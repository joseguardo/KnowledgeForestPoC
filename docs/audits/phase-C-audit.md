# Phase C Audit: Frontend Data Layer

**Date**: 2026-06-10
**Auditor**: Claude Opus 4.6 (fresh context, no prior conversation)
**Inputs**: `docs/handovers/phase-C.md`, overall plan (sections 5 & 8), full codebase

---

## 1. Correctness

### 1.1 Build succeeds — PASS
```
npx vite build
✓ 85 modules transformed
✓ built in 837ms (no errors)
```
Warning about chunk size (946 kB) is expected for Three.js — non-blocking.

### 1.2 `buildScene.js` accepts data params and falls back to defaults — PASS
Line 24: `export default function buildScene(canvas, width, height, { trees: TREES, branchIndex: BRANCH_INDEX, houses: HOUSES } = {})`
Lines 25-27: Falls back to `[]`, `{}`, and `DEFAULT_HOUSES` respectively.
Geometry constants (`SCALE`, `NODE_R`, `BRANCH_R`, `LEAF_R`, `TRUNK_H`, `BRANCH_LEN`, `vec3`) are still imported from `trees.js` — correct, these are geometry utilities not data.

### 1.3 `useForestScene.js` passes data through and rebuilds on change — PASS
Line 24: Accepts `{ trees: TREES, branchIndex: BRANCH_INDEX, houses: HOUSES }` as params.
Line 49: Passes `{ trees: TREES, branchIndex: BRANCH_INDEX, houses: HOUSES }` to `buildScene`.
Line 358: `useEffect` depends on `[TREES, BRANCH_INDEX, HOUSES]` — rebuilds when data changes.
Lines 360-363, 365-377: `selected` and `inboundLinks` useMemo hooks correctly use parameterized data.

### 1.4 `useForestData.js` falls back to static data when feature flag is off — PASS
Lines 10-11: State initialized with static `TREES` and `BRANCH_INDEX` from `trees.js`.
Line 16: `fetchForest` returns early if `USE_SUPABASE` is false or `TENANT_ID` is missing.
Lines 35-38: On error, static fallback data is preserved (no `setTrees([])` call).

### 1.5 `forestAdapter.js` transforms Supabase shape correctly — PASS
Lines 16-18: Handles null/non-array input gracefully.
Lines 20-32: Maps Supabase fields (`id`, `label`, `subtitle`, `type`, `pos`, `branches`) to the exact shape buildScene expects.
Lines 34-41: Builds `branchIndex` with `{ tree, branch }` entries — matches how `InfoPanel` and cross-link logic consume it.

### 1.6 `InfoPanel.jsx` no longer imports from `../data/trees` — PASS
Line 1: `export default function InfoPanel({ selected, inboundLinks, onSelect, onClose, branchIndex = {} })`
Receives `branchIndex` as prop. No static import of `BRANCH_INDEX`.

### 1.7 `InstanceBrowser.jsx` no longer imports from `../data/trees` — PASS
Line 1: `export default function InstanceBrowser({ info, hovered, onSelect, onHover, trees = [] })`
Receives `trees` as prop. No static import of `TREES`.

---

## 2. Completeness

### 2.1 Files from Plan Section 5 — PARTIAL PASS

| File | Status |
|------|--------|
| `src/lib/supabase.js` | EXISTS |
| `src/lib/forestAdapter.js` | EXISTS |
| `src/hooks/useForestData.js` | EXISTS |
| `src/hooks/usePointerMutation.js` | NOT YET (Phase D) |
| `src/hooks/useQueryPathLogger.js` | NOT YET (Phase E) |
| `src/components/InsertPanel.jsx` | NOT YET (Phase D) |
| `src/components/DuplicatePanel.jsx` | NOT YET (Phase D) |
| `src/components/SearchPanel.jsx` | NOT YET (Phase D) |
| `src/components/StructureEvolutionAlert.jsx` | NOT YET (Phase E) |

All Phase C files exist. The "NOT YET" files are planned for future phases — correct per the phased approach.

### 2.2 Static imports of TREES/BRANCH_INDEX removed from data flow — PASS

Grep for `from "../data/trees"` in modified files:
- `InfoPanel.jsx` — **No import** (clean)
- `InstanceBrowser.jsx` — **No import** (clean)
- `useForestData.js` — Imports `TREES, BRANCH_INDEX, HOUSES, HOUSE_INDEX` for **static fallback** (correct design)
- `buildScene.js` — Imports `HOUSES as DEFAULT_HOUSES, DB_TABLES, vec3, NODE_R, BRANCH_R, LEAF_R, TRUNK_H, BRANCH_LEN` — geometry constants + DB_TABLES (non-dynamic metadata, correct)
- `HousePanel.jsx` — Imports `HOUSE_INDEX, TREES` (intentionally **not** refactored per handover item 4: "Houses stay static")
- `TablePanel.jsx` — Imports `DB_TABLES, HOUSE_INDEX` (intentionally **not** refactored, same reason)

### 2.3 `.env.local` gitignored — PASS
`.gitignore` contains both `.env.local` and `.env*.local`.

---

## 3. Quality

### 3.1 Broken imports — PASS
All imports resolve. Build succeeds with 85 modules, no missing module errors.

### 3.2 Memory leak on scene rebuild — FIXED (was FAIL)

**Issue found**: The `useEffect` cleanup in `useForestScene.js` only called `ctx.renderer.dispose()` but did NOT dispose geometries, materials, or textures created by `buildScene`. When Supabase data arrives and the effect re-runs, the old scene's GPU resources would leak.

**Fix applied**: Added a `ctx.scene.traverse()` call in the cleanup function that disposes all geometries, materials (including arrays), and texture maps before disposing the renderer.

### 3.3 Supabase client initialization — FIXED (was FAIL)

**Issue found**: `supabase.js` called `createClient(supabaseUrl, supabaseAnonKey)` unconditionally. When `VITE_SUPABASE_URL` or `VITE_SUPABASE_ANON_KEY` are undefined (e.g., feature flag off, no `.env.local` present), `createClient(undefined, undefined)` throws at import time, crashing the entire app.

**Fix applied**: Added fallback to empty strings and a null guard: `supabase` is now `null` when env vars are missing. Updated `useForestData.js` to check `!supabase` alongside the feature flag check.

### 3.4 No hardcoded keys — PASS
All secrets come from `import.meta.env.VITE_*` variables. The `.env.local` file (which contains the actual keys) is gitignored.

---

## 4. Interface Contracts

### 4.1 Data flow: useForestData -> App -> useForestScene -> buildScene — PASS

```
useForestData() returns { trees, branchIndex, houses, ... }
    |
    v
App.jsx destructures { trees, branchIndex, houses }
    |
    v
useForestScene({ trees, branchIndex, houses })
    |
    v
buildScene(canvas, W, H, { trees, branchIndex, houses })
```

All prop names are consistent across the chain. The destructuring parameter names match at every boundary.

### 4.2 Props to InfoPanel — PASS
`App.jsx` line 58: `<InfoPanel ... branchIndex={branchIndex} />`
`InfoPanel.jsx` line 1: `function InfoPanel({ ..., branchIndex = {} })`
Used on lines 46, 67-68 to resolve branch names for links.

### 4.3 Props to InstanceBrowser — PASS
`App.jsx` line 46: `<InstanceBrowser ... trees={trees} />`
`InstanceBrowser.jsx` line 1: `function InstanceBrowser({ ..., trees = [] })`
Used on line 17 to map and render tree/branch listing.

### 4.4 Dependencies for Phase D — PASS
- `supabase` client exported from `src/lib/supabase.js` — available for Phase D's `usePointerMutation`
- `refetch` returned by `useForestData` — ready for calling after pointer insertion
- Feature flag pattern established for progressive rollout

---

## 5. Issues Summary

| # | Severity | Description | Status |
|---|----------|-------------|--------|
| 1 | **Blocking** | Memory leak: scene geometries/materials/textures not disposed on rebuild | **FIXED** |
| 2 | **Blocking** | Supabase client crashes when env vars are missing | **FIXED** |
| 3 | Non-blocking | No loading indicator shown during Supabase fetch (isLoading unused in App.jsx) | Known — documented in handover |
| 4 | Non-blocking | Scene flash/flicker on data load (dispose + rebuild) | Known — documented in handover |
| 5 | Non-blocking | Bundle size warning (946 kB) from Three.js | Expected for Three.js apps, no action needed |

---

## 6. Files Modified by Audit

| File | Change |
|------|--------|
| `src/hooks/useForestScene.js` | Added `scene.traverse()` cleanup to dispose geometries, materials, and textures |
| `src/lib/supabase.js` | Added null guard for missing env vars; `supabase` export is `null` when config is absent |
| `src/hooks/useForestData.js` | Added `!supabase` check to `fetchForest` early return |

---

## 7. Post-fix Build Verification — PASS
```
npx vite build
✓ 85 modules transformed
✓ built in 831ms (no errors)
```

---

## Verdict: PASS (after fixes)

All blocking issues have been resolved. Phase D may proceed.
