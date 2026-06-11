# Phase E Audit: Query Path Logging + Dynamic Trees

**Auditor**: Claude Opus 4.6 (1M context)
**Date**: 2026-06-10
**Handover reviewed**: `docs/handovers/phase-E.md`

---

## 1. Build Verification

| Check | Result |
|-------|--------|
| `npx vite build` succeeds (before fix) | PASS - 91 modules transformed, built in 833ms, no errors |
| `npx vite build` succeeds (after fix) | PASS - 91 modules transformed, built in 862ms, no errors |

Note: The build passes both before and after the fix because Vite/Rollup does not perform temporal dead zone analysis on `const` references within the same function body. The bug only manifests at runtime.

---

## 2. File-by-File Review

### `src/hooks/useQueryPathLogger.js` - PASS

| Check | Result | Notes |
|-------|--------|-------|
| Session management (timer cleared on new access) | PASS | `clearTimeout(timerRef.current)` called before `setTimeout` in `logPointerAccess` (line 75-76) |
| Session management (flushed on unmount) | PASS | Cleanup function clears timer then calls `flush()` (lines 83-86) |
| Duplicate consecutive clicks deduplicated | PASS | `path[path.length - 1] === pointerId` check (line 70) |
| Flush skips paths < 2 pointers | PASS | `pointerIds.length < 2` guard (line 31) |
| Session reset after flush | PASS | `pathRef.current = []` and new `sessionIdRef` in both early-return and normal paths (lines 33-34, 39-40) |
| Edge Function URL construction | PASS | `${SUPABASE_URL}/functions/v1/log-query-path` |
| Headers (Content-Type, Authorization) | PASS | Bearer token from `VITE_SUPABASE_ANON_KEY` |
| Body format (tenant_id, session_id, pointer_ids) | PASS | All three fields present, matches Edge Function contract |
| Error handling | PASS | try/catch around fetch, `res.ok` check with error logging |
| Memory leaks (timers) | PASS | Timer cleared on unmount cleanup, cleared before each reset |
| Race condition: flush + logPointerAccess | PASS | `pathRef.current = []` is set synchronously before `await fetch`, so any new `logPointerAccess` calls during the fetch write to the new array. Captured `pointerIds` reference remains stable. |
| Race condition: double flush | PASS | If flush runs twice (timer + unmount), the second call sees `pathRef.current = []` from the first flush and exits via the `length < 2` guard |
| `crypto.randomUUID()` availability | PASS | Available in all modern browsers and secure contexts |
| `USE_SUPABASE` guard | PASS | Checked in both `flush` and `logPointerAccess` |

### `src/components/StructureEvolutionAlert.jsx` - PASS

| Check | Result | Notes |
|-------|--------|-------|
| Null check on `supabase` client | PASS | `if (!supabase || !TENANT_ID) return;` (line 26) |
| Initial event query | PASS | Filters by `tenant_id`, `acknowledged=false`, `event_type=structure_evolved`, orders desc, limit 1 |
| Realtime subscription setup | PASS | `postgres_changes` on INSERT to `tenant_structure_events`, filtered by `tenant_id` |
| Realtime event filtering | PASS | Checks `event_type === "structure_evolved"` and `!acknowledged` in callback |
| Subscription cleanup on unmount | PASS | `supabase.removeChannel(channel)` in cleanup function (line 66) |
| Acknowledge function null guards | PASS | `if (!event \|\| !supabase) return;` (line 71) |
| Acknowledge updates correct row | PASS | `.update({ acknowledged: true }).eq("id", event.id)` |
| Refresh + acknowledge flow | PASS | `handleReview` calls `onRefresh?.()` then `acknowledge()` |
| Positioning (absolute via `.panel`) | PASS | `.panel` class provides `position: absolute`, `top: 80` and `left: 50%` with centering transform |
| Missing `position` in inline style | PASS | Provided by `.panel` CSS class |

### `src/App.jsx` - FIXED (was FAIL)

| Check | Result | Notes |
|-------|--------|-------|
| `useQueryPathLogger` hook wired | PASS | `logPointerAccess` destructured |
| `logPointerAccess` called when `info` changes | **FIXED** | Was referencing `info` before declaration (see Issue 1 below) |
| `useEffect` excessive logging risk | PASS (after fix) | `if (info)` guard prevents logging on mount (when `info` is null) and on deselection |
| `StructureEvolutionAlert` rendered with `onRefresh` | PASS | `<StructureEvolutionAlert onRefresh={refetch} />` |
| `info` value type compatible with `logPointerAccess` | PASS | `info` is a branchId (string UUID) or null; `logPointerAccess` expects a pointerId string and guards against falsy |

---

## 3. Issues Found and Fixed

### Issue 1 (BLOCKING): `useEffect` referenced `info` before `const` declaration -- temporal dead zone error

**File**: `src/App.jsx` lines 42-63 (original)

**Problem**: The `useEffect` that calls `logPointerAccess(info)` was placed at line 43, but `info` was destructured from `useForestScene` at line 51. In JavaScript, `const` declarations are block-scoped and exist in a "temporal dead zone" from the start of the block until the declaration statement is evaluated. When React calls `useEffect(callback, [info, logPointerAccess])` during render, the dependency array `[info, logPointerAccess]` is evaluated immediately. At that point, `info` has not yet been initialized, which throws:

```
ReferenceError: Cannot access 'info' before initialization
```

This would crash the entire application on first render.

Vite's production build does NOT catch this because it performs tree-shaking and bundling without runtime analysis of variable initialization order within function bodies. The error only surfaces at runtime.

**Fix**: Moved the `useEffect` block to after the `useForestScene` destructuring, so `info` is fully initialized before it is referenced in the dependency array.

**Lines changed**: `src/App.jsx` -- moved lines 43-45 to after line 63 (now lines 60-62)

---

## 4. Quality Checks

| Check | Result |
|-------|--------|
| Memory leaks (timers) | PASS - `timerRef` cleared in both `logPointerAccess` (reset) and unmount cleanup |
| Memory leaks (subscriptions) | PASS - Realtime channel removed via `supabase.removeChannel(channel)` on unmount |
| 30s session timeout reasonable? | PASS - Reasonable for exploratory navigation. Documented as potentially aggressive for slow users (handover known issue #2) |
| Race conditions in flush/log cycle | PASS - Synchronous array reset before async fetch prevents data loss |
| Double-flush on unmount + timer | PASS - `clearTimeout` prevents timer flush; only manual unmount flush runs |
| XSS risks | PASS - All values rendered via JSX (auto-escaped) |
| Auth token handling | PASS for MVP - Uses anon key (public by design in Supabase) |

---

## 5. Interface Contract Checks

| Contract | Result | Notes |
|----------|--------|-------|
| `logPointerAccess(pointerId)` receives correct value | PASS | `info` is a branchId (UUID string) from `useForestScene` |
| `flush()` -> `log-query-path` Edge Function | PASS | POST with `{ tenant_id, session_id, pointer_ids }` matches plan |
| `StructureEvolutionAlert.onRefresh` -> `refetch` | PASS | `refetch` from `useForestData` reloads `get_tenant_forest` |
| Realtime subscription filter matches insert pattern | PASS | Filters `tenant_id=eq.${TENANT_ID}` on INSERT events |
| Phase F dependencies (from handover) | PASS | `duplicate_flags`, `recompute_dedup_thresholds()`, `tenant_structure_mapping` are all from prior phases |

---

## 6. Known Issues (not fixed, accepted per handover)

1. **No automatic compute-forest trigger** - Threshold check creates `forest_computation_jobs` row but nothing invokes the Edge Function automatically. Requires cron or manual invocation.
2. **30s session timeout is fixed** - Not configurable from UI. May be too aggressive for slow explorers.
3. **Path logging captures all pointer selections** - Including InstanceBrowser sidebar clicks. Documented as intentional.
4. **Realtime requires enabled Supabase Realtime** - Default on new projects.

---

## 7. Verdict

**PASS** - One blocking issue fixed. Build succeeds. Implementation matches handover claims and plan specifications.

### Fixes applied
- `src/App.jsx` - Moved `useEffect` for path logging below `useForestScene` destructuring to fix temporal dead zone `ReferenceError` that would crash the app on first render
