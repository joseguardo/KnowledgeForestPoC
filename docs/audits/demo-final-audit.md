# Demo Final Audit

Date: 2026-06-10

## 1. Build

```
npx vite build
```

**PASS** -- 103 modules, 0 errors. DemoApp chunk: 24.58KB (code-split).

## 2. Code Sweep

### Imports

All imports resolve correctly across the 10 demo-related files:

| File | Imports | Status |
|------|---------|--------|
| `knowledgeGraph.js` | `TREES` from `../data/trees` | OK |
| `queryGenerator.js` | `ADJACENCY` from `./knowledgeGraph` | OK |
| `treeNamer.js` | `POINTER_MAP` from `./knowledgeGraph` | OK |
| `checkpointGenerator.js` | `POINTERS, POINTER_MAP, EDGES` from `./knowledgeGraph`; `NZYME_QUERIES` from `./queryGenerator`; `createCoAccessState, addPathToMatrix, getEdges, computeForest` from `./coAccessEngine`; `nameBranch, nameTree` from `./treeNamer` | OK |
| `DemoApp.jsx` | `useRef, useEffect` from `react`; `THREE`; `buildDemoScene`; `useSimulationPlayback`; `generateCheckpoints`; `SimulationController`; `DemoInfoPanel`; `../App.css` | OK |
| `buildDemoScene.js` | `THREE`; `TREES, NODE_R, BRANCH_R, LEAF_R, TRUNK_H, BRANCH_LEN` from `../data/trees`; `POINTER_MAP` from `../demo/knowledgeGraph` | OK |
| `useSimulationPlayback.js` | `useState, useEffect, useCallback` from `react` | OK |
| `SimulationController.jsx` | None (pure component) | OK |
| `DemoInfoPanel.jsx` | None (pure component) | OK |
| `App.jsx` | `lazy, Suspense` from `react`; lazy `./demo/DemoApp` | OK |

### Unused exports (not consumed)

- `GRAPH_STATS` in `knowledgeGraph.js` -- diagnostic only, tree-shaken in production.
- `getQueryStats` in `queryGenerator.js` -- diagnostic only, tree-shaken in production.
- `THEMES` in `queryGenerator.js` -- diagnostic only, tree-shaken in production.
- `jumpTo` returned from `useSimulationPlayback` but not destructured by DemoApp -- available for future use, not a problem.

### Fixed: Unused shared geometries in `buildDemoScene.js`

`octaGeo` (OctahedronGeometry) and `boxGeo` (BoxGeometry) were declared at module scope but never referenced. Removed to save memory.

## 3. Data Flow Integrity

Traced the full pipeline:

```
generateCheckpoints() --> CHECKPOINTS (array of 7)
  --> useSimulationPlayback(CHECKPOINTS) --> { checkpoint, checkpointIndex, ... }
    --> DemoApp: sceneRef.current.setCheckpoint(checkpoint)
    --> DemoInfoPanel: checkpoint.stats, checkpoint.diff
    --> SimulationController: checkpoint.queryIndex
```

### Checkpoint shape (produced by `checkpointGenerator.js`)

```
{
  queryIndex: number,
  trees: [{ id, label, subtitle, type, pos: [x,y,z],
            branches: [{ id, name, pointerIds, leaves, links }] }],
  unassignedPointers: string[],
  coAccessEdges: [{ a, b, weight, aboveThreshold }],
  diff: { newBranches, removedBranches, movedPointers, newTrees, removedTrees },
  stats: { treeCount, branchCount, assignedPointers, totalPointers,
           totalCoAccessEdges, edgesAboveThreshold }
}
```

### Consumers verified

| Consumer | Fields accessed | Match? |
|----------|----------------|--------|
| `buildDemoScene.setCheckpoint()` | `checkpoint.trees`, `checkpoint.unassignedPointers`, `checkpoint.coAccessEdges` | YES |
| `DemoInfoPanel` | `checkpoint.stats.*`, `checkpoint.diff.*` | YES |
| `SimulationController` | `checkpoint.queryIndex` (via `queryCount` prop) | YES |

Shape consistency confirmed at every boundary.

## 4. Memory Management

### Fixed: Shared geometry disposal

**Problem**: `sphereGeo`, `cylGeo`, `tetraGeo` are module-level shared geometries used by both Kibo and Nzyme scenes. When `setCheckpoint()` traversed and disposed nzyme scene objects, it also disposed these shared geometries, forcing GPU re-uploads for the Kibo scene on every checkpoint change.

**Fix**: Introduced a `sharedGeos` Set and a `disposeSceneObjects(scene, preserveShared)` helper. Checkpoint transitions now skip shared geometries (`preserveShared=true`); full teardown on unmount disposes everything (`preserveShared=false`).

### DemoApp unmount cleanup

- `cancelAnimationFrame(frameRef.current)` -- stops render loop. PASS.
- `window.removeEventListener("resize", ...)` -- removes resize handler. PASS.
- Canvas event listeners (pointerdown/move/up/leave, wheel) -- all removed. PASS.
- `ctx.dispose()` -- traverses both scenes, disposes all geometries/materials/textures, disposes renderer. PASS.

### Returning from demo to main app

When `demoMode` flips to `false`, React unmounts `DemoApp`, triggering the cleanup effect. The closure-scoped `nzymeScene` and `kiboScene` inside `buildDemoScene` are both properly disposed. No leaked WebGL resources.

### useSimulationPlayback timer

`setInterval` is cleared via effect cleanup on dependency changes and unmount. No timer leaks.

## 5. checkpointGenerator Correctness (CRITICAL)

### The `while` loop (line 171)

```javascript
while (state.pathCount < cpIndex && state.pathCount < queries.length) {
    addPathToMatrix(state, queries[state.pathCount].pointerIds);
}
```

**Verified**: `addPathToMatrix` (coAccessEngine.js line 35) increments `state.pathCount++` at the end of each call. The loop terminates when `state.pathCount >= cpIndex`. NOT an infinite loop.

### Progression across checkpoints

Since `state` is preserved across checkpoints (not recreated), each checkpoint feeds only its incremental queries:

| Checkpoint | cpIndex | Queries fed | state.pathCount after |
|-----------|---------|-------------|----------------------|
| 0 | 0 | 0 (loop skipped) | 0 |
| 1 | 15 | queries[0..14] | 15 |
| 2 | 35 | queries[15..34] | 35 |
| 3 | 70 | queries[35..69] | 70 |
| 4 | 120 | queries[70..119] | 120 |
| 5 | 170 | queries[120..169] | 170 |
| 6 | 200 | queries[170..199] | 200 |

Total: 200 queries fed. Matches `NZYME_QUERIES.length` (sum of theme counts: 22+22+20+22+20+18+18+18+20+20 = 200).

### Safety guard

Second condition `state.pathCount < queries.length` prevents overrun if `cpIndex` exceeds actual query count.

## 6. UI Correctness

### SimulationController

All 10 props wired correctly from DemoApp:
- `checkpointIndex`, `totalCheckpoints`, `isPlaying`, `speed` -- state display
- `onTogglePlay`, `onStepForward`, `onStepBackward`, `onSetSpeed` -- callbacks
- `queryCount` -- derived from `checkpoint.queryIndex`
- `onExit` -- propagated from DemoApp props

Buttons: `<<` (stepBackward), Play/Pause (togglePlay), `>>` (stepForward), speed selectors, Exit Demo. All functional.

### DemoInfoPanel

- Stats grid displays: treeCount, branchCount, assignedPointers/totalPointers, edgesAboveThreshold/totalCoAccessEdges.
- Diff section shows at checkpointIndex > 0: new branches, dissolved, moved pointers, new trees.
- Empty diff case handled: shows "No changes" when all diff arrays are empty.
- Checkpoint 0 shows italic message about empty forest.

### App.jsx

- `React.lazy(() => import("./demo/DemoApp"))` -- correct lazy import.
- `Suspense` fallback renders "Loading demo..." -- correct.
- `demoMode` state toggles between DemoApp and MainApp -- correct.
- MainApp receives `onDemo` prop via `<MainApp onDemo={() => setDemoMode(true)} />` -- correct.
- Demo button in toolbar uses dark styling to distinguish from other buttons -- correct.

## Summary

| Area | Status | Notes |
|------|--------|-------|
| Build | PASS | 103 modules, 0 errors, DemoApp chunk 24.58KB |
| Import resolution | PASS | All imports resolve |
| Unused imports | PASS | None found |
| Data flow shapes | PASS | Consistent across all boundaries |
| Memory management | FIXED | Shared geometry disposal now preserves Kibo scene geos |
| Dead code cleanup | FIXED | Removed unused `octaGeo` and `boxGeo` |
| Infinite loop risk | PASS | `addPathToMatrix` increments `state.pathCount` correctly |
| UI props wiring | PASS | All props matched between producer and consumer |
| Cleanup on unmount | PASS | Animation frame, listeners, renderer, scenes all disposed |
| Demo toggle | PASS | Lazy load, Suspense, bidirectional navigation working |
