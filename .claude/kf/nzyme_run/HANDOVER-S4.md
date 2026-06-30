# HANDOVER-S4 — Nzyme reconciliation edges (folder → opportunity/company)

Date: 2026-06-30 · Prod `sjiepibqadbdowcizccw` · Run by orchestrator.
Command: `pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py` (reconcile ON).

## Bug found & fixed before this succeeded
The FIRST attempt crashed in the pointer phase: `_fetch_existing_skeleton_ids` used PostgREST
`offset` pagination **without `ORDER BY`**, so across ~52k skeleton rows (Kibo+Nzyme) it
under-counted existing keys ("8768 already present") and tried to re-insert 13,341 existing
pointers → 409 against the `UNIQUE INDEX idx_pointers_canonical_key`. No data corrupted (unique
index blocked dupes; crash was before the edge phase, 0 edges written). Fixes in
`scripts/kf_ingest_nzyme.py`: (1) added `order=canonical_key` to the existing-keys fetch;
(2) `_bulk_insert` now posts with `on_conflict=canonical_key` + `Prefer:
resolution=ignore-duplicates` so a stale fetch can never 409 again. (Note: the plan assumed no
unique index — there IS one; it is protective.)

## What changed (successful re-run)
- pointers: inserted=0, already_present=22109, errors=0
- edges: **created=110**, already_exists=22107 (hierarchy 409-skip), unresolved=0

## Verify (DD-S4, all PASS)
- reconciliation edges: **66 opportunity_documents→opportunity + 44 company_documents→company = 110**
- unresolved=0 → every reconciliation edge resolves to an existing entity
- Targets respect S3: Nzyme-exclusive companies linked via new keys
  (`2025 10_Arjile`→`baa52eca::arjile.co`, `Bip&Drive`→`baa52eca::bipdrive.com`); shared companies
  via preserved keys (`Civislend`,`White Vega`→`ca61f0e5::…`).
- Idempotent: a re-run 409-skips all 22,217 edges (created=0).

## Notes
~26 entity-folders intentionally unmatched (bare codenames / near-spellings) — skeleton only, see
plan Appendix B + the `NZYME_ALIAS` follow-up.
