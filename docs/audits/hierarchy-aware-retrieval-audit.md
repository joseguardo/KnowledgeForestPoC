# Hierarchy-Aware Retrieval Audit

**Date:** 2026-06-10
**Auditor:** Claude Opus 4.6 (1M context)
**Handover:** `docs/handovers/hierarchy-aware-retrieval.md`
**Supabase project:** `rkuyvzcxaoulhjiflrmp`

---

## Database Verification

### 1. 3-Layer Retrieval (`search_hierarchy_aware('cybersecurity', kibo_tenant)`)

**Status: PASS**

Query returned 14 results across all 3 source types:

| # | Label | Type | Source | Co-access Weight | Via |
|---|-------|------|--------|-----------------|-----|
| 1 | Cybersecurity | sector | search | 0 | - |
| 2 | SEC Regulations | regulation | search | 0 | - |
| 3 | AI Infrastructure | sector | search | 0 | - |
| 4 | Security Practices | best_practice | search | 0 | - |
| 5 | Clarity AI | company | search | 0 | - |
| 6 | CrowdStrike | company | coaccess | 8 | co-accessed with Cybersecurity |
| 7 | GDPR | regulation | coaccess | 6 | co-accessed with Cybersecurity |
| 8 | Wiz | company | coaccess | 4 | co-accessed with Cybersecurity |
| 9 | API Gateway | component | graph | 0 | via guides from Security Practices |
| 10 | NVIDIA | company | graph | 0 | via primary_sector from AI Infrastructure |
| 11 | United States | geography | graph | 0 | via related from SEC Regulations |
| 12 | EU AI Act | regulation | graph | 0 | via related from AI Infrastructure |
| 13 | Fintech | sector | graph | 0 | via related from SEC Regulations |
| 14 | Seedtag | company | graph | 0 | via related from AI Infrastructure |

All 3 source types present: search (5), coaccess (3), graph (6). Ordering correct: search first, then coaccess, then graph.

### 2. Empty Tenant (No Co-access Data)

**Status: PASS**

Created `TestEmpty` tenant (`00000000-0000-0000-0000-000000000099`), ran `search_hierarchy_aware('cybersecurity', ...)`.
- Result: 10 rows, only `search` and `graph` sources.
- No `coaccess` rows appeared, as expected.
- Tenant cleaned up after test.

### 3. `search_by_coaccess` Direct Test

**Status: PASS**

Called `search_by_coaccess(kibo_tenant, [cybersecurity entry point IDs], 10)`.

| Pointer | Type | Weight | Sessions | Via |
|---------|------|--------|----------|-----|
| CrowdStrike | company | 8 | 8 | Cybersecurity |
| GDPR | regulation | 6 | 6 | Cybersecurity |
| Wiz | company | 4 | 4 | Cybersecurity |

All fields populated correctly. Matches handover test data.

### 4. Performance (`EXPLAIN ANALYZE`)

**Status: PASS (borderline)**

```
Function Scan on search_hierarchy_aware
  actual time=19.744..19.746 rows=14
Planning Time: 0.047 ms
Execution Time: 19.880 ms
```

Execution time: **19.88ms** -- under the 20ms target but just barely. As noted in the handover, this may need optimization at scale due to 3 sequential subqueries.

---

## Regression Tests

### 5. `search_hierarchy_aware('nvidia')` finds NVIDIA

**Status: PASS**

| Label | Type | Source |
|-------|------|--------|
| Jensen Huang | person | search |
| NVIDIA | company | search |
| George Kurtz | person | search |
| United States | geography | graph |
| CrowdStrike | company | graph |
| AI Infrastructure | sector | graph |
| Tim Cook | person | graph |

NVIDIA found as search result. Graph expansion yields related entities.

### 6. `search_hierarchy_aware('Kurtz')` finds George Kurtz + CrowdStrike

**Status: PASS**

| Label | Type | Source |
|-------|------|--------|
| George Kurtz | person | search |
| CrowdStrike | company | search |
| Cybersecurity | sector | coaccess |
| Jensen Huang | person | graph |
| United States | geography | graph |
| GDPR | regulation | graph |
| Wiz | company | graph |

George Kurtz found via search. CrowdStrike also in search results. Cybersecurity appears via coaccess (behavioral signal from Kibo tenant patterns).

### 7. Empty Query Returns 0 Results

**Status: PASS**

`search_hierarchy_aware('', kibo_tenant)` returned `[]` (empty array).

---

## Edge Function

### 8. `query-knowledge` Version & Status

**Status: PASS**

- Slug: `query-knowledge`
- Version: **3**
- Status: **ACTIVE**
- ID: `7666417d-41a0-4c0b-838f-1281096aa8e2`

---

## Frontend

### 9. `npx vite build` Succeeds

**Status: PASS**

```
vite v6.4.2 building for production...
106 modules transformed.
built in 1.02s
```

No errors. Output:
- `dist/index.html` (0.49 kB)
- `dist/assets/DemoApp-7bCtsZQS.js` (24.58 kB)
- `dist/assets/index-45hjORaD.js` (980.11 kB)

Note: Large chunk warning (980 kB) -- not a blocker but code-splitting recommended for production.

### 10. `useKnowledgeSearch` Calls `search_hierarchy_aware`

**Status: PASS**

`src/hooks/useKnowledgeSearch.js` line 44:
```js
const { data, error: rpcError } = await supabase.rpc("search_hierarchy_aware", {
  p_query: query.trim(),
  p_tenant_id: tenantId || null,
  p_embedding: null,
  p_type_filter: null,
  p_limit: 15,
});
```

Correctly calls `search_hierarchy_aware` (not `search_knowledge`). Passes `VITE_KIBO_TENANT_ID` as tenant.

### 11. SearchPanel Shows Source Badges

**Status: PASS**

`src/components/SearchPanel.jsx` lines 139-143:
```js
const sourceColors = {
  search: { bg: "#e8f4e8", color: "#3a7a3a", label: "Search" },
  coaccess: { bg: "#fff3e0", color: "#c07000", label: "Behavioral" },
  graph: { bg: "#e0f0ff", color: "#2070c0", label: "Graph" },
};
```

Badge rendered as a `<span>` with rounded corners (line 167-169).

### 12. Source Colors Match Specification

**Status: PASS**

| Source | Badge Label | Color | Background | Spec Match |
|--------|------------|-------|------------|------------|
| search | Search | green (#3a7a3a) | #e8f4e8 | Yes |
| coaccess | Behavioral | orange (#c07000) | #fff3e0 | Yes |
| graph | Graph | blue (#2070c0) | #e0f0ff | Yes |

Co-access results have warm background highlight (`#fffaf0` bg, `#f0e0c0` border) as specified.
`via_pointer` shown on line 174-177 for context traceability.

---

## Summary

| # | Check | Status |
|---|-------|--------|
| 1 | 3-layer retrieval (cybersecurity, Kibo) | PASS |
| 2 | Empty tenant (no co-access) | PASS |
| 3 | search_by_coaccess direct | PASS |
| 4 | Performance < 20ms | PASS (19.88ms, borderline) |
| 5 | Regression: nvidia | PASS |
| 6 | Regression: Kurtz | PASS |
| 7 | Regression: empty query | PASS |
| 8 | Edge function v3 active | PASS |
| 9 | Vite build | PASS |
| 10 | Hook calls search_hierarchy_aware | PASS |
| 11 | Source badges displayed | PASS |
| 12 | Source colors correct | PASS |

**Result: 12/12 PASS. No issues found. No fixes needed.**

### Observations (non-blocking)

1. **Performance is borderline** at 19.88ms. The 3 sequential subqueries inside `search_hierarchy_aware` leave very little headroom. At larger data volumes this will likely exceed 20ms. Consider parallelizing the coaccess + graph lookups inside the SQL function.
2. **Large JS bundle** (980 kB). The vite build warns about chunk size. Not related to this feature but worth addressing with code-splitting.
