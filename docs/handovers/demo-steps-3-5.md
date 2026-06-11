# Demo Steps 3-5 Handover: Scene + Playback + Integration

## What was built

### Step 3: `src/scene/buildDemoScene.js` — Split-screen scene
- Dual-viewport rendering via `renderer.setScissor()`/`renderer.setViewport()`
- Left viewport: Kibo's 13-tree static forest (dimmed lighting)
- Right viewport: Nzyme's evolving forest (rebuilt per checkpoint)
- `buildForestScene(trees, options)` — Reusable scene builder for any tree array
- `buildScatteredPointers(pointerIds)` — 58 scattered nodes for the empty state (checkpoint 0)
- `setCheckpoint(checkpoint)` — Rebuilds the right scene from checkpoint data, disposing old geometry
- Co-access lines rendered as gold lines for edges above threshold
- Proper memory management: all geometries/materials/textures disposed on checkpoint change and unmount

### Step 4: `src/hooks/useSimulationPlayback.js` — Playback controller
- Manages checkpoint index, isPlaying, speed (0.5x/1x/2x/4x)
- Auto-advance: 4s per checkpoint at 1x speed
- Stops at end, restarts from beginning if play pressed again at end
- `stepForward`/`stepBackward`/`jumpTo`/`togglePlay` callbacks

### Step 4: `src/components/SimulationController.jsx` — Playback UI
- Bottom bar: transport controls (<<, Play/Pause, >>)
- Progress dots (7 checkpoints, filled up to current)
- Query counter (N/200)
- Speed selector (0.5x, 1x, 2x, 4x)
- Exit Demo button

### Step 4: `src/components/DemoInfoPanel.jsx` — Checkpoint stats
- Top-right panel showing: tree count, branch count, assigned pointers, co-access edges
- Diff summary: new branches, dissolved branches, moved pointers, new trees
- Contextual message at checkpoint 0 ("Empty forest...")

### Step 4: `src/demo/DemoApp.jsx` — Demo root component
- Pre-computes checkpoints at module load (`generateCheckpoints()`)
- Builds split-screen scene on mount
- Camera orbit controls (drag to rotate, scroll to zoom)
- Auto-rotate at 0.15 rad/s
- Updates Nzyme scene when checkpoint changes
- Wires playback hook to controller UI
- Side labels ("Kibo (Investment Fund)" / "Nzyme (Regulatory Intel)")
- Vertical divider line at 50%
- Particle animation in Kibo scene

### Step 5: `src/App.jsx` — Integration
- Lazy import of DemoApp via `React.lazy()`
- `demoMode` state: true → renders DemoApp, false → renders MainApp
- Demo button in toolbar (dark themed, distinct from other buttons)
- `<Suspense fallback>` with "Loading demo..." while DemoApp chunk loads
- DemoApp code-split into separate 25KB chunk
- `onExit` callback navigates back to main app

## How to verify

### 1. Build succeeds
```bash
npx vite build
# Expected: ✓ 103 modules, DemoApp chunk separate (~25KB), no errors
```

### 2. Demo button visible
Run `npx vite --open`. Bottom toolbar should have a dark "Demo" button on the right.

### 3. Demo mode entry
Click "Demo". Screen should split in two:
- Left: Kibo's 13-tree forest (slightly dim)
- Right: Empty forest with 58 scattered pointer nodes
- Vertical divider line in the middle
- Labels at top: "Kibo (Investment Fund)" and "Nzyme (Regulatory Intel)"
- Info panel at top-right: Trees: 0, Branches: 0, Assigned: 0/58
- Playback controls at bottom

### 4. Playback works
- Click ">>" to advance to checkpoint 1 (15 queries) → right side should show first trees emerging
- Click ">>" repeatedly through all checkpoints → more trees appear on the right
- At checkpoint 6: right side should have ~10 trees (different from Kibo's 13)
- Click "<<" → goes back to previous checkpoint
- Click "Play" → auto-advances through checkpoints at 4s intervals

### 5. Speed control
- Click "2x" → auto-advance is 2s per checkpoint
- Click "4x" → 1s per checkpoint

### 6. Camera controls
- Drag canvas → orbits both viewports simultaneously
- Scroll → zooms both viewports
- Auto-rotate when not dragging

### 7. Exit demo
Click "Exit Demo" → returns to main forest app

### 8. Code splitting
Check browser Network tab: DemoApp chunk should load only when "Demo" button clicked, not on page load.

## Known issues / shortcuts

1. **No tree growth animation** — Trees appear instantly at each checkpoint (no trunk-rise or branch-unfold animation). Would require per-frame interpolation between checkpoints.
2. **No query path visualization** — Individual queries are not shown as glowing trails between checkpoints. The animation jumps between checkpoint states.
3. **Co-access lines only for above-threshold edges** — Below-threshold edges are not shown as faded lines.
4. **Camera sync is fixed** — Both viewports share the same camera angle. Can't independently orbit left vs right.
5. **Checkpoint generation runs on module load** — If `generateCheckpoints()` is slow (it shouldn't be for 200 queries), it could delay the initial lazy load.

## Files to review

| File | Lines | What to check |
|------|-------|--------------|
| `src/scene/buildDemoScene.js` | ~310 | Dual viewport rendering, memory disposal, scattered pointers, forest scene building |
| `src/hooks/useSimulationPlayback.js` | ~60 | Timer management, edge cases (end-of-playback, restart) |
| `src/components/SimulationController.jsx` | ~100 | UI layout, all buttons wired correctly |
| `src/components/DemoInfoPanel.jsx` | ~80 | Stats display, diff rendering |
| `src/demo/DemoApp.jsx` | ~160 | Scene lifecycle, camera controls, checkpoint updates, event cleanup |
| `src/App.jsx` | Modified | Lazy import, demo mode toggle, Suspense wrapper |
