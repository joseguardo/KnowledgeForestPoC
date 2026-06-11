# Demo Step 2 Audit: Simulation Engine

**Date**: 2026-06-10
**Files reviewed**:
- `src/demo/coAccessEngine.js`
- `src/demo/treeNamer.js`
- `src/demo/checkpointGenerator.js`
- `src/demo/knowledgeGraph.js` (dependency)
- `src/demo/queryGenerator.js` (dependency)
- `src/scene/buildScene.js` (consumer of output shape)
- `src/data/trees.js` (source data)

---

## Correctness

### coAccessEngine.js -- PASS

| Check | Verdict | Detail |
|-------|---------|--------|
| Proximity weighting `1/distance` | Correct | Inner loop iterates `j = i+1..len-1`, distance = `j - i`. Adjacent pointers get weight 1.0, 2-apart get 0.5. Accumulates additively across paths. |
| Canonical pair key (`a < b`) | Correct | `pairKey()` at line 18-20 uses string comparison `a < b` with null-byte separator. Deterministic and collision-free for valid pointer IDs. |
| Union-find: path compression | Correct | `find()` at line 58-67 recursively compresses path with `this.parent.set(x, this.find(...))`. Lazy initialization on first `find()` call. |
| Union-find: union by rank | Correct | `union()` at line 69-81 compares ranks, attaches smaller tree under larger. Tie-breaking increments rank. Standard textbook implementation. |
| Agglomerative merge termination | Correct | Loop at line 142-168 exits when `treeBranches.length <= maxTrees` OR when `bestWeight === 0` (no remaining inter-branch affinity, i.e., disconnected components). No infinite loop risk. |

**No issues found.**

### treeNamer.js -- PASS

| Check | Verdict | Detail |
|-------|---------|--------|
| Priority list covers all 13 types | Correct | Priority list (lines 40-53): company, person, regulation, sector, geography, flow, agent, component, skill, tool, architecture, best_practice, meta. Matches all 13 types in `TREE_TYPE` from knowledgeGraph.js. |
| Edge case: empty branch | Correct | Returns `"Empty"` (line 25). |
| Edge case: single pointer | Correct | Returns pointer label or ID fallback (line 26-28). |
| Edge case: all same type | Correct | Returns first label (line 35-37). |
| Edge case: mixed types | Correct | Falls through priority list to find the most recognizable entity (lines 56-59). Final fallback returns first label (line 61). |
| `nameTree` entity/system detection | Correct | Uses `entityTypes` Set (company, person, sector, geography, regulation) for classification. Mixed trees get `"Ecosystem"` suffix. Entity-only uses sector/geography umbrella. System-only uses architecture/component/flow umbrella. |
| `nameTree` empty | Correct | Returns `"Empty Tree"` (line 69). |
| `nameTree` single branch | Correct | Returns branch name (line 70). |

**No issues found.**

### checkpointGenerator.js -- 1 BUG FIXED

| Check | Verdict | Detail |
|-------|---------|--------|
| Query feeding loop advances | **Correct** | `addPathToMatrix()` increments `state.pathCount++` (coAccessEngine.js line 36). The while-loop condition `state.pathCount < cpIndex` advances each iteration. No infinite loop. |
| Checkpoint 0 produces empty trees | Correct | When `cpIndex === 0`, the while condition `state.pathCount < 0` is immediately false. Line 183 checks `cpIndex === 0` and returns `[]`. |
| `formatForScene` output shape | Correct | Produces `{ id, label, subtitle, type, pos: [x,y,z], branches: [{ id, name, pointerIds, leaves, links }] }`. `buildScene.js` at line 24 expects `trees` with `id`, `label`, `subtitle`, `type`, `pos` (array for `vec3()`), `branches` (array with `id`, `name`, `leaves`, `links`). Extra `pointerIds` field is harmlessly ignored by buildScene. |
| Diff: new/removed branches | Correct | Uses Set difference on branch IDs (lines 111-114). Branch IDs are deterministic from sorted pointer IDs. |
| Diff: moved pointers | Correct | Maps each pointer to its previous branch, detects when the same pointer now belongs to a different branch (lines 117-139). |
| Diff: tree-level tracking | Design note | Tree IDs are positional (`tree:0`, `tree:1`, ...) so diff only captures count-level changes, not tree identity across checkpoints. Branch-level diff handles content changes. Acceptable for animation purposes. |
| `.sort()` mutates source array | **FIXED** | Line 68: `branchPointerIds.sort()` sorted the array in-place, mutating the original clustering output. Changed to `[...branchPointerIds].sort()` to create a copy. While the mutation did not cause incorrect behavior in the current code path (naming happens before the sort, and arrays are not reused after `formatForScene`), it was a latent bug that could break if code is reordered or arrays are referenced later. |

---

## Quality

### Infinite loop risks -- NONE

| Location | Risk | Assessment |
|----------|------|------------|
| `while (state.pathCount < cpIndex)` loop (line 171) | Potential infinite loop if `addPathToMatrix` didn't increment `pathCount` | Safe: `addPathToMatrix` always increments `state.pathCount++` unconditionally. Secondary guard `state.pathCount < queries.length` prevents out-of-bounds access. |
| Agglomerative merge `while (treeBranches.length > maxTrees)` (line 142) | Could loop forever if no merge happens | Safe: exits on `bestWeight === 0` (line 162). At least one element is always removed via `splice(bestPair[1], 1)` when bestWeight > 0, so length strictly decreases each iteration. |

### Off-by-one errors -- NONE

| Location | Assessment |
|----------|------------|
| Checkpoint indices `[0, 15, 35, 70, 120, 170, 200]` | 7 values as documented. The while-loop uses strict `<` comparison, so exactly `cpIndex` queries are fed before each snapshot. Guard `state.pathCount < queries.length` prevents feeding beyond available queries. |
| First checkpoint at index 0 | Correctly produces empty state (no queries fed, empty tree array). |
| Last checkpoint at index 200 | With 200 generated queries (indices 0-199), `state.pathCount < 200` feeds all 200. If fewer queries exist, the guard handles it. |

### Tree positions -- CORRECT

| Check | Assessment |
|-------|------------|
| NaN risk | `computeTreePositions` only divides by `count`, which is protected by the `if (count === 0) return []` guard. For count >= 1, all arithmetic is well-defined. |
| Overlap risk | Positions are on a circle with radius `18 + count * 1.5`. At max trees (12), radius = 36, minimum inter-tree distance is ~18.6 units. No overlaps. For count = 1, single tree placed at `[radius, 0, 0]`. |
| Format | Returns `[x, 0, z]` arrays, compatible with `buildScene.js`'s `vec3()` which expects `[x, y, z]`. |

---

## Fix Applied

**File**: `src/demo/checkpointGenerator.js`, line 68

```diff
- id: `branch:${branchPointerIds.sort().join("+")}`,
+ id: `branch:${[...branchPointerIds].sort().join("+")}`,
```

Prevents in-place mutation of the `branchPointerIds` array from the clustering output.

---

## Summary

| Area | Verdict |
|------|---------|
| coAccessEngine.js | Clean -- standard algorithms, correctly implemented |
| treeNamer.js | Clean -- all 13 types covered, edge cases handled |
| checkpointGenerator.js | 1 minor bug fixed (array mutation), otherwise correct |
| Infinite loop risk | None |
| Off-by-one errors | None |
| Tree positions | Correct, no NaN or overlap |
| Output shape compatibility | Matches buildScene.js expectations |
