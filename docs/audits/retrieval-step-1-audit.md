# Retrieval Step 1 Audit: search_knowledge + traverse_graph

**Auditor**: Claude Opus 4.6 (1M context, fresh context -- no prior context)
**Date**: 2026-06-10
**Scope**: Migration 007 functions -- `search_knowledge`, `traverse_graph`, FTS index, RRF correctness, cycle safety, depth cap, performance
**Project**: `rkuyvzcxaoulhjiflrmp`

---

## 1. Executive Summary

**PASS -- 0 blocking issues, 1 minor observation.**

Both database functions work correctly. All handover verification queries return expected results. RRF scoring is mathematically correct. Cycle prevention works. Depth cap works. Edge cases (empty string, nonexistent term) return empty arrays gracefully. Indexes exist and are correct (seq scan at current scale is expected Postgres optimizer behavior for ~60 rows).

| Category | Status |
|----------|--------|
| search_knowledge handover queries | PASS (4/4) |
| traverse_graph handover queries | PASS (3/3) |
| RRF formula correctness | PASS (verified mathematically) |
| Cycle safety | PASS (no infinite recursion) |
| Depth cap (>3 capped to 3) | PASS |
| Edge cases (empty, nonexistent) | PASS |
| Index existence | PASS (6 relevant indexes confirmed) |
| Performance | PASS (9.3ms total, adequate for current scale) |

---

## 2. Handover Verification Queries

### 2a. search_knowledge

| Query | Expected | Actual | Status |
|-------|----------|--------|--------|
| `search_knowledge('nvidia')` | NVIDIA (trigram=1.0), Jensen Huang (attribute match) | NVIDIA (trigram=1.0, fulltext=0.061, combined=0.0328), Jensen Huang (attribute=0.636, combined=0.0164) | **PASS** |
| `search_knowledge('Kurtz')` | George Kurtz (trigram), CrowdStrike (attribute) | George Kurtz (trigram, combined=0.0328), CrowdStrike (attribute=1.0, combined=0.0164) | **PASS** |
| `search_knowledge('security', p_type_filter := 'sector')` | Cybersecurity | Cybersecurity (sector) | **PASS** |
| `search_knowledge('infrastructure') WHERE fulltext_score > 0` | AI Infrastructure | AI Infrastructure (fulltext=0.061) | **PASS** |

### 2b. traverse_graph

| Query | Expected | Actual | Status |
|-------|----------|--------|--------|
| Cybersecurity -> inbound primary_sector, company, depth 1 | CrowdStrike, Wiz | CrowdStrike, Wiz | **PASS** |
| NVIDIA -> inbound ceo, person, depth 1 | Jensen Huang | Jensen Huang | **PASS** |
| AI Infrastructure -> inbound, all types, depth 2 | ~11 results across depth 1-2 | 11 results: depth 1 (Clarity AI, Cybersecurity, EU AI Act, NVIDIA, Seedtag), depth 2 (CrowdStrike, GDPR, Jensen Huang, Spain, United States, Wiz) | **PASS** |

---

## 3. RRF Formula Correctness

### Formula review

The function uses: `score = SUM(1/(k + rank_i))` where k=60 and rank starts at 1 (via `ROW_NUMBER()`). Signals with score=0 contribute 0 (guarded by `CASE WHEN score > 0`).

### Manual verification for `search_knowledge('nvidia')`

**NVIDIA**: trigram_score=1.0 (rank 1), fulltext_score=0.061 (rank 1). Two active signals.
- RRF = 1/(60+1) + 1/(60+1) = 2/61 = **0.032787**
- Returned: **0.0327869** -- MATCH

**Jensen Huang**: attribute_score=0.636 (rank 1). One active signal.
- RRF = 1/(60+1) = 1/61 = **0.016393**
- Returned: **0.0163934** -- MATCH

**Verdict**: RRF implementation is mathematically correct.

---

## 4. Edge Cases

| Test | Result | Status |
|------|--------|--------|
| `search_knowledge('')` | Empty array `[]` | **PASS** -- no crash, no spurious results |
| `search_knowledge('xyznonexistent')` | Empty array `[]` | **PASS** -- no crash, no spurious results |

---

## 5. Cycle Safety

**Test setup**: Created two `meta` pointers (A, B) with bidirectional edges (A->B, B->A).

| Test | Result | Status |
|------|--------|--------|
| `traverse_graph(A, ['cycle_test'], 'outbound', NULL, 3)` | Returns B at depth 1 only (1 row). Does NOT loop back to A. | **PASS** |
| `traverse_graph(A, ['cycle_test'], 'both', NULL, 3)` | Returns B at depth 1 twice (2 rows). Does NOT loop back to A. | **PASS** (see observation below) |

**Cycle prevention mechanism**: The recursive CTE maintains a `visited` array. Each recursive step checks `NOT (next_id = ANY(t.visited))` before following an edge. This correctly prevents infinite recursion.

**Minor observation (non-blocking)**: With `direction='both'`, node B appears twice at depth 1 because two distinct edges reach it (the outbound A->B edge and the inbound B->A edge reversed). This is technically correct behavior (they are different traversal paths via different edges), but callers consuming results may want to deduplicate by `pointer_id`. This is a presentation concern, not a correctness bug. No fix required.

Test data was cleaned up after testing.

---

## 6. Depth Cap

| Test | Result | Status |
|------|--------|--------|
| `traverse_graph(AI_Infrastructure, NULL, 'both', NULL, 4)` | Returns results at depth 1, 2, and 3. No depth 4 results. | **PASS** |

The function source confirms: `IF p_depth > 3 THEN p_depth := 3; END IF;`

---

## 7. Performance

### Overall function timing

```
EXPLAIN ANALYZE SELECT * FROM search_knowledge('nvidia');
  Execution Time: 9.310 ms
```

### Per-signal breakdown

| Signal | Index available | Used by planner | Exec time | Notes |
|--------|----------------|-----------------|-----------|-------|
| Trigram | `idx_pointers_label_trgm` (GiST) | Seq Scan | 1.66ms | Optimizer chose seq scan for 60 rows -- correct |
| Full-text | `idx_pointers_search_text` (GIN) | Seq Scan | 0.16ms | Same -- optimizer chose seq scan for 60 rows |
| Attribute | `idx_attributes_value` (GIN) | Seq Scan | 2.02ms | Same -- 75 rows |
| Embedding | `idx_pointers_embedding` (HNSW) | N/A | N/A | Not tested (no embedding provided) |

**Note**: Postgres correctly uses sequential scan for small tables (<100 rows). The indexes exist and will automatically be used by the query planner when tables grow past a few hundred rows. This is standard Postgres optimizer behavior and not a concern.

### Index inventory (confirmed present)

| Index | Type | Table | Column(s) |
|-------|------|-------|-----------|
| `idx_pointers_label_trgm` | GiST (trigram) | pointers | label |
| `idx_pointers_search_text` | GIN (tsvector) | pointers | search_text |
| `idx_pointers_embedding` | HNSW (cosine) | pointers | embedding |
| `idx_attributes_value` | GIN (JSONB) | attributes_kv | value |
| `idx_edges_source` | btree | edges | source_id |
| `idx_edges_target` | btree | edges | target_id |

All required indexes for the 4 search signals and graph traversal are present.

---

## 8. Function Signatures (Confirmed)

### search_knowledge
```
(p_query text, p_embedding vector DEFAULT NULL, p_type_filter pointer_type DEFAULT NULL, p_limit integer DEFAULT 20)
RETURNS TABLE(pointer_id uuid, label text, type pointer_type, trigram_score real, embedding_score real, attribute_score real, fulltext_score real, combined_score real)
```

### traverse_graph
```
(p_start_ids uuid[], p_edge_types text[] DEFAULT NULL, p_direction text DEFAULT 'both', p_target_type pointer_type DEFAULT NULL, p_depth integer DEFAULT 1, p_limit integer DEFAULT 50)
RETURNS TABLE(pointer_id uuid, label text, type pointer_type, depth integer, via_edge_id uuid, via_edge_type text, via_edge_why text, from_pointer_id uuid)
```

---

## 9. Data Inventory

| Table | Row count |
|-------|-----------|
| pointers | 58 (60 during test, 58 after cleanup) |
| edges | 93 (95 during test, 93 after cleanup) |
| attributes_kv | 75 |

---

## 10. Issues Found

### Blocking: None

### Non-blocking observations

1. **Duplicate rows with `direction='both'` on bidirectional edges**: When two pointers have edges in both directions (A->B and B->A), `traverse_graph` with `direction='both'` returns the target twice at the same depth (once per edge). This is technically correct (different edges) but may surprise consumers. Recommend documenting this behavior or adding an optional `DISTINCT ON (ptr_id)` mode in a future iteration. **Severity: informational**.
