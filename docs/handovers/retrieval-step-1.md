# Retrieval Step 1 Handover: Database Functions

## What was built

### Migration 007: `search_knowledge` + `traverse_graph` + FTS index

**Full-text search index**: Added a generated `search_text tsvector` column on `pointers` (label + metadata) with a GIN index. Enables `@@` full-text matching.

**`search_knowledge(p_query, p_embedding?, p_type_filter?, p_limit?)`** — Hybrid search with 4 signals + Reciprocal Rank Fusion:

| Signal | Source | Index | Threshold |
|--------|--------|-------|-----------|
| Trigram | `similarity(label, query)` | GiST trigram | > 0.1 |
| Embedding | `1 - cosine_distance(embedding, query_embedding)` | HNSW | if embedding provided |
| Attribute | `similarity(attr_value, query)` across `attributes_kv` | GIN JSONB | > 0.1 |
| Full-text | `ts_rank(search_text, plainto_tsquery(query))` | GIN tsvector | `@@` match |

Combined via RRF: `score = sum(1/(k + rank_i))` for each signal where score > 0. k=60.

**`traverse_graph(p_start_ids, p_edge_types?, p_direction?, p_target_type?, p_depth?, p_limit?)`** — Multi-hop graph traversal:
- Recursive CTE with cycle prevention (tracks visited array)
- Supports outbound, inbound, or both directions
- Filters by edge type and target pointer type
- Depth capped at 3 hops max
- Returns: pointer, depth, edge info, from_pointer

## How to verify

### search_knowledge
```sql
-- Find NVIDIA by label (trigram)
SELECT label, type, trigram_score, combined_score FROM search_knowledge('nvidia');
-- Expected: NVIDIA (trigram=1.0), Jensen Huang (attribute match on "CEO NVIDIA")

-- Find via attribute value (CEO name)
SELECT label, type, attribute_score, combined_score FROM search_knowledge('Kurtz');
-- Expected: George Kurtz (trigram on label), CrowdStrike (attribute "CEO: Kurtz" = 1.0)

-- Type filter
SELECT label, type FROM search_knowledge('security', p_type_filter := 'sector');
-- Expected: Cybersecurity

-- Full-text search
SELECT label, fulltext_score FROM search_knowledge('infrastructure') WHERE fulltext_score > 0;
-- Expected: AI Infrastructure
```

### traverse_graph
```sql
-- Companies in cybersecurity (1 hop inbound via primary_sector)
SELECT label, type, depth, via_edge_type FROM traverse_graph(
  ARRAY[(SELECT id FROM pointers WHERE label = 'Cybersecurity')],
  ARRAY['primary_sector'], 'inbound', 'company', 1
);
-- Expected: CrowdStrike, Wiz

-- Who leads NVIDIA (1 hop inbound via ceo)
SELECT label, type FROM traverse_graph(
  ARRAY[(SELECT id FROM pointers WHERE label = 'NVIDIA')],
  ARRAY['ceo'], 'inbound', 'person', 1
);
-- Expected: Jensen Huang

-- 2-hop from AI Infrastructure (companies + their CEOs/locations)
SELECT label, type, depth, via_edge_type FROM traverse_graph(
  ARRAY[(SELECT id FROM pointers WHERE label = 'AI Infrastructure')],
  NULL, 'inbound', NULL, 2
);
-- Expected: ~11 results across depth 1 (NVIDIA, Clarity AI, Seedtag, Cybersecurity, EU AI Act) and depth 2 (Jensen Huang, Spain, US, CrowdStrike, Wiz, GDPR)
```

## Files to review

| Resource | What to check |
|----------|--------------|
| Supabase migration 007 | RRF scoring correct? Recursive CTE cycle-safe? tsvector generated column correct? |
