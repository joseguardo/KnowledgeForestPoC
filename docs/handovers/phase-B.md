# Phase B Handover: Edge Functions + Seed Data

## What was built

### 4 Supabase Edge Functions (all ACTIVE)

1. **`insert-pointer`** — Orchestrates pointer insertion with dedup:
   - Accepts `{ label, type, canonical_key?, metadata?, attributes? }`
   - Calls OpenAI text-embedding-3-small for embedding generation
   - Calls `insert_pointer_with_dedup` RPC (tiered dedup)
   - If created/pending_review, bulk-inserts attributes
   - Returns `{ status, pointer_id, duplicates? }`
   - Gracefully handles missing OpenAI key (inserts without embedding)

2. **`link-pointers`** — Creates edges between pointers:
   - Accepts `{ source_id, target_id, relationship_type?, why?, payload? }`
   - Validates both pointers exist (404 if not)
   - Returns 409 for duplicate edges
   - Returns created edge object

3. **`log-query-path`** — Logs navigation sessions for dynamic tree generation:
   - Accepts `{ tenant_id, session_id, pointer_ids, user_id?, agent_id?, query_text? }`
   - Inserts path into `query_paths`
   - Generates co-access pairs with proximity weighting (1/distance decay)
   - Caps at 50 pointers per path (1225 max pairs)
   - Calls `upsert_coaccess_batch` and `update_coaccess_cursor`
   - Returns `{ status, path_id, pairs_updated, recompute_triggered }`

4. **`compute-forest`** — Runs clustering pipeline for dynamic tree generation:
   - Accepts `{ tenant_id, job_id?, weight_threshold?, min_branch_size?, max_trees? }`
   - Fetches co-access edges above threshold
   - Union-Find clustering → branches (connected components)
   - Greedy agglomerative merge → trees (max 12)
   - LLM naming via OpenAI gpt-4o-mini (falls back to "Tree N" / "Branch N")
   - Stability mapping: Jaccard similarity between old and new branches
   - Emits `structure_evolved` events when changes are significant
   - Job status tracking (pending → running → completed/failed)

### Seed Data (all via SQL with deterministic UUIDs)

Using namespace UUID `a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11` with `uuid_generate_v5` for deterministic IDs.

| Table | Count | Notes |
|-------|-------|-------|
| pointers | 58 | All branches from 13 trees in trees.js |
| edges | 93 | All cross-links with typed relationships |
| attributes_kv | 75 | Parsed from leaves ("Key: Value" format) |
| tenants | 1 | Kibo (uuid_generate_v5(ns, 'tenant:kibo')) |
| tenant_trees | 13 | Mirrors TREES array with original positions |
| tenant_branches | 58 | 1:1 with pointers, each in correct tree |

### Key decisions during seeding

- **Deterministic UUIDs**: Used `uuid_generate_v5` so pointer IDs are reproducible and edges can cross-reference them. The namespace `a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11` is arbitrary but must stay consistent.
- **No embeddings in seed**: Pointers seeded without embeddings (embedding column is NULL). Backfill via the `insert-pointer` Edge Function or a separate script when OpenAI key is configured.
- **Canonical keys**: Added tickers for public companies (CRWD, AAPL, NVDA, MRNA). Private companies have NULL canonical_key.
- **Relationship types**: Edges use typed relationships (primary_sector, competitor, ceo, hq_location, uses_skill, etc.) instead of the generic "related" from trees.js.
- **Seed branches have 1 pointer each**: In the seed, each branch contains exactly 1 pointer. Dynamic clustering (Phase E) will group multiple pointers per branch based on co-access patterns.

## How to verify it works

### 1. Check counts
```sql
SELECT 
  (SELECT count(*) FROM pointers) as pointers,
  (SELECT count(*) FROM edges) as edges,
  (SELECT count(*) FROM attributes_kv) as attributes,
  (SELECT count(*) FROM tenants) as tenants,
  (SELECT count(*) FROM tenant_trees) as tenant_trees,
  (SELECT count(*) FROM tenant_branches) as tenant_branches;
-- Expected: 58, 93, 75, 1, 13, 58
```

### 2. Verify get_tenant_forest returns 13 trees
```sql
SELECT jsonb_array_length(get_tenant_forest(
  uuid_generate_v5('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::UUID, 'tenant:kibo')
)) as tree_count;
-- Expected: 13
```

### 3. Verify tree shape matches buildScene.js expectations
```sql
SELECT get_tenant_forest(
  uuid_generate_v5('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::UUID, 'tenant:kibo')
)->0 as first_tree;
-- Expected: { id, label, subtitle, type, pos, is_seed, version, branches: [{ id, name, leaves, links, pointer_ids }] }
```

### 4. Verify Edge Functions are deployed
Use Supabase MCP: `list_edge_functions(project_id='rkuyvzcxaoulhjiflrmp')`
Expected: 4 functions, all status ACTIVE (insert-pointer, link-pointers, log-query-path, compute-forest)

### 5. Test get_pointer_subgraph
```sql
SELECT get_pointer_subgraph(
  uuid_generate_v5('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::UUID, 'company:nvidia')
);
-- Expected: { pointer: {...}, attributes: [{key: "Rev", value: "$60B"}, ...], outbound_edges: [...], inbound_edges: [...] }
```

## Known issues / shortcuts taken

1. **No embeddings in seed data** — Pointers have NULL embedding. Dedup will only use trigram matching until embeddings are backfilled.
2. **OpenAI key not yet in Supabase vault** — Edge Functions gracefully handle this (insert without embedding, name with fallback) but full functionality requires the key.
3. **Edge Functions use verify_jwt=true** — They require a valid Supabase JWT in the Authorization header. For testing, use the service role key or authenticate first.
4. **compute-forest's LLM naming uses gpt-4o-mini** — This is cheaper but less accurate than a larger model. Could be upgraded.
5. **System tree attributes not seeded** — Only entity trees (sectors, companies, etc.) have attributes. System trees (agents, tools, etc.) have attributes in trees.js but were not seeded (the leaves are less structured, e.g., "Type: core", "Runtime: Node.js").

## Dependencies for next phase

Phase C (Frontend Data Layer) needs:
- **Supabase project URL**: `https://rkuyvzcxaoulhjiflrmp.supabase.co`
- **Supabase anon key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJrdXl2emN4YW91bGhqaWZscm1wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwNzk0MzAsImV4cCI6MjA5NjY1NTQzMH0.wBqZtj7oYrVA9AdSzpzFRB5nbCPZMzjfremGv3Gx2wI`
- **Kibo tenant ID**: `uuid_generate_v5('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'tenant:kibo')` = deterministic, compute at runtime
- `get_tenant_forest` RPC is the primary data source for the 3D scene
- Output shape matches what buildScene.js expects (verified)

## Files to review

- No local files created — all Edge Functions deployed via Supabase MCP
- The auditor should:
  1. Run all verification queries above
  2. Test `get_pointer_subgraph` for several pointer types (company, sector, person)
  3. Verify all 4 Edge Functions are ACTIVE
  4. Check that the `get_tenant_forest` output for each of the 13 trees has correct label, subtitle, type, pos, and non-empty branches
  5. Verify edges have correct relationship_types and why fields
