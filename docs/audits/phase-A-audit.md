# Phase A Audit: Supabase Setup + Schema

**Auditor**: Claude Opus 4.6 (fresh context, no prior conversation)
**Date**: 2026-06-10
**Project**: `rkuyvzcxaoulhjiflrmp` (eu-central-1)

---

## Summary

Phase A is **PASS with 1 blocking fix applied**. The schema is complete, all 18 tables exist with RLS enabled, all 7 RPC functions are present, and the core dedup pipeline works correctly. One blocking bug was found and fixed (`get_pointer_subgraph` alias collision), and one data quality improvement was applied (empty label CHECK constraint).

---

## Verification Steps (Handover Steps 1-8)

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | 18 tables exist with RLS | **PASS** | All 18 tables confirmed: pointers, edges, attributes_kv, document_chunks, timeseries_data, duplicate_flags, system_config, tenants, query_paths, tenant_coaccess, tenant_coaccess_cursor, tenant_trees, tenant_branches, tenant_pointer_assignments, tenant_structure_mapping, tenant_structure_events, forest_computation_jobs, naming_cache. All have `rls_enabled: true`. |
| 2 | Extensions installed | **PASS** | pg_trgm 1.6, vector 0.8.0, moddatetime 1.0 |
| 3 | system_config seeded | **PASS** | `dedup_auto_merge_threshold=0.8`, `dedup_review_threshold=0.4` |
| 4 | Clean insert | **PASS** | `insert_pointer_with_dedup('TestCompany', 'company', ...)` returned `{"status": "created", "pointer_id": "<uuid>", "duplicates": []}` |
| 5 | Trigram dedup | **PASS** | `insert_pointer_with_dedup('TestCmpany', 'company', ...)` returned `{"status": "pending_review", ...}` with trigram_score 0.643 |
| 6 | Canonical key auto-merge | **PASS** | First insert `Apple Inc` with key `AAPL` created. Second insert `Apple` with key `AAPL` returned `{"status": "merged", "pointer_id": "<same-uuid>"}` |
| 7 | Empty tenant forest | **PASS** | `get_tenant_forest('00000000-...')` returned `[]` (empty array, no error) |
| 8 | Test data cleanup | **PASS** | All test data deleted, all tables at 0 rows |

---

## Correctness

| Check | Result | Notes |
|-------|--------|-------|
| All three dedup tiers work | **PASS** | created, merged, pending_review all produce correct JSONB shapes |
| NULL type rejected | **PASS** | Correctly throws NOT NULL constraint violation |
| Empty label previously accepted | **FIXED** | Was allowed -- added CHECK constraint `length(trim(label)) > 0` |
| Duplicate edges rejected | **PASS** | Unique constraint `(source_id, target_id, relationship_type)` works |
| CHECK on `pointer_id_a < pointer_id_b` | **PASS** | Inserting with reversed UUIDs correctly fails |
| CHECK on `pointer_a < pointer_b` (coaccess) | **PASS** | Constraint present, and `upsert_coaccess_batch` uses LEAST/GREATEST |
| `recompute_dedup_thresholds()` with no data | **PASS** | Returns `{"status": "insufficient_data", "total_resolutions": 0, "needed": 50}` |
| `get_pointer_subgraph` on non-existent pointer | **PASS** | Returns `null` (not an error) |

---

## Completeness

### Tables (Plan Section 1)

| Table | Status | Notes |
|-------|--------|-------|
| pointers | **PASS** | All columns match plan. Includes vector(1536). |
| edges | **PASS** | ON DELETE CASCADE on both FK columns. |
| attributes_kv | **PASS** | Includes data_type enum, sort_order, source, confidence. |
| document_chunks | **PASS** | Unique on (pointer_id, sequence). Extra columns: char_count (generated), metadata. |
| timeseries_data | **PASS** | Extra column: source (provenance). |
| duplicate_flags | **PASS** | CHECK constraint a < b present. |
| system_config | **PASS** | Seeded with 2 threshold rows. |
| tenants | **PASS** | |
| query_paths | **PASS** | Includes pointer_ids UUID[], session_id, user_id, agent_id. |
| tenant_coaccess | **PASS** | Unique on (tenant_id, pointer_a, pointer_b). CHECK a < b. |
| tenant_coaccess_cursor | **PASS** | PK on tenant_id. |
| tenant_trees | **PASS** | Extra column: branch_ids UUID[]. |
| tenant_branches | **PASS** | Extra column: internal_cohesion. |
| tenant_pointer_assignments | **PASS** | PK on (tenant_id, pointer_id). |
| tenant_structure_mapping | **PASS** | CHECK entity_type IN ('branch','tree'). |
| tenant_structure_events | **PASS** | Includes acknowledged boolean. |
| forest_computation_jobs | **PASS** | CHECK status IN ('pending','running','completed','failed'). Extra columns: error_message, result_summary. |
| naming_cache | **PASS** | Not in plan Section 1 but referenced in handover. Unique on entity_id. |

### RPC Functions (Plan Section 4)

| Function | Status | Notes |
|----------|--------|-------|
| `check_duplicates(label, type, canonical_key?, embedding?, threshold?)` | **PASS** | Returns TABLE with pointer_id, label, match_method, trigram_sim, embedding_sim, combined_sim |
| `insert_pointer_with_dedup(label, type, canonical_key?, metadata?, embedding?)` | **PASS** | Returns JSONB with status, pointer_id, duplicates |
| `get_pointer_subgraph(pointer_id)` | **FIXED** | Was broken (see Blocking Issues). Now returns pointer + attributes + edges + chunks + timeseries |
| `get_tenant_forest(tenant_id)` | **PASS** | Returns JSONB array of trees with branches |
| `upsert_coaccess_batch(tenant_id, pairs)` | **PASS** | Bulk upsert with ON CONFLICT increment |
| `update_coaccess_cursor(tenant_id, path_id, new_edges)` | **PASS** | Returns boolean for recompute. Present in DB but not listed in plan Section 4 -- correctly added per handover |
| `recompute_dedup_thresholds()` | **PASS** | Returns JSONB with status and threshold values |

### Indexes (Plan Section 1)

| Index | Status | Notes |
|-------|--------|-------|
| GiST trigram on pointers.label | **PASS** | `idx_pointers_label_trgm` |
| HNSW cosine on pointers.embedding | **PASS** | `idx_pointers_embedding` using vector_cosine_ops |
| btree on pointers.type | **PASS** | `idx_pointers_type` |
| GIN on pointers.metadata | **PASS** | `idx_pointers_metadata` |
| Unique on pointers.canonical_key (partial, WHERE NOT NULL) | **PASS** | `idx_pointers_canonical_key` |
| Unique on edges (source, target, type) | **PASS** | `idx_edges_unique_pair` |
| Unique on document_chunks (pointer_id, sequence) | **PASS** | `idx_doc_chunks_order` |
| btree on timeseries (pointer_id, metric_name, ts DESC) | **PASS** | `idx_timeseries_metric` |
| Unique partial on duplicate_flags (pending only) | **PASS** | `idx_duplicate_pair` |
| Unique on tenant_coaccess (tenant_id, pointer_a, pointer_b) | **PASS** | Built-in unique constraint index |

### moddatetime Triggers

| Table | Status |
|-------|--------|
| pointers | **PASS** |
| edges | **PASS** |
| attributes_kv | **PASS** |
| tenant_trees | **PASS** |
| tenant_branches | **PASS** |

---

## Quality

### SQL Injection Risk

| Function | Risk | Notes |
|----------|------|-------|
| `check_duplicates` | **NONE** | Uses parameterized queries via PL/pgSQL variables. No string concatenation. |
| `insert_pointer_with_dedup` | **NONE** | All inputs bound as typed parameters. JSONB built via `jsonb_build_object`. |
| `get_pointer_subgraph` | **NONE** | Single UUID parameter used in WHERE clause. |
| `get_tenant_forest` | **NONE** | Single UUID parameter. |
| `upsert_coaccess_batch` | **NONE** | JSONB array elements extracted via `->>'key'` with explicit casts. |
| `update_coaccess_cursor` | **NONE** | Typed parameters only. |
| `recompute_dedup_thresholds` | **NONE** | No user input. Reads from duplicate_flags and writes to system_config. |

### ON DELETE CASCADE Chains

| Scenario | Result | Verified |
|----------|--------|----------|
| Delete pointer -> attributes_kv | **PASS** | Tested: 1 attribute cascaded |
| Delete pointer -> edges | **PASS** | Tested: 1 edge cascaded |
| Delete pointer -> document_chunks | **PASS** | Tested: 1 chunk cascaded |
| Delete pointer -> timeseries_data | **PASS** | Tested: 1 timeseries row cascaded |
| Delete pointer -> duplicate_flags | **PASS** | Tested: 1 flag cascaded |
| Delete pointer -> tenant_coaccess | **PASS** | FK with CASCADE present |
| Delete pointer -> tenant_pointer_assignments | **PASS** | FK with CASCADE present |
| Delete tenant -> all tenant tables | **PASS** | All 9 tenant-dependent tables have CASCADE FKs |
| Delete tenant_tree -> tenant_branches | **PASS** | FK with CASCADE present |
| Delete tenant_branch -> tenant_pointer_assignments | **PASS** | FK with CASCADE present |

### RLS Policies

| Table | anon SELECT | auth SELECT | auth INSERT | auth UPDATE | auth DELETE | Notes |
|-------|-------------|-------------|-------------|-------------|-------------|-------|
| pointers | YES | YES | YES | YES | YES | |
| edges | YES | YES | YES | YES | YES | |
| attributes_kv | YES | YES | YES | YES | - | No DELETE policy (minor) |
| document_chunks | YES | YES | YES | - | - | No UPDATE/DELETE (minor) |
| timeseries_data | YES | YES | YES | - | - | No UPDATE/DELETE (minor) |
| duplicate_flags | - | YES | YES | YES | - | No anon read (correct) |
| system_config | YES | YES | - | YES | - | No INSERT (correct, seeded) |
| tenants | YES | YES | YES | - | - | No UPDATE/DELETE |
| query_paths | - | YES | YES | - | - | No anon read (correct) |
| tenant_coaccess | - | YES | YES | YES | - | No anon read (correct) |
| tenant_coaccess_cursor | - | YES | YES | YES | - | No anon read (correct) |
| tenant_trees | YES | YES | YES | YES | YES | |
| tenant_branches | YES | YES | YES | YES | YES | |
| tenant_pointer_assignments | YES | YES | YES | - | YES | No UPDATE |
| tenant_structure_mapping | - | YES | YES | - | - | No anon read (correct) |
| tenant_structure_events | - | YES | YES | YES | - | No anon read (correct) |
| forest_computation_jobs | - | YES | YES | YES | - | No anon read (correct) |
| naming_cache | YES | YES | YES | YES | - | |

Public/anon read is correctly scoped to visualization tables only.

---

## Interface Contracts

### `get_tenant_forest()` output shape vs. buildScene.js expectations

The function returns:
```json
[{
  "id": "<uuid>",
  "label": "AI Infra",
  "subtitle": "Semiconductors & Cloud",
  "type": "entity",
  "pos": [10, 0, 5],
  "is_seed": true,
  "version": 1,
  "branches": [{
    "id": "<uuid>",
    "name": "Chip Makers",
    "pointer_ids": ["<uuid>"],
    "leaves": ["ticker: NVDA", "sector: Semiconductors"],
    "links": [{"id": "<uuid>", "why": "chip manufacturing"}]
  }]
}]
```

**Comparison with trees.js TREES shape:**

| Field | trees.js | get_tenant_forest | Compatible? |
|-------|----------|-------------------|-------------|
| tree.id | string ("sectors") | UUID | YES - forestAdapter.js will handle |
| tree.label | "SECTOR TREE" | from t.name | **YES** |
| tree.subtitle | "Sectors" | from t.subtitle | **YES** |
| tree.type | "entity"/"system" | from t.type | **YES** |
| tree.pos | [-22, 0, -7] | REAL[3] array | **YES** |
| branch.id | "sector:cyber" | UUID | YES - forestAdapter.js will handle |
| branch.name | "Cybersecurity" | from b.name | **YES** |
| branch.leaves | ["Market: $180B", ...] | ["ticker: NVDA", ...] | **YES** - same string[] format |
| branch.links | [{id, why}] | [{id, why}] | **YES** |

**Verdict: PASS** -- The output shape is compatible. The `forestAdapter.js` (Phase C) will transform UUIDs, but the structural shape matches what buildScene.js expects.

### `insert_pointer_with_dedup()` return shapes

| Path | Shape | Consistent? |
|------|-------|-------------|
| created | `{"status": "created", "pointer_id": "<uuid>", "duplicates": []}` | **YES** |
| merged | `{"status": "merged", "pointer_id": "<existing-uuid>", "duplicates": [{...}]}` | **YES** |
| pending_review | `{"status": "pending_review", "pointer_id": "<new-uuid>", "duplicates": [{...}]}` | **YES** |

All three paths return the same top-level keys: `status`, `pointer_id`, `duplicates`. **PASS**.

---

## Blocking Issues Found and Fixed

### 1. `get_pointer_subgraph` alias collision (BLOCKING - FIXED)

**Problem**: The function used `ts` as both a subquery alias and implicitly referenced the `timeseries_data.ts` column. When `row_to_json(ts)` was called, PostgreSQL tried to call `row_to_json` on the timestamp column instead of the subquery row, causing:
```
ERROR: function row_to_json(timestamp with time zone) does not exist
```

**Fix applied**: Changed the subquery alias from `ts` to `ts_row`:
```sql
FROM (...) ts_row  -- was: ts
```

**Verified**: Function now returns correct output with all 5 sections (pointer, attributes, outbound_edges, inbound_edges, document_chunks, timeseries_latest).

### 2. Empty label accepted by insert (BLOCKING - FIXED)

**Problem**: `insert_pointer_with_dedup('', 'company', ...)` succeeded and created a pointer with an empty label. This would cause display issues in the 3D visualization and break trigram similarity scoring.

**Fix applied**: Added CHECK constraint:
```sql
ALTER TABLE pointers ADD CONSTRAINT pointers_label_not_empty CHECK (length(trim(label)) > 0);
```

**Verified**: Both empty strings and whitespace-only strings are now rejected.

---

## Non-Blocking Issues

### 1. `get_pointer_subgraph` returns NULL for non-existent pointer

The function returns `null` instead of a structured error or empty object. This is acceptable for MVP but the frontend should handle null gracefully. Phase C/D should be aware.

### 2. Missing RLS DELETE policies on some tables

`attributes_kv`, `document_chunks`, `timeseries_data`, `duplicate_flags`, `naming_cache` lack authenticated DELETE policies. This means authenticated users cannot delete individual attributes, chunks, etc. via direct table access. However, ON DELETE CASCADE from pointers handles cleanup, so this is not blocking for MVP.

### 3. `forest_computation_jobs.status` uses TEXT + CHECK instead of ENUM

The plan mentions a status ENUM for `forest_computation_jobs`, but the implementation uses a TEXT column with a CHECK constraint. Functionally equivalent but less type-safe. Non-blocking.

### 4. `get_tenant_forest` leaves are flat strings

Leaves come back as `"key: value"` strings (e.g., `"ticker: NVDA"`). This matches the current trees.js format where leaves are strings like `"Rev: $3.06B"`, so it is compatible. However, a richer object format (`{"key": "ticker", "value": "NVDA"}`) would be more useful for future features like filtering or editing leaves inline. Non-blocking for MVP.

### 5. `get_tenant_forest` aggregates ALL attributes across ALL pointers in a branch

If a branch has 20 pointers each with 10 attributes, the `leaves` array will have 200 entries. This could be slow for large branches. The handover acknowledges this (Known Issue #3). Non-blocking.

---

## Residual Items for Human Review

1. **OpenAI API key in Supabase vault** -- The plan (Phase A, item 6) says "Store OpenAI API key in Supabase vault." The handover does not mention this being done. Verify before Phase B.

2. **RLS for service role** -- The RPC functions run as the function owner (typically `postgres`), which bypasses RLS. This is correct for MVP. But Edge Functions in Phase B will need the service role key to call these functions without RLS restrictions.

3. **Embedding dimension** -- The schema uses `vector(1536)` for OpenAI text-embedding-3-small. If the model changes, a migration will be needed. This is acknowledged as deferred.

---

## Test Data Status

All test data has been cleaned up. All tables are at 0 rows (except system_config with its 2 seed rows).
