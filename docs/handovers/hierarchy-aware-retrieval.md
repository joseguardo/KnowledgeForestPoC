# Hierarchy-Aware Retrieval Handover

## What was built

The retrieval layer now respects the tenant's navigation patterns. Three retrieval layers execute in priority order:

```
1. SEARCH (hybrid text match) → entry points
2. COACCESS (tenant behavioral signal) → "what does this tenant think of together?"
3. GRAPH (structural edges) → cold-start fallback
```

### Migration 009: Two new RPC functions

**`search_by_coaccess(tenant_id, pointer_ids, limit)`**
- Queries `tenant_coaccess` for pointers co-accessed with the input pointers
- Aggregates weights when a pointer is co-accessed with multiple inputs
- Returns: pointer_id, label, type, coaccess_weight, coaccess_sessions, via_pointer_id, via_pointer_label

**`search_hierarchy_aware(query, tenant_id, embedding?, type_filter?, limit)`**
- Orchestrates the 3-layer pipeline:
  1. Calls `search_knowledge` for entry points
  2. Collects entry point IDs, passes to `search_by_coaccess` for behavioral expansion
  3. Passes entry point IDs to `traverse_graph` for structural fallback
  4. Deduplicates (keeps highest relevance per pointer)
  5. Orders: search results first, then coaccess, then graph
- Returns: pointer_id, label, type, source ('search'|'coaccess'|'graph'), relevance_score, match_details, coaccess_weight, via_pointer

### Updated `query-knowledge` Edge Function (v3)
- Now uses `search_hierarchy_aware` as the default first step instead of flat `search_knowledge`
- LLM schema context updated to describe the 3-layer system
- Plans now prefer `hierarchy_search` action, falling back to `traverse` and `enrich`
- Answer composition mentions which layer found each result
- Accepts `tenant_id` in request body (defaults to Kibo)

### Frontend updates
- `useKnowledgeSearch.js`: `quickSearch` now calls `search_hierarchy_aware` instead of `search_knowledge`
- `SearchPanel.jsx`: Results show source badge (Search=green, Behavioral=orange, Graph=blue), co-access results have warm background highlight, via_pointer shown for context

### Test data
Simulated co-access data for Kibo tenant (kept for demo):
- Cybersecurity ↔ CrowdStrike: weight 8, sessions 8
- Cybersecurity ↔ GDPR: weight 6, sessions 6
- Cybersecurity ↔ Wiz: weight 4, sessions 4

## How to verify

### 3-layer retrieval works
```sql
SELECT label, type, source, coaccess_weight, via_pointer
FROM search_hierarchy_aware(
  'cybersecurity', 'ca61f0e5-563e-5894-954f-38f5a9e0eabc', NULL, NULL, 15
);
-- Expected: 
--   source='search': Cybersecurity, SEC Regulations, AI Infrastructure, Security Practices
--   source='coaccess': CrowdStrike (w:8), GDPR (w:6), Wiz (w:4)
--   source='graph': API Gateway, NVIDIA, EU AI Act, etc.
```

### Co-access returns empty when no data
```sql
-- Create a new tenant with no co-access history
INSERT INTO tenants (id, name) VALUES ('00000000-0000-0000-0000-000000000099', 'TestEmpty');
SELECT label, source FROM search_hierarchy_aware(
  'cybersecurity', '00000000-0000-0000-0000-000000000099', NULL, NULL, 10
);
-- Expected: only 'search' and 'graph' sources, no 'coaccess'
DELETE FROM tenants WHERE id = '00000000-0000-0000-0000-000000000099';
```

### Build
```bash
npx vite build  # Expected: ✓ 106 modules, no errors
```

### Edge Function
```
list_edge_functions(project_id='rkuyvzcxaoulhjiflrmp')
# Expected: query-knowledge version 3, ACTIVE
```

## Known issues
1. `search_hierarchy_aware` calls `search_by_coaccess` and `search_knowledge` which may result in 3 sequential subqueries. Performance acceptable for current data size (<20ms) but may need optimization at scale.
2. The co-access relevance score is `weight/100` — a rough normalization that works for demo but should be calibrated against actual weight distributions.

## Files to review
| File | What to check |
|------|--------------|
| Supabase migration 009 | search_by_coaccess + search_hierarchy_aware |
| Edge Function `query-knowledge` v3 | Uses hierarchy_search, passes tenant_id |
| `src/hooks/useKnowledgeSearch.js` | quickSearch calls search_hierarchy_aware |
| `src/components/SearchPanel.jsx` | Source badges, co-access highlighting |
