# KnowledgeForest Architecture

## Overview

KnowledgeForest is a dual-layer knowledge system built on Supabase (PostgreSQL + Edge Functions). It separates **what you know** (a shared global graph) from **how you see it** (a tenant-specific forest that emerges from behavioral signals).

**Stack:**
- Frontend: React + Three.js (3D visualization), Vite
- Backend: Supabase Edge Functions (Deno)
- Database: PostgreSQL with `pgvector` and `pg_trgm` extensions
- Embeddings: OpenAI `text-embedding-3-small` (1536 dimensions)
- Job scheduling: `pg_cron` for nightly forest recomputation

---

## Data Model

### Global Graph (Shared Truth)

The global graph is append-friendly and shared across all tenants.

#### `pointers`
The core entity table. Every piece of knowledge — a company, person, document, event — is a pointer.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `uuid` | Primary key |
| `label` | `text` | Human-readable name |
| `type` | `pointer_type` (enum) | e.g. `company`, `person`, `document`, `event` |
| `canonical_key` | `text` | Stable external identifier (ticker, content hash, etc.); `UNIQUE` |
| `metadata` | `jsonb` | Arbitrary structured data |
| `embedding` | `vector(1536)` | OpenAI embedding for semantic ops |
| `occurred_at` | `timestamptz` | Domain event time (email sent, doc published). Falls back to `created_at` |
| `search_text` | `tsvector` | Full-text search index (generated column) |

**Indexes:**
- HNSW on `embedding` — cosine similarity search (`<=>`)
- GiST trigram on `label` — fuzzy label matching (`%` operator)
- GIN on `metadata` — fast JSONB attribute lookups
- B-tree on `COALESCE(occurred_at, created_at) DESC` — recency sort

#### `edges`
Directed relationships between pointers.

| Column | Type | Notes |
|--------|------|-------|
| `source_id` | `uuid` | FK → `pointers.id` |
| `target_id` | `uuid` | FK → `pointers.id` |
| `relationship_type` | `text` | e.g. `describes`, `invested_in`, `attended` |
| `why` | `text` | Human-readable rationale |
| `payload` | `jsonb` | Additional relationship data |
| `weight` | `real` | Relationship strength (default 1.0) |

Unique constraint on `(source_id, target_id, relationship_type)` — prevents duplicate edges.

#### `attributes_kv`
Flexible key-value properties per pointer. Intentionally separate from `pointers` to allow schema evolution without migrations.

| Column | Type | Notes |
|--------|------|-------|
| `pointer_id` | `uuid` | FK → `pointers.id` |
| `key` | `text` | Attribute name (e.g. `Stage`, `Sector`) |
| `value` | `jsonb` | Attribute value |
| `data_type` | `text` | `string`, `number`, `boolean`, etc. |
| `sort_order` | `int` | Display ordering |
| `source` | `text` | Provenance (`api`, `batch`, etc.) |

Unique constraint on `(pointer_id, key)` enables **upsert semantics**: re-ingesting an entity updates its attribute values rather than duplicating rows.

#### `document_chunks`
Ordered text segments for documents. Concatenating chunks by `sequence` reconstructs the original document.

| Column | Type | Notes |
|--------|------|-------|
| `pointer_id` | `uuid` | FK → `pointers.id` |
| `sequence` | `int` | Chunk order (0-indexed) |
| `content` | `text` | Chunk text |
| `heading` | `text` | Last markdown heading seen before this chunk |
| `embedding` | `vector(1536)` | Per-chunk embedding for retrieval |

Unique constraint on `(pointer_id, sequence)`.

#### `duplicate_flags`
Review queue for potential duplicates that didn't meet the auto-merge threshold.

| Column | Type | Notes |
|--------|------|-------|
| `pointer_id_a` | `uuid` | Always `< pointer_id_b` (canonical ordering) |
| `pointer_id_b` | `uuid` | |
| `similarity_score` | `real` | Combined score |
| `trigram_score` | `real` | Label trigram similarity |
| `embedding_score` | `real` | Cosine similarity |
| `match_method` | `text` | How the match was detected |
| `resolution` | `text` | `pending`, `merged`, `rejected` |

#### `system_config`
Key-value store for adaptive thresholds.

| Key | Default | Meaning |
|-----|---------|---------|
| `dedup_auto_merge_threshold` | `0.8` | Score above which pointers auto-merge |
| `dedup_review_threshold` | `0.4` | Score above which pointers go to review |

#### `schema_vocabulary`
Describes pointer types and attribute keys for agent context — so LLM-based workflows can resolve schema without hardcoding.

---

### Tenant-Specific Forest (Subjective View)

These tables are per-tenant and contain structure that **emerges from usage**, not from upfront taxonomy.

| Table | Purpose |
|-------|---------|
| `tenants` | Registry of tenants (`id`, `name`) |
| `query_paths` | Navigation session logs (`tenant_id`, `pointer_ids[]`, `query_text`) |
| `tenant_coaccess` | Co-access weight matrix: how often two pointers are accessed together |
| `tenant_coaccess_cursor` | Incremental computation state for threshold detection |
| `tenant_trees` | Dynamically computed tree nodes (`label`, `subtitle`, `type`, `pos real[]`) |
| `tenant_branches` | Dynamically computed branches within trees (`pointer_ids uuid[]`) |
| `tenant_pointer_assignments` | Denormalized lookup: `pointer_id → branch_id → tree_id` |
| `forest_computation_jobs` | Job queue for forest rebuild (`status`, `trigger_reason`) |
| `naming_cache` | LLM-generated branch/tree names (cached to avoid re-generation) |

---

## Write Path: Ingestion

Three Edge Functions handle all writes. They all converge on the same PostgreSQL RPC.

### Edge Function: `insert-pointer`
**File:** `supabase/functions/insert-pointer/index.ts`
**Use case:** Single entity with optional attributes.

```
POST /functions/v1/insert-pointer
{
  "label": "Acme Corp",
  "type": "company",
  "canonical_key": "acme-corp",       // optional
  "metadata": { "sector": "SaaS" },   // optional
  "occurred_at": "2024-01-15T00:00Z", // optional
  "attributes": [                      // optional
    { "key": "Stage", "value": "Series B", "data_type": "string" }
  ]
}
```

**Steps:**
1. Validate `label` and `type` are present
2. Generate embedding: `label + JSON.stringify(metadata)` via OpenAI `text-embedding-3-small`
3. Call `insert_pointer_with_dedup()` RPC
4. Upsert `attributes` to `attributes_kv` on **all outcomes** (created, merged, pending_review) — on `merged` this is the enrichment path
5. Set `occurred_at` if provided; on `merged`, only fills a `NULL` slot (never overwrites existing domain time)

**Returns:** `{ status, pointer_id, duplicates[] }`

---

### Edge Function: `ingest-document`
**File:** `supabase/functions/ingest-document/index.ts`
**Use case:** Long-form text (memos, reports, emails).

```
POST /functions/v1/ingest-document
{
  "title": "Q4 Investment Memo",
  "content": "...",
  "occurred_at": "2024-01-15T00:00Z",
  "chunk_size": 1200,                  // optional, default 1200 chars
  "link": {                            // optional edge to an entity
    "target_canonical_key": "acme-corp",
    "relationship_type": "describes"
  }
}
```

**Steps:**
1. Compute `SHA256(content)` → `canonical_key = "doc:<hash>"`  
   This makes byte-identical re-uploads deduplicate to the same pointer, regardless of source.
2. Chunk content on paragraph boundaries (non-overlapping; preserves markdown heading context per chunk)
3. Single OpenAI batch call: embed `title + content[:4000]` plus all chunks
4. Call `insert_pointer_with_dedup()` for the document pointer
5. On `created` or `pending_review`: insert all chunk rows to `document_chunks` (skipped on `merged` — same hash means chunks already exist)
6. Optionally resolve target by `target_id`, `target_canonical_key`, or `target_label`, then insert edge to `edges`

**Content limits:** 500,000 characters max; chunks are at most `chunk_size` characters.

---

### Edge Function: `ingest-batch`
**File:** `supabase/functions/ingest-batch/index.ts`
**Use case:** Bulk ingestion (up to 50 items).

```
POST /functions/v1/ingest-batch
{
  "source": "crm-export",
  "items": [
    { "label": "...", "type": "company", "attributes": [...] },
    ...
  ]
}
```

**Steps:**
1. Single OpenAI call to embed all items at once
2. **Sequential** processing per item (not parallel) — so that item N can deduplicate against items 0..N-1 ingested earlier in the same batch
3. Upsert attributes for each item
4. Returns a summary: `{ total, created, merged, pending_review, errors }`

---

### RPC: `insert_pointer_with_dedup()`
**File:** `supabase/migrations/20260611140000_dedup_respect_canonical_key_mismatch.sql`

This is the single insert contract for all three Edge Functions. It enforces three-tier deduplication:

```
                         ┌─────────────────────────────────┐
                         │ call check_duplicates()          │
                         │ (trigram + embedding similarity) │
                         └────────────┬────────────────────┘
                                      │
               ┌──────────────────────┼───────────────────────┐
               │ no matches           │ score 0.4–0.8          │ score ≥ 0.8
               ▼                      ▼                        ▼
          CREATED              PENDING_REVIEW            check canonical_key
      (clean insert)       (insert + flag dupes)              │
                                                   ┌──────────┴───────────┐
                                          both have different        no conflict
                                          non-null canonical_keys         │
                                                   │                      ▼
                                                   ▼               AUTO_MERGE
                                           PENDING_REVIEW      (return existing
                                      (identity conflict;        pointer_id)
                                       declared distinct)
```

**Scoring** (`check_duplicates()`):
- Trigram similarity on `label` via `pg_trgm`
- Cosine distance on `embedding` via `pgvector` (`<=>`)
- Combined score used for threshold comparison

**Canonical key conflict rule:** Two pointers with *different* non-null `canonical_key` values are declared distinct identities. Even at similarity ≥ 0.8, they must not auto-merge (e.g. "Batch Testco Alpha" vs "Batch Testco Beta" score high on label similarity but have different canonical keys — they go to review, not merge).

**Thresholds are adaptive:** After human resolutions accumulate in `duplicate_flags`, `recompute_dedup_thresholds()` adjusts the `system_config` values to match actual judgment patterns.

---

## Read Path: Retrieval

### Quick Search
**Hook:** `src/hooks/useKnowledgeSearch.js` → `quickSearch()`

Fired on every keystroke with 300ms debounce. No LLM, no embedding generation. Uses a generation counter to discard stale responses from in-flight requests.

```
User types → debounce 300ms → RPC search_hierarchy_aware(query, tenant_id, null, null, 15)
```

Returns results tagged with source: `search`, `coaccess`, or `graph`.

---

### Deep Search
**Hook:** `src/hooks/useKnowledgeSearch.js` → `deepSearch()`

Fired on Enter or explicit "Ask". Cancels any previous in-flight request via `AbortController`.

```
User presses Enter → POST /functions/v1/query-knowledge
                     { query, mode: "answer" }
                   → { results[], answer, plan, suggestions[] }
```

The `query-knowledge` Edge Function runs an LLM query planner that uses `schema_vocabulary` for context, calls `search_hierarchy_aware()` for entry points, and composes a natural-language answer with follow-up suggestions.

---

### RPC: `search_hierarchy_aware()`

Three-stage pipeline that personalizes results without separate per-tenant indexes.

```
Stage 1: SEARCH
  search_knowledge(query)
  → hybrid: tsvector full-text + trigram label matching
  → entry point pointers with relevance scores

Stage 2: COACCESS
  search_by_coaccess(tenant_id, entry_point_ids)
  → expand via tenant_coaccess weight matrix
  → pointers co-accessed with entry points, weighted by frequency

Stage 3: GRAPH
  traverse_graph(entry_point_ids)
  → walk edges table 1–2 hops from entry points
  → structurally connected pointers

Deduplication: keep highest score per pointer_id
Ordering: search results → coaccess results → graph results
```

**Cold-start behavior:** A new tenant with no co-access history still gets results from stages 1 and 3. The behavioral layer (stage 2) adds personalization as usage accumulates.

---

### RPC: `search_pointers()`
**File:** `supabase/migrations/20260611120100_add_search_pointers_rpc.sql`  
**Wrapper:** `src/lib/searchPointers.js`

Deterministic filtered search. Used by structured workflows and agents that resolve filters via `schema_vocabulary`.

```sql
search_pointers(
  p_types        text[],       -- filter by pointer type
  p_date_from    timestamptz,  -- event time range (COALESCE occurred_at, created_at)
  p_date_to      timestamptz,
  p_attr_filters jsonb,        -- exact attribute match: { "Stage": "Series B" }
  p_query_text   text,         -- full-text + trigram label search
  p_embedding    vector,       -- optional semantic ranking
  p_limit        int,          -- 1–100, default 20
  p_offset       int
)
→ { total, results[] }         -- results include attributes as ordered array
```

**Ranking:** `ts_rank(search_text, tsquery) + similarity(label, query_text) + (1 - cosine_distance)`  
**Sort:** rank DESC, then `COALESCE(occurred_at, created_at) DESC`

---

### Forest Loading
**Hook:** `src/hooks/useForestData.js`  
**Adapter:** `src/lib/forestAdapter.js`

```
useForestData() mount
  └─ if VITE_FEATURE_SUPABASE=true && VITE_KIBO_TENANT_ID set
       └─ RPC get_tenant_forest(tenant_id)
            └─ adaptForest() transforms RPC response → 3D scene shape
                 └─ trees[]: { id, label, subtitle, type, pos[x,y,z], branches[] }
                 └─ branchIndex: { branchId: { tree, branch } }   (O(1) lookup)
  └─ falls back to static TREES from src/data/trees.js on error
```

---

## Forest Growth: Nightly Dreamcycle

The forest structure is not declared — it **emerges** from how users navigate the knowledge graph.

```
1. User navigates pointers in the app
   └─ Edge Function log-query-path()
        ├─ INSERT into query_paths
        ├─ Generate co-access pairs (proximity-weighted by session recency)
        └─ UPSERT into tenant_coaccess

2. pg_cron runs trigger_nightly_forest_compute() at 03:00 UTC
   └─ For each tenant: count pairs in tenant_coaccess WHERE proximity_weight >= 2.0
        └─ If count >= 10 (minimum signal guard):
             ├─ INSERT forest_computation_jobs (status='pending')
             └─ HTTP POST to compute-forest Edge Function

3. compute-forest Edge Function
   ├─ Fetch co-access edges above weight threshold
   ├─ Union-Find clustering → branches
   ├─ Agglomerative merge → trees (capped at 12)
   ├─ LLM naming via gpt-4o-mini
   ├─ Jaccard stability mapping (preserve IDs for unchanged clusters)
   └─ UPDATE tenant_trees, tenant_branches, tenant_pointer_assignments

4. Next poll: useForestData() refetches → 3D visualization updates
```

**Minimum signal guard:** The compute step **deletes and rebuilds** all tenant tree/branch rows. Firing it on thin signal (< 10 co-access pairs) would wipe the seed forest and produce a degenerate result. The guard ensures meaningful behavioral data exists before restructuring.

---

## Data Flow Summary

```
                         WRITE PATH
                         ──────────

  API caller / UI
       │
       ├── insert-pointer ──────────┐
       ├── ingest-document ─────────┤  generate embedding (OpenAI)
       └── ingest-batch ────────────┘         │
                                              ▼
                               insert_pointer_with_dedup() RPC
                                   ├── created   → INSERT pointers
                                   ├── merged    → return existing id
                                   └── pending_review → INSERT + flag
                                              │
                               ┌─────────────┴──────────────┐
                               ▼                             ▼
                      UPSERT attributes_kv         INSERT document_chunks
                      (enriches on merge)          (only on created/pending)
                               │
                               ▼
                     INSERT edges  (optional, document link)


                         READ PATH
                         ─────────

  User types                             User presses Enter
      │                                         │
      ▼ 300ms debounce                          ▼
  search_hierarchy_aware()            POST query-knowledge
  ┌─────────────────────┐            (Edge Function, LLM)
  │ 1. search_knowledge │                      │
  │ 2. coaccess expand  │◄─────────────────────┘
  │ 3. graph traverse   │        calls same RPC for entry points
  └─────────────────────┘
          │
          ▼
  Results tagged: search | coaccess | graph
```

---

## Configuration

```env
VITE_SUPABASE_URL=https://<project>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon-key>
VITE_FEATURE_SUPABASE=true          # enables live data; false uses static fallback
VITE_KIBO_TENANT_ID=<tenant-uuid>   # which tenant's forest to render
```

Edge Functions read `SUPABASE_SERVICE_ROLE_KEY` and `OPENAI_API_KEY` from Supabase secrets (not exposed to the frontend).

---

## Key Files

| File | Role |
|------|------|
| `supabase/functions/insert-pointer/index.ts` | Single entity ingestion |
| `supabase/functions/ingest-document/index.ts` | Document ingestion + chunking |
| `supabase/functions/ingest-batch/index.ts` | Bulk ingestion (≤50 items) |
| `supabase/migrations/20260611140000_dedup_*.sql` | `insert_pointer_with_dedup()` RPC |
| `supabase/migrations/20260611120100_add_search_pointers_rpc.sql` | `search_pointers()` RPC |
| `supabase/migrations/20260611130100_nightly_forest_compute_cron.sql` | pg_cron schedule + trigger |
| `supabase/migrations/20260611130000_unique_attribute_per_pointer_key.sql` | Upsert constraint on `attributes_kv` |
| `supabase/migrations/20260611120000_add_occurred_at_to_pointers.sql` | `occurred_at` column + event-time index |
| `src/hooks/useKnowledgeSearch.js` | Quick + deep search hook |
| `src/hooks/useForestData.js` | Forest loading with static fallback |
| `src/lib/forestAdapter.js` | RPC response → 3D scene shape |
| `src/lib/searchPointers.js` | Wrapper for `search_pointers()` RPC |
| `src/lib/supabase.js` | Supabase client initialization |
