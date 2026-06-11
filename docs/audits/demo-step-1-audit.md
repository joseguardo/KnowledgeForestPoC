# Audit: Demo Step 1 — Data Layer

**Date**: 2026-06-10
**Auditor**: Claude Opus 4.6 (automated)
**Files reviewed**:
- `src/data/trees.js` (source of truth)
- `src/demo/knowledgeGraph.js` (graph extraction)
- `src/demo/queryGenerator.js` (synthetic query generation)
- `src/demo/treeNamer.js` (consumer of pointer types)

---

## 1. Graph Extraction Correctness

### Branch count
- **trees.js** contains 13 trees with 58 total branches (manually counted):
  sectors (5), companies (10), people (4), geographies (4), regulation (4),
  components (4), agents (4), skills (4), tools (5), flows (4), trees_meta (2),
  best_practices (4), architecture (4).
- **knowledgeGraph.js** iterates every `tree.branches` — extracts all 58. **PASS**

### Edge count
- trees.js originally had 93 directed edges. After audit fixes (see below), now 95.
- knowledgeGraph.js iterates every `branch.links` — extracts all edges. **PASS**

### Type derivation — FIXED (was a bug)
The original regex approach `tree.id.replace(/s$/, "").replace("_meta", "meta")` produced wrong types:

| Tree ID | Old (buggy) | Correct | Impact |
|---------|-------------|---------|--------|
| `companies` | `companie` | `company` | treeNamer priority miss |
| `people` | `people` | `person` | treeNamer priority miss |
| `geographies` | `geographie` | `geography` | treeNamer priority miss |
| `trees_meta` | `treesmeta` | `meta` | treeNamer priority miss |

**Fix applied**: Replaced regex with explicit `TREE_TYPE` lookup map in `knowledgeGraph.js`.

### Adjacency bidirectionality
The `addEdge(a, b)` function adds both directions. Confirmed correct. **PASS**

### Isolated pointers
All 58 pointers appear in at least one edge (either as source or target). Zero isolated pointers. **PASS**

---

## 2. Query Generator — Spine Path Verification

Every consecutive pair in every spine was checked against the bidirectional adjacency derived from trees.js.

### Blocking bugs found and fixed

#### Bug 1: Theme 4 (ai-infrastructure), Spine 1
- **Original**: `["company:nvidia", "sector:ai-infra", "company:clarity-ai", "company:seedtag"]`
- **Broken hop**: `company:clarity-ai` <-> `company:seedtag` — no edge exists
- **Fix**: Changed to `["company:nvidia", "sector:ai-infra", "company:seedtag", "geo:spain"]`

#### Bug 2: Theme 5 (agent-architecture), Spine 2
- **Original**: `["arch:agent-framework", "agent:analyst", "skill:analysis", "skill:report-gen"]`
- **Broken hop**: `skill:analysis` <-> `skill:report-gen` — no edge exists
- **Fix**: Changed to `["arch:agent-framework", "agent:analyst", "skill:report-gen", "tool:doc-writer"]`

#### Bug 3: Theme 9 (research-workflows), Spine 2
- **Original**: `["flow:dd-flow", "agent:analyst", "skill:analysis", "skill:report-gen", "tool:doc-writer"]`
- **Broken hop**: `skill:analysis` <-> `skill:report-gen` — same missing edge
- **Fix**: Reordered to `["flow:dd-flow", "skill:analysis", "agent:analyst", "skill:report-gen", "tool:doc-writer"]`

#### Bug 4: Theme 10 (consumer-biotech), Spine 2
- **Original**: `["sector:biotech", "company:moderna", "sector:consumer", "company:seedtag"]`
- **Broken hop**: `company:moderna` <-> `sector:consumer` — no edge exists
- **Fix**: Reordered to `["company:moderna", "sector:biotech", "sector:consumer", "company:seedtag"]`
- **Also added** edge `sector:biotech -> sector:consumer` in trees.js (semantically: biotech consumer health products)

#### Bug 5: Theme 10 (consumer-biotech), Spine 3
- **Original**: `["company:apple", "sector:consumer", "company:jobandtalent", "geo:spain"]`
- **Broken hop**: `company:jobandtalent` <-> `geo:spain` — no edge exists
- **Fix**: Added edge `company:jobandtalent -> geo:spain` in trees.js (Jobandtalent HQ is Madrid)

### All other spines verified — PASS
Themes 1, 2, 3, 6, 7, 8, and remaining spines in themes 4, 5, 9, 10 all have valid consecutive hops.

---

## 3. Theme Balance

| # | Theme | Count |
|---|-------|-------|
| 1 | European AI Regulation | 22 |
| 2 | Security & Compliance | 22 |
| 3 | Spanish Tech Hub | 20 |
| 4 | AI Infrastructure | 22 |
| 5 | Agent Architecture | 20 |
| 6 | Monitoring Pipeline | 18 |
| 7 | Data & Knowledge | 18 |
| 8 | Fintech & LatAm | 18 |
| 9 | Research Workflows | 20 |
| 10 | Consumer & Biotech | 20 |

**Total: 200** — PASS

### Theme distinctness
Core clusters have minimal overlap:
- Themes 1/2 share `reg:gdpr` but diverge (regulation focus vs security tooling)
- Themes 3/8 share `sector:fintech` but diverge (Spain geography vs LatAm geography)
- Themes 5/9 share agent nodes but diverge (architecture vs workflows)
- No two themes share the same dominant cluster. **PASS**

---

## 4. PRNG

- Implementation: standard mulberry32 algorithm. **PASS**
- Seed: hardcoded `42` in `NZYME_QUERIES = generateQueries(42)`. **PASS**
- Determinism: same seed always produces same sequence (no external state). **PASS**

---

## 5. Build

```
npx vite build
✓ 92 modules transformed.
✓ built in 855ms (no errors)
```

**PASS**

---

## Summary of Changes Made

### `src/demo/knowledgeGraph.js`
- Replaced regex type derivation with explicit `TREE_TYPE` lookup map (4 type bugs fixed)
- Updated edge count in file comment from 93 to 95

### `src/data/trees.js`
- Added link `company:jobandtalent -> geo:spain` (HQ Madrid — was inexplicably missing)
- Added link `sector:biotech -> sector:consumer` (biotech consumer health products)

### `src/demo/queryGenerator.js`
- Fixed Theme 4 Spine 1: rerouted through seedtag->spain instead of invalid clarity-ai->seedtag hop
- Fixed Theme 5 Spine 2: rerouted through analyst->report-gen->doc-writer instead of invalid analysis->report-gen hop
- Fixed Theme 9 Spine 2: reordered to dd-flow->analysis->analyst->report-gen->doc-writer
- Fixed Theme 10 Spine 2: reordered to moderna->biotech->consumer->seedtag
- Theme 10 Spine 3: now valid with new jobandtalent->spain edge

### Verdict: **5 blocking bugs found and fixed. Build green.**
