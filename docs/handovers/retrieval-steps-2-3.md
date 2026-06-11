# Retrieval Steps 2-3 Handover: LLM Query Planner + Frontend

## What was built

### Step 2: `query-knowledge` Edge Function (LLM Query Planner)

Translates natural language questions into multi-step retrieval plans executed against the knowledge graph.

**Flow**:
1. Generate query embedding (OpenAI text-embedding-3-small)
2. LLM (gpt-4o-mini) generates a JSON execution plan from the query + schema context
3. Plan executor runs steps sequentially: `search` → `traverse` → `enrich`
4. In `answer` mode: second LLM call composes a natural language answer from results
5. In `explore` mode: generates follow-up query suggestions

**Schema context** provided to the LLM includes: all 15 pointer types, all 26 edge types with direction annotations, all attribute keys. The LLM outputs a JSON plan with `$stepN` references for chaining steps.

**Fallback**: If no OpenAI key configured, falls back to a simple search-only plan (no LLM, just calls `search_knowledge` directly).

**Modes**:
- `search`: returns raw results with scores/paths
- `answer`: returns results + composed natural language answer
- `explore`: returns results + suggested follow-up queries

### Step 3: Frontend Integration

**`src/hooks/useKnowledgeSearch.js`** — Search hook with two modes:
- `quickSearch(query)`: calls `search_knowledge` RPC directly. No LLM, no embedding. Instant. Used for as-you-type.
- `deepSearch(query, mode)`: calls `query-knowledge` Edge Function. Full LLM pipeline. Used on Enter.
- Aborts previous deep search when new one starts.
- Returns: `results, answer, plan, suggestions, isSearching, mode, error`

**`src/components/SearchPanel.jsx`** — Enhanced search panel:
- Quick mode: debounced 300ms, calls `quickSearch` on every keystroke
- Deep mode: triggered on Enter key, calls `deepSearch("answer")`
- Shows mode indicator ("Quick search" vs "Deep search")
- Answer box (blue background) when LLM provides a composed answer
- Results show: label, type, relevance score, traversal path (via edge type + why)
- Enriched results show attribute previews
- Suggested queries (explore mode) are clickable to chain searches
- Error display with red banner

## How to verify

### 1. Build succeeds
```bash
npx vite build
# Expected: ✓ 104 modules, no errors
```

### 2. Edge Function deployed
```
list_edge_functions(project_id='rkuyvzcxaoulhjiflrmp')
# Expected: query-knowledge ACTIVE among 5 total functions
```

### 3. Quick search works (no LLM needed)
Run `npx vite --open`, click "Search", type "nvidia".
Expected: results appear within 300ms showing NVIDIA + Jensen Huang (via attribute match).

### 4. Deep search works (needs OpenAI key in Supabase vault)
In the search box, type "Who leads the biggest AI companies?" and press Enter.
Expected: "Thinking..." indicator, then results showing Jensen Huang with NVIDIA context, plus a composed answer.

### 5. Quick search shows scores
Type "security" — results should show Cybersecurity (trigram match) and possibly Security Practices, with relevance percentage.

## Known issues

1. **Deep search requires OpenAI key** in Supabase vault. Without it, falls back to search-only (no LLM planning, no answer composition).
2. **No embedding in quick search** — Quick mode uses trigram + full-text only, not semantic. Saves an API call per keystroke.
3. **Plan execution is sequential** — Each step waits for the previous. Could be parallelized for independent steps.
4. **Suggestions are template-based** — Not LLM-generated. Based on top result labels.
5. **search_knowledge RRF scoring** — The `combined_score` values are small (0.01-0.03 range) due to RRF formula. They're relative rankings, not absolute scores. The % display in the UI may be confusing.

## Files to review

| File | What to check |
|------|--------------|
| Edge Function `query-knowledge` | Schema context completeness, plan parsing, step execution, answer composition |
| `src/hooks/useKnowledgeSearch.js` | Quick vs deep mode, abort handling, error states |
| `src/components/SearchPanel.jsx` | Debounce, Enter key handling, result rendering, answer display |
