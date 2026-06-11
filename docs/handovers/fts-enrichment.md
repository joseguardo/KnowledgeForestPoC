# FTS Enrichment + Search Traceability Handover

## What was built

### Migration 008: Enriched FTS via triggers
- Dropped the `GENERATED ALWAYS` `search_text` column (could only reference own row)
- Added regular `search_text tsvector` column with GIN index
- Created `rebuild_pointer_search_text(pointer_id)` function that collects text from 3 tables:
  - `pointers.label`
  - All `attributes_kv.value` for that pointer
  - All `edges.why` connected to that pointer (both directions)
- Created 3 triggers:
  - `trg_pointer_search_text` → fires on pointers INSERT/UPDATE of label/metadata
  - `trg_attr_search_text` → fires on attributes_kv INSERT/UPDATE/DELETE
  - `trg_edge_search_text` → fires on edges INSERT/UPDATE/DELETE (rebuilds both endpoints)
- Backfilled all 58 pointers

### Enhanced `search_knowledge` with `match_details`
- Dropped and recreated function with new return column: `match_details JSONB`
- `match_details` contains:
  - `matched_signals`: array of which signals fired (e.g., `["trigram", "attribute", "fulltext"]`)
  - `trigram_match`: the label that matched (if trigram fired)
  - `attribute_match`: `{"key": "CEO", "value": "Kurtz"}` (best matching attribute)
  - `fulltext_match`: `ts_headline` output showing matched terms
  - `embedding_match`: boolean flag
- FTS headline uses `ts_headline('english', label || metadata, query, 'MaxWords=12')` — note: contains some JSON noise from metadata serialization

### Frontend: `MatchDetails.jsx` component
- Color-coded signal badges: Label (green), Semantic (purple), Attribute (orange), Full-text (blue)
- Shows matched text inline (truncated at 25 chars, full on hover via title)
- Cleans FTS headlines (strips JSON noise from metadata)
- Used in both SearchPanel and ChatPanel

## How to verify

### FTS enrichment (previously failing, now working)
```sql
SELECT label, fulltext_score FROM search_knowledge('data protection') WHERE fulltext_score > 0;
-- Expected: GDPR (0.19), Cybersecurity (0.10)

SELECT label, fulltext_score FROM search_knowledge('endpoint security') WHERE fulltext_score > 0;
-- Expected: CrowdStrike (0.24), GDPR (0.23), Cybersecurity (0.15)

SELECT label, fulltext_score FROM search_knowledge('financial markets') WHERE fulltext_score > 0;
-- Expected: MiFID II (0.10)
```

### Traceability
```sql
SELECT label, match_details FROM search_knowledge('Kurtz');
-- Expected: George Kurtz: matched_signals=["trigram","fulltext"]
--           CrowdStrike: matched_signals=["attribute","fulltext"], attribute_match={"key":"CEO","value":"Kurtz"}

SELECT label, match_details FROM search_knowledge('data protection');
-- Expected: GDPR: matched_signals=["attribute","fulltext"], attribute_match={"key":"Scope","value":"EU data protection"}
```

### Trigger test
```sql
-- Insert a test attribute and verify tsvector updates
INSERT INTO attributes_kv (pointer_id, key, value, data_type)
VALUES ((SELECT id FROM pointers WHERE label = 'NVIDIA'), 'TestAttr', '"test trigger value"', 'string');

-- Check tsvector now contains "test trigger value"
SELECT search_text FROM pointers WHERE label = 'NVIDIA';
-- Should contain 'test', 'trigger', 'valu' stems

-- Cleanup
DELETE FROM attributes_kv WHERE key = 'TestAttr' AND pointer_id = (SELECT id FROM pointers WHERE label = 'NVIDIA');
```

### Build
```bash
npx vite build
# Expected: ✓ 106 modules, no errors
```

## Known issues
1. `fulltext_match` headline includes JSON noise from `metadata::text` serialization (e.g., `{"tree_origin"...`). The `MatchDetails` component strips this client-side but the raw JSONB value is messy.
2. `search_knowledge` was dropped and recreated — any cached references to the old function signature need refreshing.

## Files to review
| File | What to check |
|------|--------------|
| Supabase migration 008 | Triggers fire correctly on all 3 tables, backfill covers all 58 pointers |
| `search_knowledge` RPC | match_details populated correctly, no regression on existing tests |
| `src/components/MatchDetails.jsx` | Signal badges render, headline cleaning works |
| `src/components/SearchPanel.jsx` | MatchDetails integrated in results |
| `src/components/ChatPanel.jsx` | MatchDetails integrated in message bubbles |
