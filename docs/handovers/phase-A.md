# Phase A Handover: Supabase Setup + Schema

## What was built

A new Supabase project **KnowledgeForest** (`rkuyvzcxaoulhjiflrmp`) in `eu-central-1` under the ConCoord organization, with the complete database schema for the MVP.

### Migrations applied (5 total)

1. **001_extensions_and_enums** — Enabled `pg_trgm` (v1.6), `vector` (v0.8.0), `moddatetime` (v1.0). Created enums: `pointer_type`, `duplicate_resolution`, `attribute_data_type`.

2. **002_core_global_tables** — Created 7 tables:
   - `pointers` — Graph nodes with label, type, canonical_key, metadata JSONB, embedding vector(1536). Indexes: GiST trigram on label, HNSW cosine on embedding, btree on type, GIN on metadata, unique on canonical_key.
   - `edges` — Directed relationships with why, payload JSONB, weight. Unique on (source_id, target_id, relationship_type).
   - `attributes_kv` — Flexible key-value attributes per pointer with data_type enum, sort_order, source provenance, confidence score.
   - `document_chunks` — Ordered chunks with sequence, content, heading, embedding. Unique on (pointer_id, sequence).
   - `timeseries_data` — Time-indexed values with metric_name. Indexed on (pointer_id, metric_name, ts DESC).
   - `duplicate_flags` — Flagged duplicates with trigram_score, embedding_score, combined similarity_score, resolution status. CHECK constraint ensures pointer_id_a < pointer_id_b.
   - `system_config` — Adaptive thresholds. Seeded with `dedup_auto_merge_threshold=0.8`, `dedup_review_threshold=0.4`.

3. **003_tenant_tables** — Created 11 tables:
   - `tenants` — Multi-tenant registry.
   - `query_paths` — Navigation session logging (tenant_id, session_id, pointer_ids UUID[], query_text).
   - `tenant_coaccess` — Materialized co-access weights per tenant pair.
   - `tenant_coaccess_cursor` — Incremental processing state for threshold checks.
   - `tenant_trees` — Dynamically generated tree structures per tenant (with is_seed flag for cold start).
   - `tenant_branches` — Dynamically generated branches with pointer_ids array.
   - `tenant_pointer_assignments` — Denormalized pointer-to-branch-to-tree lookup.
   - `tenant_structure_mapping` — Old-to-new branch/tree mapping for stability (Jaccard overlap).
   - `tenant_structure_events` — Adaptation signals (splits, merges, pointer moves).
   - `forest_computation_jobs` — Job queue for tree recomputation.
   - `naming_cache` — LLM-generated names for branches/trees.

4. **004_rpc_functions** — Created 7 RPC functions:
   - `check_duplicates(label, type, canonical_key?, embedding?, threshold?)` — Multi-method duplicate detection.
   - `insert_pointer_with_dedup(label, type, canonical_key?, metadata?, embedding?)` — Tiered insertion: auto-merge (>=threshold), block for review, or clean insert.
   - `get_pointer_subgraph(pointer_id)` — Full pointer detail with attributes, edges, chunks, timeseries.
   - `get_tenant_forest(tenant_id)` — Per-tenant forest for 3D visualization.
   - `upsert_coaccess_batch(tenant_id, pairs)` — Bulk co-access weight update.
   - `update_coaccess_cursor(tenant_id, path_id, new_edges)` — Incremental cursor + threshold check, returns boolean for recompute.
   - `recompute_dedup_thresholds()` — Adaptive threshold update from resolution history (needs 50+ resolutions).

5. **005_rls_policies** — RLS enabled on all 18 tables. Policy: public/anon read on visualization tables (pointers, edges, attributes, trees, branches), authenticated read/write on all tables.

### Bug found and fixed during testing

The `insert_pointer_with_dedup` function had a bug in the auto-merge branch: it tried to log a `duplicate_flags` entry using `gen_random_uuid()` as a placeholder pointer ID, which violated the foreign key constraint (no pointer with that UUID exists). Fixed by removing the flags insert from the auto-merge path — auto-merges don't need human review, so no flag is needed.

## How to verify it works

### 1. Check tables exist (18 expected)
```sql
SELECT name, rls_enabled, rows FROM information_schema.tables 
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
```
Or use Supabase MCP: `list_tables(project_id='rkuyvzcxaoulhjiflrmp')`

### 2. Check extensions
```sql
SELECT extname, extversion FROM pg_extension WHERE extname IN ('pg_trgm', 'vector', 'moddatetime');
-- Expected: pg_trgm 1.6, vector 0.8.0, moddatetime 1.0
```

### 3. Check system_config seeded
```sql
SELECT * FROM system_config;
-- Expected: 2 rows (dedup_auto_merge_threshold=0.8, dedup_review_threshold=0.4)
```

### 4. Test clean insert
```sql
SELECT insert_pointer_with_dedup('TestCompany', 'company', NULL, '{}'::jsonb, NULL);
-- Expected: {"status": "created", "pointer_id": "<uuid>", "duplicates": []}
```

### 5. Test trigram dedup (run after step 4)
```sql
SELECT insert_pointer_with_dedup('TestCmpany', 'company', NULL, '{}'::jsonb, NULL);
-- Expected: {"status": "pending_review", "duplicates": [...], "pointer_id": "<new-uuid>"}
```

### 6. Test auto-merge via canonical key
```sql
-- First insert with canonical key
SELECT insert_pointer_with_dedup('Apple Inc', 'company', 'AAPL', '{}'::jsonb, NULL);
-- Then try same canonical key
SELECT insert_pointer_with_dedup('Apple', 'company', 'AAPL', '{}'::jsonb, NULL);
-- Expected: {"status": "merged", "pointer_id": "<same-uuid-as-first>", "duplicates": [...]}
```

### 7. Test get_tenant_forest returns empty for non-existent tenant
```sql
SELECT get_tenant_forest('00000000-0000-0000-0000-000000000000'::UUID);
-- Expected: [] (empty array, no error)
```

### 8. Clean up test data after verification
```sql
DELETE FROM duplicate_flags;
DELETE FROM pointers;
```

## Design decisions made during implementation

1. **HNSW index on embedding created immediately** (not deferred) — Since we're using embeddings in MVP for dedup, the index is needed from day 1. Cost: slightly slower inserts, but enables fast cosine similarity searches.

2. **Auto-merge doesn't log to duplicate_flags** — The original plan had it logging, but since no new pointer is created in auto-merge (we return the existing one), there's nothing to flag. This simplifies the function and avoids the FK violation bug.

3. **RLS is permissive for MVP** — All authenticated users can read/write everything. Per-tenant RLS (where each tenant only sees their own data) is deferred to post-MVP.

4. **moddatetime installed in `extensions` schema** — Supabase convention; the trigger references `extensions.moddatetime()`.

## Known issues / shortcuts taken

1. **No tenant-scoped RLS** — Any authenticated user can read/write any tenant's data. This is a known MVP shortcut.
2. **Embedding index created on empty table** — HNSW index works but is suboptimal when first populated. Consider `REINDEX` after initial seed.
3. **`get_tenant_forest` aggregates all attributes per branch** — For branches with many pointers, this could return large payloads. May need pagination post-MVP.
4. **`insert_pointer_with_dedup` scans all pointers of same type** — For large pointer counts (>10K), the trigram GiST index handles it, but the embedding HNSW scan could be slow without `LIMIT` tuning.

## Dependencies for next phase

Phase B (Edge Functions + Seed Data) needs:
- **Supabase project ID**: `rkuyvzcxaoulhjiflrmp`
- **Supabase project URL**: `https://rkuyvzcxaoulhjiflrmp.supabase.co`
- **Supabase anon key**: Retrieve from Supabase dashboard → Settings → API
- **Supabase service role key**: Needed for Edge Functions to bypass RLS
- **OpenAI API key**: Needed for embedding generation in the `insert-pointer` Edge Function
- All RPC functions are callable via `supabase.rpc('function_name', {params})`

## Files to review

No files were created in the project directory — all work was done via Supabase migrations (stored in Supabase's migration history). The auditor should:

1. Run `list_tables` to verify all 18 tables exist with RLS enabled
2. Run the verification SQL queries above (steps 1-7)
3. Check each RPC function signature matches the plan in `/Users/joseguardo/.claude/plans/greedy-dancing-jellyfish.md`
4. Verify the `insert_pointer_with_dedup` function handles all three tiers correctly
5. Check that `get_tenant_forest` output shape is compatible with what `buildScene.js` expects (trees → branches → leaves/links)
