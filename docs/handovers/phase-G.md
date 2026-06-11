# Phase G Handover: Integration + Deploy

## What was built

Final integration phase — no new code, focused on verification and deploy readiness.

### Deploy configuration

**Vercel environment variables needed:**
```
VITE_SUPABASE_URL=https://rkuyvzcxaoulhjiflrmp.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJrdXl2emN4YW91bGhqaWZscm1wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwNzk0MzAsImV4cCI6MjA5NjY1NTQzMH0.wBqZtj7oYrVA9AdSzpzFRB5nbCPZMzjfremGv3Gx2wI
VITE_FEATURE_SUPABASE=true
VITE_KIBO_TENANT_ID=ca61f0e5-563e-5894-954f-38f5a9e0eabc
```

**Supabase secrets needed (in Supabase vault for Edge Functions):**
- `OPENAI_API_KEY` — For embedding generation in `insert-pointer` and LLM naming in `compute-forest`

### Project structure (final)

```
src/
  lib/
    supabase.js              — Supabase client (null-safe)
    forestAdapter.js         — Supabase → TREES shape transformer
  hooks/
    useForestScene.js        — Three.js scene (parameterized)
    useForestData.js         — Supabase data fetcher with static fallback
    usePointerMutation.js    — Insert pointer + resolve duplicates
    useQueryPathLogger.js    — Navigation session logging
  components/
    InfoPanel.jsx            — Pointer detail (prop-based branchIndex)
    InstanceBrowser.jsx      — Tree browser (prop-based trees)
    InsertPanel.jsx          — Pointer creation form
    DuplicatePanel.jsx       — Duplicate resolution modal
    SearchPanel.jsx          — Fuzzy search
    StatsPanel.jsx           — Dedup threshold stats
    StructureEvolutionAlert.jsx — Forest evolution banner
    HousePanel.jsx           — House detail (unchanged)
    TablePanel.jsx           — DB table browser (unchanged)
    Legend.jsx               — Controls legend (unchanged)
    ProjectionDemo.jsx       — Projection demo (unchanged)
  scene/
    buildScene.js            — Three.js builder (parameterized)
  data/
    trees.js                 — Static fallback + geometry constants
  App.jsx                    — Root component (all wiring)
  App.css                    — Styles
  main.jsx                   — React root
docs/
  handovers/                 — Phase A-G handover documents
  audits/                    — Phase A-F audit reports
```

### Supabase project summary

- **Project**: KnowledgeForest (`rkuyvzcxaoulhjiflrmp`)
- **Region**: eu-central-1
- **Tables**: 18 (all with RLS)
- **Extensions**: pg_trgm, vector (pgvector), moddatetime, uuid-ossp
- **Edge Functions**: 4 (insert-pointer, link-pointers, log-query-path, compute-forest)
- **RPC Functions**: 9 (check_duplicates, insert_pointer_with_dedup, get_pointer_subgraph, get_tenant_forest, upsert_coaccess_batch, update_coaccess_cursor, recompute_dedup_thresholds, seed_tenant_from_template, get_dedup_stats)
- **Seed data**: 58 pointers, 93 edges, 75 attributes, 1 tenant (Kibo), 13 trees, 58 branches

## End-to-end verification checklist

### Build & Deploy
- [ ] `npx vite build` succeeds (92 modules, no errors)
- [ ] Vercel env vars configured
- [ ] OpenAI API key in Supabase vault

### Feature flag OFF (regression)
- [ ] Set `VITE_FEATURE_SUPABASE=false`, run `npx vite --open`
- [ ] 3D forest renders with 13 trees (identical to original PoC)
- [ ] Hover, click, focus mode, cross-links all work
- [ ] InstanceBrowser shows all branches
- [ ] InfoPanel shows properties and links

### Feature flag ON (Supabase)
- [ ] Set `VITE_FEATURE_SUPABASE=true`, run `npx vite --open`
- [ ] 3D forest renders from Supabase (13 trees, matching positions)
- [ ] All interactions work (hover, click, focus, cross-links)

### Insert flow
- [ ] Click "+ Insert" → form appears
- [ ] Insert "TestCompany" as company → green "Created" banner
- [ ] Insert "TestCmpany" (typo) → red "Potential duplicates" banner
- [ ] Click "Review" → DuplicatePanel shows match with similarity score
- [ ] Click "Keep Both" → panel closes, forest refreshes

### Search flow
- [ ] Click "Search" → search panel appears
- [ ] Type "NVIDIA" → results appear after debounce
- [ ] Click result → InfoPanel opens (if pointer is in branchIndex)

### Stats panel
- [ ] Click "Stats" → shows thresholds (80%/40%)
- [ ] Shows "50 more" until adaptive
- [ ] All counters at 0 initially

### Path logging (requires browser dev tools)
- [ ] Click 3+ branches in sequence
- [ ] Wait 30 seconds
- [ ] Check `query_paths` table → row with correct pointer_ids
- [ ] Check `tenant_coaccess` → pairs with weights > 0

### Structure evolution (manual)
- [ ] Insert test event via SQL
- [ ] Banner appears: "Your forest has evolved"
- [ ] Click "Refresh" → forest reloads
- [ ] Click "Dismiss" → banner disappears

### Cold start (API test)
```sql
INSERT INTO tenants (id, name) VALUES (gen_random_uuid(), 'NewTenant') RETURNING id;
-- Then:
SELECT seed_tenant_from_template('<new-tenant-id>', 'ca61f0e5-563e-5894-954f-38f5a9e0eabc');
-- Verify: 13 trees, 58 branches copied
```

### Performance
- [ ] `get_tenant_forest` < 200ms (check via Supabase dashboard)
- [ ] Build size < 1MB gzip (current: ~259KB gzip)
- [ ] Scene renders at 60fps (check via browser DevTools Performance tab)

## What's NOT in the MVP (deferred)

| Feature | Status | Notes |
|---------|--------|-------|
| Embeddings in seed data | Deferred | Pointers have NULL embeddings. Backfill via insert-pointer or script. |
| Automatic compute-forest trigger | Deferred | Threshold check enqueues a job but nothing auto-invokes the Edge Function. Needs cron. |
| Leiden/Louvain clustering | Deferred | MVP uses union-find. Same data flow, just swap the algorithm. |
| Force-directed tree layout | Deferred | MVP uses circular layout. |
| Auth UI | Deferred | MVP uses anon key for reads. |
| Role-based RLS per tenant | Deferred | All authenticated users see everything. |
| Link creation UI | Deferred | `link-pointers` Edge Function exists but no frontend. |
| Embedding-based search | Deferred | Search uses ilike only. |
