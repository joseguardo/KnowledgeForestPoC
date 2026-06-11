# Phase E Handover: Query Path Logging + Dynamic Trees

## What was built

The navigation path logging system that tracks how users explore the knowledge graph, and the UI for structure evolution alerts. This captures the behavioral data needed for dynamic tree generation.

### New files

1. **`src/hooks/useQueryPathLogger.js`** — Session-based navigation path logger:
   - Tracks every pointer selection (`logPointerAccess(pointerId)`)
   - Accumulates pointer IDs in a session buffer
   - Deduplicates consecutive same-pointer clicks
   - Session ends after 30 seconds of inactivity (configurable `SESSION_TIMEOUT_MS`)
   - On session end, calls the `log-query-path` Edge Function with:
     - `tenant_id`, `session_id` (UUID), `pointer_ids` (ordered array)
   - Minimum 2 pointers required to form a path (single clicks don't generate paths)
   - Flushes on component unmount to capture partial sessions
   - Uses `crypto.randomUUID()` for session IDs

2. **`src/components/StructureEvolutionAlert.jsx`** — Forest evolution notification:
   - On mount, queries `tenant_structure_events` for unacknowledged `structure_evolved` events
   - Subscribes to Supabase Realtime for new events (INSERT on `tenant_structure_events`)
   - Shows a banner at top-center with:
     - Tree/branch count changes
     - "Refresh" button (calls `refetch` to reload the forest)
     - "Dismiss" button (marks event as acknowledged)
   - Auto-hides when no unacknowledged events exist

### Modified files

3. **`src/App.jsx`** — Integrated path logging and evolution alerts:
   - Imports `useQueryPathLogger` and `StructureEvolutionAlert`
   - `useEffect` calls `logPointerAccess(info)` whenever selected pointer changes
   - `StructureEvolutionAlert` rendered with `onRefresh={refetch}`

## The Full Dynamic Tree Pipeline (end-to-end)

This is how all the pieces from Phases A-E connect:

```
User clicks pointer → App.jsx setInfo(pointerId)
  → useEffect logs via useQueryPathLogger.logPointerAccess()
    → After 30s idle, flush() sends to log-query-path Edge Function
      → Edge Function:
        1. Inserts query_path row
        2. Generates co-access pairs with proximity weighting
        3. Calls upsert_coaccess_batch (incremental)
        4. Calls update_coaccess_cursor (threshold check)
        5. If >10% change → creates forest_computation_jobs row
      → compute-forest Edge Function (triggered manually or by cron):
        1. Reads co-access edges above weight threshold
        2. Union-Find clustering → branches
        3. Agglomerative merge → trees
        4. LLM naming (OpenAI gpt-4o-mini)
        5. Stability mapping (Jaccard old→new)
        6. Emits structure_evolved event
      → StructureEvolutionAlert picks up the event
        → User clicks "Refresh" → refetch() reloads get_tenant_forest
          → 3D scene rebuilds with new tree structure
```

**Note**: The `compute-forest` Edge Function was deployed in Phase B. The connection between the threshold trigger (`forest_computation_jobs` row) and actually calling `compute-forest` is not yet automated — it requires either a cron job or manual invocation. This is expected for MVP and noted in the plan.

## How to verify it works

### 1. Build succeeds
```bash
npx vite build
# Expected: ✓ built successfully, 91 modules, no errors
```

### 2. Path logging integration
- Run `npx vite --open` with Supabase feature flag on
- Click on several branches in sequence (e.g., CrowdStrike → Cybersecurity → NVIDIA)
- Wait 30 seconds (session timeout)
- Check `query_paths` table in Supabase:
```sql
SELECT * FROM query_paths ORDER BY created_at DESC LIMIT 5;
```
Expected: A row with `pointer_ids` containing the UUIDs of clicked branches.

### 3. Co-access matrix populated
After paths are logged:
```sql
SELECT * FROM tenant_coaccess WHERE tenant_id = 'ca61f0e5-563e-5894-954f-38f5a9e0eabc' ORDER BY proximity_weight DESC LIMIT 10;
```
Expected: Co-access pairs with weights > 0.

### 4. Threshold check
```sql
SELECT * FROM tenant_coaccess_cursor WHERE tenant_id = 'ca61f0e5-563e-5894-954f-38f5a9e0eabc';
```
Expected: Row with `total_edges` > 0.

### 5. Structure evolution alert (manual test)
Insert a test event:
```sql
INSERT INTO tenant_structure_events (tenant_id, event_type, details)
VALUES ('ca61f0e5-563e-5894-954f-38f5a9e0eabc', 'structure_evolved', '{"old_branches": 58, "new_branches": 45, "new_trees": 10}');
```
Expected: Banner appears at top of screen with "Your forest has evolved".

### 6. Manual compute-forest invocation
After accumulating some paths:
```bash
curl -X POST https://rkuyvzcxaoulhjiflrmp.supabase.co/functions/v1/compute-forest \
  -H "Authorization: Bearer <service-role-key>" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "ca61f0e5-563e-5894-954f-38f5a9e0eabc", "weight_threshold": 1.0}'
```
Expected: Returns `{ status: "completed", trees_count, branches_count, pointers_assigned }`.

## Known issues / shortcuts taken

1. **No automatic compute-forest trigger** — The threshold check creates a `forest_computation_jobs` row, but nothing automatically invokes the `compute-forest` Edge Function. Requires a cron or webhook setup.
2. **Session timeout is fixed at 30s** — Not configurable from UI. May be too aggressive for slow explorers.
3. **Path logging fires on every pointer selection** — This includes selections from the InstanceBrowser sidebar, not just 3D scene clicks. This is actually desirable (captures all navigation patterns) but could generate more data than expected.
4. **Realtime subscription for events** — Requires Supabase Realtime to be enabled on the project (it is by default on new projects).

## Dependencies for next phase

Phase F (Adaptive Thresholds + Stability) needs:
- `duplicate_flags` rows with human resolutions (from Phase D's DuplicatePanel)
- `recompute_dedup_thresholds()` function (created in Phase A)
- `tenant_structure_mapping` table (populated by compute-forest in Phase B)
- The stability and threshold logic is purely backend — no new UI components needed

## Files to review

| File | What to check |
|------|--------------|
| `src/hooks/useQueryPathLogger.js` | Session management, flush logic, timer cleanup |
| `src/components/StructureEvolutionAlert.jsx` | Realtime subscription, event handling, cleanup |
| `src/App.jsx` | Path logging integration, StructureEvolutionAlert wiring |
