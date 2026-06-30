# Nzyme SharePoint skeleton ingestion — HANDOVER S1 (dry-run validated)

Date: 2026-06-30
Runner: `scripts/kf_ingest_nzyme.py` (new; mirrors the proven Kibo runner
`scripts/kf_ingest_sharepoint.py`, which was NOT modified). The skeleton adapter
`pipeline/pipeline/adapters/sharepoint_skeleton.py` was NOT modified — the
Nzyme-specific reconciliation lives entirely in the runner.

## What the script does
1. **Enumerate** the Nzyme `Documentos` library (drive_id
   `b!jyI-HlHR8kGKZaI-n2Pqz3gUEPtDslVBvlZD2P8BTrv3fQa9hf-OSrCGbCegojsN`).
   Reuses the cache at `/tmp/nzyme_drive.json` (34,798 items) if present; else
   enumerates via Graph delta and saves. `--cache` overrides the path.
2. **Slice** to items whose `sp_path` equals a root or starts with `root + "/"`,
   for `ROOTS = ["04_Dealflow", "05_Portfolio"]` → 22,109 items.
3. **Skeleton build** via `sk.build_skeleton(... drive_name="Documentos",
   acl_principal=NZYME_TENANT, resolve_company=lambda n: None,
   resolve_fund=lambda n: None)`. The None resolvers guarantee NO Kibo-style
   entity edges (Nzyme paths don't match `portfolio_context` anyway). Produces
   body-less `folder`/`document` pointers + hierarchy edges (`documents_of` for
   files, `folder_of` for folders). `drive_name="Documentos"` ⇒
   `metadata.library == "Documentos"`, isolating Nzyme rows.
   - Pointer key scheme: `msgraph:{AZURE_TENANT_ID}:drive/{drive_id}/item/{item_id}`.
   - ACL principal = `NZYME_TENANT = baa52eca-4c88-4861-9d45-720e743febb4`.
4. **Reconciliation pass** (runner-only, additive `EdgeSpec`s appended to
   `plan.edges`); skipped with `--no-reconcile`:
   - Entity index: PostgREST GET `/rest/v1/pointers` for `type=opportunity` then
     `type=company`, filtered `acl=cs.{baa52eca-...}`, paginated. Keyed
     `normalize(label) -> [(canonical_key, type), ...]` (list — an opportunity AND
     a company can share a normalized label). Index size: **396 opportunity + 334
     company** pointers.
   - Entity-folder selection (verified path levels):
     - **Dealflow deal folders** = folders exactly 3 segments deep under
       `04_Dealflow/01_Open opportunities/` or
       `04_Dealflow/02_Discarded and lost opportunities/`.
     - **Portfolio company folders** = folders exactly 2 segments deep under
       `05_Portfolio/`, EXCLUDING names whose lowercase is in
       `{"z_folder structure", "01_recruiting for portcos"}` and any name matching
       `^(z_|a_|b_|0\d_)` (case-insensitive).
   - Name → match variants: from each folder name, strip in combination a leading
     date prefix `^\s*\d{4}\s*\d{0,2}\s*[_ ]\s*`, a generic numeric prefix
     `^\s*\d+\s*[_.\-)]\s*`, a trailing parenthetical `\s*\([^)]*\)\s*$`, and a
     trailing `_pt$` (case-insensitive). A folder matches if ANY variant's
     `normalize()` is in the index.
   - For each matched folder × each matched entity, append
     `EdgeSpec(folder_key, entity_key, "folder_of",
     why="opportunity_documents" if type==opportunity else "company_documents")`.

## Exact CLI
```
# Dry-run (no writes; reconciliation ON):
pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py --dry-run

# Dry-run, skeleton/hierarchy only:
pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py --dry-run --no-reconcile
```
Flags: `--dry-run` (build + print plan + full match list + unmatched list, no
writes), `--no-reconcile` (skeleton + hierarchy only), `--cache PATH` (default
`/tmp/nzyme_drive.json`), `--verbose`.

## Dry-run output (reconciliation ON)
```
matched 22109 drive items under ['04_Dealflow', '05_Portfolio']
entity index: 396 opportunity + 334 company pointers (Nzyme tenant)
[dry-run] pointers: 22109  (4478 folder, 17631 document)
[dry-run] edges:    22217
            documents_of   17631
            folder_of      4586
[dry-run] per-root pointer counts:
  04_Dealflow      10677  (2507 folder, 8170 document)
  05_Portfolio     11432  (1971 folder, 9461 document)
[dry-run] reconciliation: 72 folders matched -> 110 edges
                          (66 opportunity_documents, 44 company_documents)
```
`--no-reconcile` dry-run: 22,109 pointers; 22,107 edges (17,631 documents_of +
4,476 folder_of). `folder_of` math: 4,478 folders − 2 roots = 4,476 hierarchy
edges; +110 reconciliation edges = 4,586 in the reconcile-on run.

### Reconciliation match summary (72 folders → 110 edges)
Spot-checks confirmed: `2026 06_Bip&Drive` → opportunity Bip&Drive + company
bipdrive.com; `Azenea` → opportunity Azenea; `White Vega` → opportunity + company
whitevega.com; `2026 03_Orgoa (Project Onyx)` and `202404_Orgoa` both → company
orgoa.es. 26 entity-folders unmatched (e.g. code-named projects with no entity:
`Project Fleming`, `DEH (Project Delta)`, `2026 06 Digital Bridge`,
`Clinicas López-Ibor`, plus the structural `Z_Folder structure`). Unmatched
folders still get pointers + hierarchy edges; they just carry no entity link.

## Deviation from expected numbers
Spec expected ~80 folders matched / ~109 edges (~66 opportunity + ~43 company).
Actual: **72 folders / 110 edges (66 opportunity + 44 company)**. Opportunity
count is exact; company is 44 vs ~43 (one extra); total 110 vs ~109. Folder count
72 vs ~80 — the "~80" was approximate; 72 is the count after applying the verified
3-seg/2-seg selection and exclusion rules against the current cache. All
within stated tolerance ("small drift OK if SharePoint changed"). Per-root pointer
counts match the spec exactly.

## Next steps
- **S2 — skeleton + hierarchy only (real write):**
  ```
  pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py --no-reconcile
  ```
  Bulk-inserts ~22,109 pointers (skip-if-exists by canonical_key) + ~22,107
  hierarchy edges (link_pointers, concurrency 16, 409 == idempotent skip).
- **S4 — reconciliation on (real write):**
  ```
  pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py
  ```
  Re-runs idempotently (pointers already present), then adds the ~110
  reconciliation edges. Existing edges 409 and are skipped.

## Notes / gotchas
- **Embeddings/search_text are NULL** on bulk-inserted rows. The runner uses a
  direct PostgREST bulk INSERT (not `insert_pointer_with_dedup`, whose per-item
  vector-similarity search does not scale to ~22k rows). Backfill embeddings
  separately (option A) if semantic search over the skeleton is needed.
- Reconciliation edges are `folder_of` (same relationship_type as hierarchy
  edges) but distinguished by `why` (`opportunity_documents` / `company_documents`
  vs `sp_hierarchy`).
- Idempotency: pointers keyed on exact `canonical_key` (stable item_id); edges
  treated idempotent on 409. Safe to re-run any step.
- `metadata.library == "Documentos"` is the isolation key separating Nzyme rows
  from Kibo (`Kibo_Ventures`) skeleton rows.
```
