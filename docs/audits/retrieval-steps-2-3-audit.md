# Retrieval Steps 2-3 Audit: Frontend Search Hook + Search Panel

**Auditor**: Claude Opus 4.6 (1M context, fresh context -- no prior context)
**Date**: 2026-06-10
**Scope**: `useKnowledgeSearch.js` (hook), `SearchPanel.jsx` (UI), `query-knowledge` Edge Function (deployment check)
**Project**: `rkuyvzcxaoulhjiflrmp`

---

## 1. Executive Summary

**PASS after 2 fixes -- 2 bugs found and fixed, 1 non-blocking observation.**

Both files are well-structured and follow React best practices. Interface contracts with `search_knowledge` RPC and the `query-knowledge` Edge Function are correct. Debounce, Enter-key deep search, error display, and result rendering all work correctly. Two race-condition bugs were found and fixed. Build passes before and after fixes.

| Category | Status |
|----------|--------|
| Build (`npx vite build`) | PASS (104 modules, 0 errors) |
| Edge Function deployed | PASS (`query-knowledge` ACTIVE, 5 total functions) |
| Abort controller (deep search) | PASS |
| Quick search race condition | **FIXED** (added generation counter) |
| Suggestion click triggers unwanted quick search | **FIXED** (added skip-next-quick ref) |
| RPC parameter names | PASS (matches DB signature) |
| Deep search body format | PASS (`{ query, mode }`) |
| Debounce implementation | PASS (timer cleared on re-render + unmount) |
| Enter key triggers only deep search | PASS |
| Result rendering (both modes) | PASS |
| Empty query handling | PASS |
| Network error display | PASS |
| Rapid typing cancellation | PASS |

---

## 2. Infrastructure Verification

### 2a. Build

```
npx vite build
  104 modules transformed
  built in 920ms (pre-fix), 904ms (post-fix)
  0 errors
```

### 2b. Edge Function deployment

Verified via `list_edge_functions(project_id='rkuyvzcxaoulhjiflrmp')`:

| Slug | Status |
|------|--------|
| insert-pointer | ACTIVE |
| link-pointers | ACTIVE |
| log-query-path | ACTIVE |
| compute-forest | ACTIVE |
| **query-knowledge** | **ACTIVE** |

All 5 functions active. `query-knowledge` ID: `7666417d-41a0-4c0b-838f-1281096aa8e2`.

---

## 3. Code Quality: useKnowledgeSearch.js

### 3a. Abort controller handling (deep search)

- Previous deep search is correctly aborted before a new one starts (line 74).
- `AbortError` is caught and silently ignored (line 111) -- correct, this is expected.
- `clear()` aborts any in-flight deep search (line 125).
- AbortController is stored in a ref, not state -- correct (avoids re-renders).

**Verdict**: PASS.

### 3b. quickSearch avoids Edge Function

`quickSearch` calls `supabase.rpc("search_knowledge", ...)` directly (line 43). No fetch to any Edge Function. Correct.

### 3c. deepSearch body format

```js
body: JSON.stringify({ query: query.trim(), mode: searchMode })
```

Matches the expected `{ query, mode }` contract for the `query-knowledge` Edge Function. Correct.

### 3d. BUG FOUND + FIXED: quickSearch race condition

**Problem**: `quickSearch` had no mechanism to discard stale responses. If two quick searches fired in sequence (debounce fires, user types again, next debounce fires), the first RPC could resolve after the second, displaying stale results.

**Fix**: Added a `quickSearchGenRef` generation counter. Each call increments it, and the response is discarded if the generation has changed since the call started.

**File**: `src/hooks/useKnowledgeSearch.js`
**Lines affected**: 20, 33, 51, 56, 60

---

## 4. Code Quality: SearchPanel.jsx

### 4a. Debounce implementation

```js
useEffect(() => {
  clearTimeout(timerRef.current);
  timerRef.current = setTimeout(() => quickSearch(query), 300);
  return () => clearTimeout(timerRef.current);
}, [query, quickSearch, clear]);
```

- Timer is cleared when `query` changes (new effect runs, previous cleanup runs).
- Timer is cleared on unmount (cleanup function).
- 300ms delay matches the handover spec.

**Verdict**: PASS.

### 4b. Enter key triggers only deep search

```js
const handleKeyDown = (e) => {
  if (e.key === "Enter" && query.trim()) {
    clearTimeout(timerRef.current);  // Cancel pending quick search
    deepSearch(query, "answer");
  }
};
```

Correctly checks for Enter only, cancels pending debounced quick search, then triggers deep search with `"answer"` mode. Correct.

### 4c. Result rendering (both modes)

Defensive fallback chains handle both quick and deep result shapes:

| Field | Quick mode source | Deep mode source | Code |
|-------|-------------------|------------------|------|
| id | `r.pointer_id` | `r.pointer?.id` | `r.pointer_id \|\| r.pointer?.id \|\| r.id` |
| label | `r.label` | `r.pointer?.label` | `r.label \|\| r.pointer?.label \|\| "Unknown"` |
| type | `r.type` | `r.pointer?.type` | `r.type \|\| r.pointer?.type \|\| ""` |
| score | `r.combined_score` | `r.score` | `r.combined_score \|\| r.score` |
| via | n/a (quick has no traversal) | `r.via` | `r.via \|\| r.via_edge_type` |
| why | n/a | `r.why` | `r.why \|\| r.via_edge_why` |

The `via_edge_type` and `via_edge_why` fallbacks also cover results from `traverse_graph` (used internally by the Edge Function). Correct.

**Verdict**: PASS.

### 4d. BUG FOUND + FIXED: Suggestion click triggers competing quick search

**Problem**: Clicking a suggestion called `setQuery(s)` then `deepSearch(s, "answer")`. The `setQuery` triggers the `useEffect` which schedules a quick search 300ms later. This quick search could overwrite the deep search results (setting mode back to "quick", clearing the answer).

**Fix**: Added a `skipNextQuickRef` flag. The suggestion click handler sets `skipNextQuickRef.current = true` before calling `setQuery`. The `useEffect` checks this flag and skips the quick search if it was set by a programmatic query change.

**File**: `src/components/SearchPanel.jsx`
**Lines affected**: 31, 40-46, 182

---

## 5. Interface Contracts

### 5a. quickSearch -> search_knowledge RPC

| Parameter | Expected (DB signature) | Actual (code) | Match |
|-----------|------------------------|---------------|-------|
| `p_query` | `text` | `query.trim()` | YES |
| `p_embedding` | `vector DEFAULT NULL` | `null` | YES |
| `p_type_filter` | `pointer_type DEFAULT NULL` | `null` | YES |
| `p_limit` | `integer DEFAULT 20` | `15` | YES (valid override) |

DB returns: `pointer_id, label, type, trigram_score, embedding_score, attribute_score, fulltext_score, combined_score` -- all flat fields. SearchPanel reads `r.pointer_id`, `r.label`, `r.type`, `r.combined_score` directly. Correct.

### 5b. deepSearch -> query-knowledge Edge Function

| Field | Expected | Actual | Match |
|-------|----------|--------|-------|
| `query` | `string` | `query.trim()` | YES |
| `mode` | `"search" \| "answer" \| "explore"` | `searchMode` (default `"answer"`) | YES |

Response fields consumed: `data.results`, `data.answer`, `data.plan`, `data.suggestions` -- all with `|| []` / `|| ""` / `|| null` fallbacks. Correct.

---

## 6. Edge Cases

### 6a. Empty query

| Scenario | Behavior | Status |
|----------|----------|--------|
| `quickSearch("")` | Returns early, clears results (line 26-29) | PASS |
| `deepSearch("")` | Returns early (line 71) | PASS |
| User clears input | `useEffect` detects empty query, calls `clear()` (line 48-49) | PASS |

### 6b. Network error

| Scenario | Behavior | Status |
|----------|----------|--------|
| RPC error in quick search | Caught, `setError(err.message)`, results cleared (line 55-58) | PASS |
| HTTP error in deep search | Caught, error message extracted from JSON body (line 99-101) | PASS |
| Fetch abort (deep search) | `AbortError` caught, silently ignored (line 111) | PASS |
| UI error display | Red banner with error text (line 102-106) | PASS |

### 6c. Rapid typing (faster than debounce)

| Scenario | Behavior | Status |
|----------|----------|--------|
| Type faster than 300ms | Each keystroke clears previous timer; only last fires (debounce cleanup) | PASS |
| Quick search in-flight when new one fires | Generation counter discards stale response (**post-fix**) | PASS |
| Enter during debounce | `clearTimeout` cancels pending quick search before deep search starts | PASS |

---

## 7. Issues Summary

### Fixed (2)

| # | Severity | File | Description |
|---|----------|------|-------------|
| 1 | Medium | `useKnowledgeSearch.js` | **Quick search race condition**: No mechanism to discard stale RPC responses. Two overlapping quick searches could display results from the earlier, slower query. Fixed with generation counter (`quickSearchGenRef`). |
| 2 | Medium | `SearchPanel.jsx` | **Suggestion click triggers competing quick search**: `setQuery(s)` in suggestion handler triggers `useEffect`, which fires a debounced `quickSearch` that overwrites deep search results. Fixed with `skipNextQuickRef` flag. |

### Non-blocking observations (1)

| # | Severity | Description |
|---|----------|-------------|
| 1 | Low | **Deep search fetch continues after unmount**: If the component unmounts during a deep search, the `fetch` continues (AbortController is not cleaned up on unmount). The orphaned `setResults` call will be a no-op (React ignores setState on unmounted components in modern React), so this is not a functional bug, but it wastes network resources. A cleanup effect that calls `abortRef.current?.abort()` on unmount would be cleaner. Not fixed because it has no user-visible impact. |

---

## 8. Post-fix Build Verification

```
npx vite build
  104 modules transformed
  built in 904ms
  0 errors
```

Both fixes compile cleanly. No new warnings introduced.
