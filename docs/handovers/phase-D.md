# Phase D Handover: Insertion + Dedup UI

## What was built

Three new UI components + a mutation hook that let users create pointers, search the graph, and resolve duplicates through the tiered dedup system.

### New files

1. **`src/hooks/usePointerMutation.js`** — Hook for pointer insertion and duplicate resolution:
   - `insertPointer({ label, type, canonical_key?, metadata?, attributes? })` — Calls the `insert-pointer` Edge Function. Returns `{ status, pointer_id, duplicates? }`.
   - `resolveDuplicate(flagId, resolution)` — Updates a `duplicate_flags` row to 'merged', 'distinct', or 'dismissed'.
   - Exposes `isSubmitting`, `lastResult`, `error`, `clearResult`, `clearError`.

2. **`src/components/InsertPanel.jsx`** — Pointer creation form:
   - Type dropdown (all 15 pointer types)
   - Label text input (required)
   - Canonical key input (optional, e.g. ticker symbol)
   - Dynamic attribute key-value pairs (add/remove rows)
   - Result banners: green for created, yellow for auto-merged, red for pending_review
   - "Review" button on pending_review opens DuplicatePanel
   - Submit calls `onInsert`, which flows through `usePointerMutation`

3. **`src/components/DuplicatePanel.jsx`** — Duplicate resolution modal:
   - Centered overlay (z-index 100)
   - Shows each duplicate match with:
     - Label, match method, trigram score, embedding score
     - Existing pointer's attributes (fetched via `get_pointer_subgraph`)
   - Three actions per match: "Merge (use existing)", "Keep Both", "Dismiss"
   - Resolution updates `duplicate_flags` and triggers forest refetch

4. **`src/components/SearchPanel.jsx`** — Fuzzy search for pointers:
   - Debounced search (300ms) using `ilike` on pointer labels
   - Shows results with label and type
   - Click result to select/navigate to that pointer
   - Max 20 results

### Modified files

5. **`src/App.jsx`** — Major wiring update:
   - Imports and uses `usePointerMutation` hook
   - State for `showInsert`, `showSearch`, `dupeResult`
   - Bottom-center toolbar with "+ Insert" and "Search" toggle buttons
   - `handleInsert`: calls insertPointer → on created/merged refetches forest, on pending_review opens DuplicatePanel
   - `handleResolveDuplicate`: resolves flag → closes panel → refetches forest
   - All three new panels wired with proper open/close/data flow

## How to verify it works

### 1. Build succeeds
```bash
npx vite build
# Expected: ✓ built successfully, 89 modules, no errors
```

### 2. Toolbar appears
Run `npx vite --open`. At bottom-center of the screen, two buttons should appear: "+ Insert" and "Search".

### 3. Insert panel opens
Click "+ Insert". The insert form should appear at bottom-left with:
- Label input, Type dropdown, Canonical Key input
- Dynamic attribute rows with + button
- Insert and Cancel buttons

### 4. Clean insert
Fill: Label="TestCompany", Type="company", click Insert.
Expected: Green banner "Created successfully" (if Supabase is configured and Edge Function works).

### 5. Duplicate detection
Insert again: Label="TestCmpany" (typo), Type="company".
Expected: Red banner "Potential duplicates found (1). [Review]"

### 6. Duplicate review
Click "Review" on the red banner. DuplicatePanel should appear as a centered modal showing:
- The matching pointer with similarity scores
- Three action buttons

### 7. Search works
Click "Search" in the toolbar. Type "NVIDIA" in the search box.
Expected: Results appear after 300ms debounce showing NVIDIA pointer.

### 8. Search navigates
Click a search result. Expected: The InfoPanel opens for that pointer (if the pointer ID is in the current forest's branchIndex).

## Design decisions

1. **Edge Function for insert, direct Supabase for search/resolve** — Insert needs the OpenAI embedding pipeline (Edge Function). Search and resolution are simple CRUD operations that work through the Supabase JS client directly.

2. **Search uses `ilike` not trigram** — For the search panel, simple `ilike` (case-insensitive LIKE) is sufficient and simpler than raw trigram queries. The trigram index will accelerate these queries automatically via PostgreSQL query planner.

3. **DuplicatePanel as modal overlay** — Duplicate review is a blocking operation (the plan specifies blocking in the 0.4-0.8 range), so it's presented as a centered modal rather than a side panel.

4. **Toolbar replaces ProjectionDemo's bottom-right space** — The new panels coexist with the existing ProjectionDemo component. The toolbar sits at bottom-center to avoid conflicts.

## Known issues / shortcuts taken

1. **Search doesn't use embeddings** — Uses `ilike` only. Semantic search (finding "Alphabet" when searching "Google") requires calling the embedding API from the frontend, which is deferred.
2. **DuplicatePanel flag query is imprecise** — It queries all pending flags for the new pointer, not specifically the pair. Works correctly for single-duplicate cases but may over-resolve when multiple flags exist.
3. **No validation on attribute values** — All attributes stored as strings. Numeric/date parsing deferred.
4. **No "link pointers" UI** — The `link-pointers` Edge Function is deployed but there's no UI for creating edges between pointers. Users can do this via the API.
5. **Search results clicking may not navigate in 3D** — `setInfo(pointerId)` sets the selected pointer ID, but if the pointer isn't in the current tenant's branchIndex (e.g., it's a newly inserted pointer not yet in a branch), the InfoPanel won't show anything. The forest needs a refetch first.

## Dependencies for next phase

Phase E (Query Path Logging + Dynamic Trees) needs:
- Navigation path tracking — hook into `setInfo` calls to log pointer access sequences
- `log-query-path` Edge Function already deployed (Phase B)
- `compute-forest` Edge Function already deployed (Phase B)

## Files to review

| File | What to check |
|------|--------------|
| `src/hooks/usePointerMutation.js` | Edge Function call pattern, error handling, auth token handling |
| `src/components/InsertPanel.jsx` | Form validation, result banner logic, attribute management |
| `src/components/DuplicatePanel.jsx` | Flag resolution logic, subgraph fetching, action handlers |
| `src/components/SearchPanel.jsx` | Debounce logic, query pattern, result rendering |
| `src/App.jsx` | Data flow: insertPointer → dedup handling → refetch cycle |
