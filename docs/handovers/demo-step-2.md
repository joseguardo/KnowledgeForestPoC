# Demo Step 2 Handover: Simulation Engine

## What was built

### `src/demo/coAccessEngine.js` — Client-side co-access + clustering
- **`createCoAccessState()`** — Creates empty state with a weights Map
- **`addPathToMatrix(state, pointerIds)`** — Adds a navigation path. For each pair (i,j), adds weight = 1/|i-j| with canonical ordering (a < b)
- **`getEdges(state, threshold)`** — Returns all co-access edges as `{ a, b, weight, aboveThreshold }`
- **`clusterBranches(state, threshold, minBranchSize)`** — Union-find clustering on edges above threshold. Returns array of pointer ID arrays (branches). Filters out branches smaller than minBranchSize.
- **`mergeBranchesIntoTrees(branches, state, maxTrees)`** — Greedy agglomerative merge. Computes inter-branch affinity from co-access weights. Iteratively merges most-affiliated pair until count <= maxTrees.
- **`computeForest(state, options)`** — Full pipeline: cluster → merge. Returns `{ branches, trees }`.

### `src/demo/treeNamer.js` — Deterministic naming
- **`nameBranch(pointerIds)`** — Names a branch from its members. Uses priority ordering: company > person > regulation > sector > geography > system types.
- **`nameTree(branches)`** — Names a tree from its branches. Detects entity/system mix. Uses sector/geography as umbrella for entity trees, architecture/component for system trees.

### `src/demo/checkpointGenerator.js` — Full simulation with snapshots
- **`generateCheckpoints(queries, options)`** — Main function:
  1. Feeds queries into co-access engine one by one
  2. At each checkpoint index [0, 15, 35, 70, 120, 170, 200], snapshots:
     - Formatted tree array (buildScene-compatible shape)
     - Unassigned pointer list
     - Co-access edge list with threshold flags
     - Diff from previous checkpoint (new/removed branches, moved pointers)
     - Stats (tree count, branch count, assigned pointers, edge counts)
  3. Returns array of 7 checkpoint objects

- Tree positions computed via circular layout: `radius = 18 + count * 1.5`, distributed evenly by angle
- Tree type (entity/system) derived from majority pointer type
- Threshold default: 1.5

## How to verify

### 1. Build succeeds
```bash
npx vite build
# Expected: ✓ no errors
```

### 2. Code review: coAccessEngine.js
- Proximity weighting: `1/distance` — verify adjacent pointers get 1.0, 2-apart get 0.5
- Canonical ordering: pair key always has `a < b` — verify `pairKey` function
- Union-find: path compression in `find()`, union by rank — verify standard implementation
- Agglomerative merge: verify it stops when `bestWeight === 0` (disconnected trees) or count <= maxTrees

### 3. Code review: checkpointGenerator.js
- Checkpoint indices: [0, 15, 35, 70, 120, 170, 200] — total 7 checkpoints
- First checkpoint (0) should produce empty trees array
- `formatForScene` output shape must match what buildScene.js expects: `{ id, label, subtitle, type, pos: [x,y,z], branches: [{ id, name, leaves, links, pointerIds }] }`
- Diff computation: verify new/removed branches detected correctly, pointer moves tracked

### 4. Code review: treeNamer.js
- Priority list matches all pointer types in the graph
- Edge cases: empty branch → "Empty", single pointer → pointer label, mixed types → uses priority

## Files to review

| File | What to check |
|------|--------------|
| `src/demo/coAccessEngine.js` | Proximity weighting, union-find correctness, merge termination |
| `src/demo/treeNamer.js` | Priority ordering, entity/system detection, edge cases |
| `src/demo/checkpointGenerator.js` | Query feeding loop, snapshot shape, diff computation, tree positioning |
