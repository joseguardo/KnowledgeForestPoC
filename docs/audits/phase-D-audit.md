# Phase D Audit: Insertion + Dedup UI

**Auditor**: Claude Opus 4.6 (1M context)
**Date**: 2026-06-10
**Handover reviewed**: `docs/handovers/phase-D.md`

---

## 1. Build Verification

| Check | Result |
|-------|--------|
| `npx vite build` succeeds | PASS - 91 modules transformed, built in 844ms, no errors |

---

## 2. File-by-File Review

### `src/hooks/usePointerMutation.js` - PASS

| Check | Result | Notes |
|-------|--------|-------|
| Edge Function URL construction | PASS | Uses `VITE_SUPABASE_URL` + `/functions/v1/insert-pointer` |
| Headers (Content-Type, Authorization) | PASS | Correct format, Bearer token from session or anon key fallback |
| Body format matches Edge Function contract | PASS | `{ label, type, canonical_key, metadata, attributes }` matches plan Section 4 |
| Error handling | PASS | try/catch, HTTP error check via `res.ok`, error state exposed |
| `resolveDuplicate` uses correct Supabase pattern | PASS | `.update().eq("id", flagId).select().single()` is correct |
| `isSubmitting` correctly toggled in finally block | PASS | |
| Auth token fallback to anon key | PASS (see note) | MVP-appropriate; anon key is inherently public in Supabase architecture |

### `src/components/InsertPanel.jsx` - PASS

| Check | Result | Notes |
|-------|--------|-------|
| Empty label prevention | PASS | `if (!label.trim()) return;` on submit + `disabled={!label.trim()}` on button |
| 15 pointer types listed | PASS | All 15 from plan accounted for |
| Attribute add/remove works | PASS | `addAttr` appends, `removeAttr` filters by index, remove button hidden when only 1 row |
| Attribute filtering (empty keys/values stripped) | PASS | `.filter((a) => a.key.trim() && a.value.trim())` before submit |
| Green banner for `created` | PASS | Shows "Created successfully" + New button |
| Yellow banner for `merged` | PASS | Shows auto-merge message |
| Red banner for `pending_review` | PASS | Shows duplicate count + Review button |
| Review button calls `onShowDuplicates` | PASS | Passes full `lastResult` |
| `onInsert` call shape matches `insertPointer` | PASS | `{ label, type, canonical_key, attributes }` - metadata omitted but hook defaults to `{}` |
| XSS risk in form inputs | PASS | React escapes all JSX text content; no `dangerouslySetInnerHTML` |

### `src/components/DuplicatePanel.jsx` - FIXED (was FAIL)

| Check | Result | Notes |
|-------|--------|-------|
| Subgraph fetch via `get_pointer_subgraph` | PASS | Correct RPC call with `p_pointer_id` parameter |
| Displays label, match_method, scores | PASS | All rendered in duplicate card |
| Three resolution actions | PASS | "Merge (use existing)" / "Keep Both" / "Dismiss" map to merged/distinct/dismissed |
| Flag query correctness | **FIXED** | Original had malformed `.or()` filter and dead code (see Issue 1 below) |
| Cleanup on close | **FIXED** | Added `setDuplicateDetails([])` reset and effect cancellation (see Issue 2 below) |
| Modal blocks interaction | **FIXED** | Added backdrop overlay div (see Issue 3 below) |
| `onResolve(flagId, resolution)` matches Supabase update pattern | PASS | Resolution flows through `handleResolveDuplicate` in App.jsx to `resolveDuplicate` in hook |

### `src/components/SearchPanel.jsx` - FIXED (minor)

| Check | Result | Notes |
|-------|--------|-------|
| Debounce 300ms | PASS | `setTimeout` with 300ms, `clearTimeout` on re-render and effect cleanup |
| Timer cleanup on unmount | PASS | Effect cleanup function calls `clearTimeout(timerRef.current)` |
| `ilike` query with limit 20 | PASS | Correct Supabase query pattern |
| LIKE wildcard escape | **FIXED** | User input `%` and `_` characters are now escaped (see Issue 4 below) |
| Click result calls `onSelect` | PASS | `onClick={() => onSelect(r.id)}` |
| No results / searching states | PASS | Both empty-state and loading indicator rendered |

### `src/App.jsx` - PASS

| Check | Result | Notes |
|-------|--------|-------|
| `usePointerMutation` hook wired | PASS | Destructures all needed values |
| `handleInsert` data flow | PASS | created -> refetch, merged -> refetch, pending_review -> setDupeResult |
| `handleResolveDuplicate` cleans up | PASS | Sets dupeResult null, clears result, refetches |
| Toolbar visibility (hidden in focus mode) | PASS | Wrapped in `!focusedTree &&` conditional |
| Toggle behavior (insert/search mutual exclusion) | PASS | Each toggle sets the other to false |
| InsertPanel receives all required props | PASS | open, onClose, onInsert, isSubmitting, lastResult, error, onClearResult, onShowDuplicates |
| SearchPanel `onSelect` integrates with selection system | PASS | Calls `setInfo(pointerId)` and closes search |
| DuplicatePanel receives correct props | PASS | insertResult, onResolve, onClose |

---

## 3. Issues Found and Fixed

### Issue 1 (BLOCKING): DuplicatePanel flag query was malformed and had dead code

**File**: `src/components/DuplicatePanel.jsx` lines 56-80 (original)

**Problem**: The `handleResolve` function had two sequential Supabase queries. The first used a malformed `.or()` filter:
```js
.or(`and(pointer_id_a.eq.${[newId, dupePointerId].sort().join(",pointer_id_b.eq.")})`)
```
This constructs an invalid PostgREST filter string. The result (`flags`) was never used -- it was dead code. Only the second, broader query ran, which resolved ALL pending flags for the new pointer regardless of which specific duplicate was being actioned.

**Fix**: Replaced with a precise query using `.eq("pointer_id_a", idA).eq("pointer_id_b", idB)` where `[idA, idB]` are sorted (matching the `a < b` constraint on `duplicate_flags`). Added a fallback to the broader query only if the precise match fails.

### Issue 2 (NON-BLOCKING): DuplicatePanel did not clean up state when closed/reopened

**File**: `src/components/DuplicatePanel.jsx` `useEffect`

**Problem**: When the panel was closed and reopened with a different `insertResult`, stale `duplicateDetails` from the previous review would flash briefly. The async fetch had no cancellation mechanism.

**Fix**: 
- Added `setDuplicateDetails([])` in the early-return path when `insertResult` is null/empty
- Added a `cancelled` flag with effect cleanup to prevent stale async results from updating state

### Issue 3 (NON-BLOCKING): DuplicatePanel had no backdrop overlay

**File**: `src/components/DuplicatePanel.jsx`

**Problem**: The handover describes a "centered overlay" modal, but the panel was just an absolutely positioned div with z-index 100. Users could still click on elements behind it (toolbar, insert panel, 3D canvas), violating the "blocking operation" design intent.

**Fix**: Added a semi-transparent backdrop div at z-index 99 that covers the entire parent, with `onClick={onClose}` to dismiss on backdrop click.

### Issue 4 (NON-BLOCKING): SearchPanel LIKE wildcard injection

**File**: `src/components/SearchPanel.jsx`

**Problem**: User input containing `%` or `_` characters was passed directly into the `.ilike()` query. While this is not SQL injection (Supabase parameterizes the value), these are LIKE pattern wildcards that would cause unintended matching behavior (e.g., searching for "100%" would match any label containing "100" followed by any characters).

**Fix**: Added escape of `%`, `_`, and `\` characters before interpolation: `query.trim().replace(/[%_\\]/g, (c) => \`\\${c}\`)`.

---

## 4. Quality Checks

| Check | Result |
|-------|--------|
| XSS risks in form inputs or displayed data | PASS - All values rendered via JSX (auto-escaped), no `dangerouslySetInnerHTML` |
| Memory leaks (event listeners, timers) | PASS - SearchPanel timer cleaned up in effect cleanup; DuplicatePanel async cancelled |
| Auth token security | PASS for MVP - Falls back to anon key (public by design in Supabase) when no session |
| DuplicatePanel cleanup on close | PASS (after fix) |

---

## 5. Interface Contract Checks

| Contract | Result | Notes |
|----------|--------|-------|
| InsertPanel `onInsert` -> `usePointerMutation.insertPointer` | PASS | Shape `{ label, type, canonical_key, attributes }` matches destructured params |
| DuplicatePanel `onResolve(flagId, resolution)` -> Supabase update | PASS | `handleResolveDuplicate` calls `resolveDuplicate(flagId, resolution)` which updates `duplicate_flags` |
| SearchPanel result click -> selection system | PASS | `onSelect(r.id)` flows to `setInfo(pointerId)` in App.jsx |
| `handleInsert` status routing | PASS | All 3 statuses handled: created/merged -> refetch, pending_review -> show DuplicatePanel |
| Phase E dependencies | PASS | `setInfo` is the navigation hook point for path logging; `refetch` is available for forest refresh |

---

## 6. Known Issues (not fixed, accepted per handover)

1. **Search does not use embeddings** - `ilike` only, as documented. Semantic search deferred.
2. **No attribute value validation** - All stored as strings. Documented shortcut.
3. **Search result click may not navigate if pointer not in branchIndex** - Documented in handover. Requires refetch first for newly inserted pointers.
4. **No "link pointers" UI** - Documented. Edge Function exists but no frontend.

---

## 7. Verdict

**PASS** - All blocking issues fixed. Build succeeds. Implementation matches handover claims and plan specifications. Interface contracts are correct for Phase E dependencies.

### Fixes applied
- `src/components/DuplicatePanel.jsx` - Fixed malformed flag query, added state cleanup, added backdrop overlay
- `src/components/SearchPanel.jsx` - Added LIKE wildcard escaping for user input
