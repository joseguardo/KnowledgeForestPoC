# HANDOVER-MASTER — Nzyme SharePoint skeleton + company re-namespacing (COMPLETE)

Date: 2026-06-30 · Prod `sjiepibqadbdowcizccw`. All steps DD-green. This summarizes every
data-structure change for a clean-context follow-up thread.

## What was done
1. **SharePoint skeleton** for Nzyme `04_Dealflow` + `05_Portfolio` (site "Nzyme", library
   "Documentos") → 22,109 body-less pointers (4,478 `folder` + 17,631 `document`) +
   22,107 hierarchy edges (`documents_of`/`folder_of`, why=`sp_hierarchy`).
2. **Company re-namespacing**: 305 Nzyme-exclusive Affinidad companies re-keyed
   `company::ca61f0e5-…` → `company::baa52eca-…` (the 29 genuinely-shared companies kept their
   shared Kibo key). Adapter fixed so future syncs key Nzyme-owned companies under Nzyme.
3. **Reconciliation**: 110 `folder_of` edges (66 why=`opportunity_documents`→opportunity,
   44 why=`company_documents`→company) linking deal/portfolio folders to their entities.

## Data-structure changes (for coherency / future DD)
- `pointers`: +22,109 rows. Filter Nzyme skeleton with `metadata->>'library'='Documentos'`
  (Kibo skeleton uses `Kibo_Ventures`). acl=`[baa52eca…]`, source=`sharepoint_skeleton`.
  Canonical key: `msgraph:{AZURE_TENANT_ID}:drive/{driveId}/item/{itemId}`. Embeddings/search_text
  are **NULL** (graph + exact-label only; semantic/FTS needs a backfill).
- `pointers` (companies): 305 canonical_key rewrites (tenant segment only; ids unchanged).
- `edges`: +22,217 (id-FK; the key rewrite did not touch them). `folder_of`/`documents_of` vocab
  already existed (migration `20260629140000`). 409 = idempotent skip throughout.
- **UNIQUE INDEX `idx_pointers_canonical_key`** (partial, canonical_key not null) EXISTS — the
  plan wrongly assumed none. It is protective (no dup keys possible).
- Code: `pipeline/pipeline/adapters/affinidad.py` + new `affinidad_nzyme_owned.py` (allowlist;
  `TODO(ownership-signal)` to replace with a `crm_list_entries→crm_lists` join). 27 tests pass.
- `scripts/kf_ingest_nzyme.py` (new). NOTE the idempotency fix: existing-keys fetch now uses
  `order=canonical_key` and `_bulk_insert` uses `on_conflict=canonical_key`+ignore-duplicates.

## Final coherency (S5) — all PASS
0 global dup keys · 0 dangling edges · 22,109 Nzyme pointers · 22,217 Nzyme edges ·
0 reconciliation edges with bad target · 0 Nzyme-only companies still Kibo-keyed.

## Re-run safety
`kf_ingest_nzyme.py` is fully idempotent (0 pointer inserts, all edges 409-skip). The S3 SQL is
guarded (`LIKE 'company::ca61f0e5-%'`). The adapter upserts onto re-namespaced rows.

## Open follow-ups (out of scope)
- Backfill embeddings/search_text for the 22,109 skeleton rows.
- Replace the Nzyme-owned allowlist with the real CRM list-membership join (`TODO(ownership-signal)`).
- `NZYME_ALIAS` for ~26 unmatched deal folders (codenames / near-spellings: `Arbio`→"Arbio Group",
  `Bango`, `Bosquia Nature`→"Bosquia", `Project Vesta/Fleming/Thomson`, `WGI`, `Fontiber`, …).
- Pre-existing CRM source dupes (`bdeo.cio`/`bdeo.io`, `Room007Hostels`×2, `Union/Unión Financiera`).
- Optional `query-knowledge` planner hint for `folder_of`/`documents_of` ("documents of X").
