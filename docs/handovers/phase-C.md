# Phase C Handover: Frontend Data Layer

## What was built

Replaced all static data imports with a Supabase-backed data layer, controlled by a feature flag. The 3D visualization now works from either hardcoded data (flag off) or Supabase (flag on).

### New files created

1. **`src/lib/supabase.js`** — Supabase client singleton using `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` env vars.

2. **`src/lib/forestAdapter.js`** — Transforms `get_tenant_forest()` RPC response into the exact shape `buildScene.js` expects. Handles null/empty data gracefully. Builds `branchIndex` from adapted trees.

3. **`src/hooks/useForestData.js`** — Hook that fetches forest data from Supabase when `VITE_FEATURE_SUPABASE=true` and `VITE_KIBO_TENANT_ID` is set. Falls back to static `trees.js` data on error or when feature flag is off. Returns `{ trees, branchIndex, houses, houseIndex, isLoading, error, refetch }`.

4. **`.env.local`** — Environment variables (gitignored):
   - `VITE_SUPABASE_URL` — Supabase project URL
   - `VITE_SUPABASE_ANON_KEY` — Supabase anon key
   - `VITE_FEATURE_SUPABASE=true` — Feature flag
   - `VITE_KIBO_TENANT_ID=ca61f0e5-563e-5894-954f-38f5a9e0eabc` — Kibo tenant UUID

### Modified files

5. **`src/scene/buildScene.js`** — Now accepts `{ trees, branchIndex, houses }` as a 4th parameter instead of importing `TREES`, `HOUSES`, `DB_TABLES`, `BRANCH_INDEX` from trees.js. Geometry constants (`SCALE`, `NODE_R`, etc.) still imported from trees.js. Falls back to defaults if params not provided.

6. **`src/hooks/useForestScene.js`** — Now accepts `{ trees, branchIndex, houses }` as parameters. Passes data to `buildScene`. `useEffect` dependency array includes `[TREES, BRANCH_INDEX, HOUSES]` so scene rebuilds when data changes. `selected` and `inboundLinks` useMemo hooks use parameterized data.

7. **`src/components/InfoPanel.jsx`** — Removed static `BRANCH_INDEX` import. Receives `branchIndex` as a prop instead.

8. **`src/components/InstanceBrowser.jsx`** — Removed static `TREES` import. Receives `trees` as a prop instead.

9. **`src/App.jsx`** — Wires `useForestData()` into `useForestScene()`. Passes `trees` to `InstanceBrowser` and `branchIndex` to `InfoPanel`.

10. **`.gitignore`** — Added `node_modules`, `dist`, `.env.local`, `.env*.local`.

### Dependencies added

- `@supabase/supabase-js` (59 packages)

## How to verify it works

### 1. Build succeeds
```bash
cd /Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC
npx vite build
# Expected: ✓ built successfully, no errors
```

### 2. Feature flag OFF (static data)
Set `VITE_FEATURE_SUPABASE=false` in `.env.local`, then:
```bash
npx vite --open
```
Expected: 3D forest renders identically to original PoC (13 trees, all branches, hover/click/focus work).

### 3. Feature flag ON (Supabase data)
Set `VITE_FEATURE_SUPABASE=true` in `.env.local`, then:
```bash
npx vite --open
```
Expected: 3D forest renders from Supabase data. Should look identical since seed data matches trees.js.

### 4. Verify all interactions work
- Hover over branches → scale animation
- Click branch → InfoPanel shows properties and links
- Click tree root → focus mode enters
- Click "Back to forest" → exits focus
- InstanceBrowser sidebar lists all branches grouped by tree
- Cross-tree links (dashed curves) render correctly

## Design decisions made during implementation

1. **Static fallback**: `useForestData` initializes state with the static `TREES`/`BRANCH_INDEX` from trees.js. If Supabase fetch fails, users still see the PoC. No blank screen.

2. **Scene rebuild on data change**: The `useEffect` in `useForestScene` depends on `[TREES, BRANCH_INDEX, HOUSES]`. When Supabase data arrives, the entire Three.js scene is disposed and rebuilt. This is simple and correct but causes a brief flash on load. Acceptable for MVP.

3. **Houses stay static**: `HOUSES` and `DB_TABLES` are still imported from trees.js (system metadata, not user data). They're not in Supabase.

4. **No HousePanel/TablePanel changes**: These components still import directly from trees.js since houses aren't in the dynamic data layer.

## Known issues / shortcuts taken

1. **Scene flash on data load** — When Supabase data arrives, the scene rebuilds (dispose + create). Brief white flash. Could be smoothed with a loading overlay in a future pass.
2. **`vec3` still imported from trees.js** — `buildScene.js` uses `vec3()` which depends on THREE.js. This stays as a trees.js import since it's a utility, not data.
3. **No loading indicator** — `useForestData` exposes `isLoading` but App.jsx doesn't show a loader. The static fallback renders immediately.
4. **Houses still statically imported** in HousePanel.jsx and the DB_TABLES in TablePanel.jsx.

## Dependencies for next phase

Phase D (Insertion + Dedup UI) needs:
- The Supabase client (`src/lib/supabase.js`) is ready
- `refetch` from `useForestData` can be called after inserting a pointer to refresh the scene
- The `insert-pointer` Edge Function from Phase B is deployed and ready

## Files to review

| File | What changed |
|------|-------------|
| `src/App.jsx` | Wires useForestData → useForestScene → components |
| `src/hooks/useForestScene.js` | Accepts data params, passes to buildScene |
| `src/scene/buildScene.js` | Accepts data params instead of static imports |
| `src/hooks/useForestData.js` | NEW: Supabase data fetching hook |
| `src/lib/forestAdapter.js` | NEW: Data shape transformer |
| `src/lib/supabase.js` | NEW: Supabase client |
| `src/components/InfoPanel.jsx` | Receives branchIndex as prop |
| `src/components/InstanceBrowser.jsx` | Receives trees as prop |
