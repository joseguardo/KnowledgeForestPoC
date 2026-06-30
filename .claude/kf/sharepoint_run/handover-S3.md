# Handover — S3 (full 02_Portfolio ingestion) — DONE & VERIFIED

Date: 2026-06-29. Continues `handover-S1.md`. Plan: `.claude/kf/SHAREPOINT_SKELETON_PLAN.md`.

## What this stage did
Ingested the ENTIRE `02_Portfolio` subtree of the Kibo_Ventures library into prod
(`sjiepibqadbdowcizccw`): 30,340 pointers (7,994 folder + 22,346 document) + ~30,378
edges (22,346 documents_of + 8,032 folder_of). 0 errors, 0 timeouts.

## MAJOR change: pointer phase rewritten to a bulk insert
The dedup path (`ingest-batch` -> `insert_pointer_with_dedup`) **does not scale**: it
runs a per-item vector-similarity search over the whole pointer table, which
decelerates as the table grows and times out. A first full attempt CRASHED at ~11.6k
pointers after 85 timeouts (`EdgeFunctionTimeout`).

Fix (in `scripts/kf_ingest_sharepoint.py`, `run_ingest`): pointers now go in via a
direct PostgREST **bulk INSERT** keyed on the exact canonical_key:
- `_fetch_existing_skeleton_ids()` pages all existing `metadata->>source=sharepoint_skeleton`
  (canonical_key -> id), so we **insert only missing** rows (idempotent WITHOUT a unique
  constraint — there is NO unique index on canonical_key; dedup is RPC-logic only).
- `_bulk_insert()` POSTs in chunks of 500 with `Prefer: return=representation`.
- Edges unchanged: concurrent `link-pointers` (sem=16), 409 == already-exists -> skip.
- Result: full 30k load in ~1 min pointers + ~10 min edges, vs the old path failing at
  40 min / 38%.

Consequence: bulk-inserted pointers have **null embedding and null search_text** (the
RPC used to set these). 18,681 rows need backfill; the 11,659 from the crashed RPC run
already have embeddings.

## Verified (DD via REST — MCP SQL was auth-blocked this session)
- 30,340 pointers = 7,994 folder + 22,346 document (matches source tree exactly).
- 30,340/30,340 keys well-formed `msgraph:6e409d59-…:drive/{driveId}/item/{itemId}`.
- acl = `['ca61f0e5-…']` on all 30,340; 0 mismatches.
- Edges: documents_of=22,346 (one per file -> no file orphan/dup), folder_of=8,032.
- No dangling edges (loader unresolved=0), no errors.
- Idempotent by construction (insert-only-missing + edge 409-skip); proven on Carto re-run.

## Remaining follow-ups
1. **Embedding + search_text backfill** for the 18,681 null rows (option A). Needs a
   batch OpenAI embedding pass + `update pointers set embedding=…, search_text=to_tsvector('english',label)`.
   Until done, semantic/FTS search won't find skeleton nodes; graph + exact-label work.
2. **query-knowledge planner hint** (S2a) — add a folder_of/documents_of traversal note
   to schemaContextFor so "documents of <company>" reliably walks the skeleton. Vocab
   rows (folder/folder_of/documents_of) already exist; prose hint still pending.
3. **~7 unresolved companies** (Clarity, DefinedCrowd, Job and Talent, Mitiga, Tappx,
   Tier, Worldsensing): folders exist, no folder_of->entity link. Populate
   `COMPANY_ALIAS` in `pipeline/pipeline/adapters/sharepoint_skeleton.py` + idempotent re-run.
4. **Fund I** has no fund pointer (folders unlinked) — create one if desired.
5. Full-site (beyond 02_Portfolio) + delta sync (deltaLink + tombstones) — future.

## How to re-verify / re-run
`pipeline/.venv/bin/python scripts/kf_ingest_sharepoint.py --cache /tmp/kibo_drive.json`
(idempotent: re-run inserts 0, edges all already_exist). REST DD: count pointers with
`metadata->>source=eq.sharepoint_skeleton` (expect 30,340) and edges by relationship_type.
