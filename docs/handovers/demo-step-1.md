# Demo Step 1 Handover: Data Layer

## What was built

### `src/demo/knowledgeGraph.js` — Flat graph extraction
- Extracts all 58 pointers from `TREES` in `src/data/trees.js`
- Each pointer: `{ id, label, type, treeId, leaves }`
- Extracts all edges from branch `links` arrays (directed)
- Builds `ADJACENCY` map (bidirectional) for path validation
- Exports: `POINTERS`, `POINTER_MAP`, `EDGES`, `ADJACENCY`, `GRAPH_STATS`

### `src/demo/queryGenerator.js` — 200 synthetic queries
- 10 investigation themes for the Nzyme tenant (regulatory intelligence firm)
- Each theme has 2-3 spine paths and a query count (18-22)
- Seeded PRNG (mulberry32, seed=42) for deterministic generation
- Path generation: pick spine → random entry/exit offset → optional detour from neighbor → trim to 3-6 nodes
- Queries interleaved across themes via round-robin with jitter
- Exports: `THEMES`, `generateQueries(seed)`, `NZYME_QUERIES` (pre-generated), `getQueryStats(queries)`

### Theme distribution (designed for ~200 total)

| # | Theme | Count | Core Cluster |
|---|-------|-------|-------------|
| 1 | European AI Regulation | 22 | eu-ai-act, europe, gdpr, mifid |
| 2 | Security & Compliance | 22 | security, crowdstrike, wiz, cyber, gdpr |
| 3 | Spanish Tech Hub | 20 | spain, factorial, jobandtalent, seedtag, clarity-ai |
| 4 | AI Infrastructure | 22 | nvidia, ai-infra, huang |
| 5 | Agent Architecture | 20 | orchestrator, research, analyst, agent-framework |
| 6 | Monitoring Pipeline | 18 | alert-pipeline, monitor, alerting, scheduler |
| 7 | Data & Knowledge | 18 | data-quality, knowledge-store, data-layer, db-connector |
| 8 | Fintech & LatAm | 18 | latam, fintech, stripe, collison |
| 9 | Research Workflows | 20 | sector-scan, dd-flow, research, analysis |
| 10 | Consumer & Biotech | 20 | consumer, biotech, apple, moderna, cook |

## How to verify

### 1. Build succeeds
```bash
npx vite build
# Expected: ✓ no errors
```

### 2. Code review verification
- Read `knowledgeGraph.js`: Does it extract from `TREES` correctly? Are all branches captured?
- Read `queryGenerator.js`: Do all spine paths follow actual edges in ADJACENCY?
- Verify theme spines: for each spine `[A, B, C, D]`, confirm A→B, B→C, C→D exist in the graph edges
- Verify PRNG is deterministic: `generateQueries(42)` called twice should produce identical arrays

### 3. Expected stats (verify by code review)
- POINTERS.length should be 58
- EDGES.length should be ~93 (directed edges from links)
- ADJACENCY should have entries for most pointers
- GRAPH_STATS.isolatedPointers should be few or none (all pointers should be reachable via edges)

## Files to review

| File | What to check |
|------|--------------|
| `src/demo/knowledgeGraph.js` | Graph extraction, adjacency correctness |
| `src/demo/queryGenerator.js` | Spine validity, PRNG determinism, theme balance, interleaving |
