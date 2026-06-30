# HANDOVER-S2 — Nzyme skeleton ingest (pointers + hierarchy)

Date: 2026-06-30 · Prod `sjiepibqadbdowcizccw` · Run by orchestrator.
Command: `pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py --no-reconcile`

## What changed
Bulk-inserted the `04_Dealflow` + `05_Portfolio` skeleton and its hierarchy edges. NO entity
reconciliation (that is S4). All rows carry `acl=[baa52eca…]`, `metadata.source=sharepoint_skeleton`,
`metadata.library=Documentos` (isolates Nzyme from Kibo's `Kibo_Ventures`). Embeddings/search_text NULL.

## Run output
- pointers: **inserted=22109**, already_present=0, errors=0
- edges: **created=22107**, already_exists=0, unresolved=0

## Verify (DD-S2, all PASS)
- total=22109, distinct_keys=22109, folders=4478, docs=17631
- wrong_acl=0, dup_keys=0
- `documents_of`(sp_hierarchy)=17631 (==#files); `folder_of`(sp_hierarchy)=4476 (==#folders−2 roots)
- orphans = exactly the 2 roots (`04_Dealflow`, `05_Portfolio`)

## Idempotency
Re-running `--no-reconcile` inserts 0 (all keys present) and 409-skips all 22,107 edges.

## Next
S4 = `pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py` (reconcile ON). It re-attempts the 22,107
hierarchy edges (all 409-skip) and adds ~110 reconciliation `folder_of` edges. The reconciliation
index is fetched live, so it targets the **post-S3** company keys (305 Nzyme-keyed + 29 shared).
