# Phase F Handover: Adaptive Thresholds + Stability

## What was built

### Backend (Supabase migration 006)

1. **`check_threshold_recompute()` trigger** — Fires after every `duplicate_flags` UPDATE. When a flag transitions from 'pending' to a resolution (merged/distinct/dismissed), it counts total human resolutions. After 50+ resolutions, every 10th resolution triggers `recompute_dedup_thresholds()` automatically.

2. **`seed_tenant_from_template(new_tenant_id, template_tenant_id)`** — Cold start RPC. Copies all trees and branches from a template tenant to a new tenant, marking them `is_seed=true` with version 0. New tenants immediately see the template forest.

3. **`get_dedup_stats()`** — Returns current thresholds, flag counts by resolution status, and how many more resolutions are needed before adaptive kicks in.

### Frontend

4. **`src/components/StatsPanel.jsx`** — Dedup statistics panel:
   - Shows current auto-merge and review thresholds
   - Shows "Until adaptive" counter (50 - resolutions)
   - Shows resolution history counts (pending/merged/distinct/dismissed)
   - Accessible via "Stats" button in the toolbar

5. **`src/App.jsx`** — Added StatsPanel + "Stats" toolbar button. All toolbar buttons now mutually exclusive (opening one closes others).

## How to verify it works

### 1. Build succeeds
```bash
npx vite build
# Expected: ✓ 92 modules, no errors
```

### 2. get_dedup_stats returns correct initial state
```sql
SELECT get_dedup_stats();
-- Expected: { auto_merge_threshold: 0.8, review_threshold: 0.4, resolutions_until_adaptive: 50, ... }
```

### 3. Trigger exists
```sql
SELECT trigger_name, event_manipulation, action_statement 
FROM information_schema.triggers 
WHERE trigger_name = 'trg_check_threshold_recompute';
-- Expected: 1 row, AFTER UPDATE, EXECUTE FUNCTION check_threshold_recompute()
```

### 4. Cold start function works
```sql
-- Create test tenant
INSERT INTO tenants (id, name) VALUES ('00000000-0000-0000-0000-000000000001', 'TestTenant');

-- Seed from Kibo
SELECT seed_tenant_from_template(
  '00000000-0000-0000-0000-000000000001'::UUID,
  'ca61f0e5-563e-5894-954f-38f5a9e0eabc'::UUID
);
-- Expected: { status: "seeded", trees_copied: 13, branches_copied: 58 }

-- Verify
SELECT count(*) FROM tenant_trees WHERE tenant_id = '00000000-0000-0000-0000-000000000001';
-- Expected: 13

-- Cleanup
DELETE FROM tenants WHERE id = '00000000-0000-0000-0000-000000000001';
```

### 5. Stats panel renders
Run `npx vite --open`. Click "Stats" in the bottom toolbar.
Expected: Panel shows thresholds (80%/40%), "50 more" until adaptive, all counters at 0.

### 6. Adaptive trigger (simulated)
```sql
-- Simulate 50 human resolutions by inserting fake flags and resolving them
-- (This would require 50 pointer pairs — skip for now, verify trigger exists)
```

## Known issues / shortcuts taken

1. **Trigger fires on every UPDATE** — Even non-resolution updates (e.g., updating resolved_by) will trigger the function. The function guards against this (checks OLD.resolution = 'pending'), but it's extra overhead.
2. **No manual threshold override UI** — Thresholds can only be changed via SQL (`UPDATE system_config`). An admin panel is deferred.
3. **Stability mapping relies on compute-forest** — Already implemented in Phase B's compute-forest Edge Function. No additional frontend for viewing mapping history.

## Dependencies for next phase

Phase G (Integration + Deploy) needs:
- All features are implemented
- Feature flag removal
- Vercel env var configuration
- End-to-end testing

## Files to review

| File | What to check |
|------|--------------|
| Migration 006 (Supabase) | Trigger logic, cold start function, stats function |
| `src/components/StatsPanel.jsx` | Stats display, threshold formatting |
| `src/App.jsx` | StatsPanel wiring, toolbar mutual exclusivity |
