# Handover — S0 (migration) + S1 (Carto sample) — DONE & VERIFIED

Date: 2026-06-29. For a clean-context thread continuing the SharePoint skeleton
ingestion. Plan: `.claude/kf/SHAREPOINT_SKELETON_PLAN.md`.

## What this stage did
- **S0 — applied to KnowledgeForest prod (`sjiepibqadbdowcizccw`):**
  - `alter type public.pointer_type add value 'folder'`
  - `schema_vocabulary` rows: `folder` (pointer_type), `folder_of` + `documents_of`
    (edge_type). NOTE: `schema_vocabulary.category` is constrained to
    `pointer_type | edge_type | attribute_key` — a `convention` category fails.
    The committed migration file was corrected to use edge_type rows.
- **S1 — ingested only the Carto company** (both `021 - CARTO` under Fondo I and
  `007 - Carto` under Opportunity Fund) via
  `pipeline/.venv/bin/python scripts/kf_ingest_sharepoint.py --company Carto --cache /tmp/kibo_drive.json`.

## Data-structure changes (for coherency checks)
- New pointer type `folder`; files use existing `document` type. Bodies empty.
- canonical_key: `msgraph:{entraTenant=6e409d59-0cb2-468a-8cbc-a1b48ab0f949}:drive/{driveId}/item/{itemId}`.
- New edge types: `folder_of` (folder→parent folder, and company/fund folder→entity),
  `documents_of` (file→parent folder). Edges live in table `edges` (source_id,
  target_id, relationship_type).
- acl on every skeleton pointer: `['ca61f0e5-563e-5894-954f-38f5a9e0eabc']` (Kibo tenant).
- metadata keys: source=sharepoint_skeleton, drive_id, item_id, library, name,
  sp_path, web_url, size, last_modified, fund_folder, company, is_folder.

## Verified counts (DD suite PASSED — all green)
- 454 pointers = 112 folder + 342 document; keys 454/454 well-formed & unique.
- 454 edges = 112 folder_of + 342 documents_of; 0 orphans, 0 dangling.
- Reconciliation: both Carto company folders → `company::…::naluat:carto` (2 edges).
- acl = Kibo tenant on all 454.
- **Idempotency: re-ran twice → still exactly 454/454, runner reports
  `created=0 merged=454` / `edges already_exists=454`.** No duplicates.

## Findings
1. **Idempotency bug (FIXED).** `link-pointers` returns HTTP 409 on an existing edge
   ([supabase/functions/link-pointers/index.ts:86](../../../supabase/functions/link-pointers/index.ts#L86)).
   The runner treated 409 as fatal and crashed on re-run. Fixed in
   `scripts/kf_ingest_sharepoint.py` (edge loop now treats 409 as idempotent skip).
   Data was always safe — the 409 is what prevents duplicate edges.
2. **Edge phase is slow & serial (OPEN — must fix before S3).** The runner issues
   one `link-pointers` call per edge, sequentially; re-runs round-trip every existing
   edge (occasional timeout+retry). Fine for 454; for full `02_Portfolio` (~30k
   edges) it's too slow. Add bounded async concurrency to the edge phase (and ideally
   skip edges already present) before scaling.

## How to re-verify
Use the S1 DD prompt (in the plan / chat). Key SQL isolates Carto with
`metadata->>'source'='sharepoint_skeleton' and lower(metadata->>'company')='carto'`.
Idempotency re-run: re-execute the loader command above; expect `created=0 merged=454`.

## Next (S2)
- **S2a (parallel, no data dep):** update kf-ingest/kf-query/kf-schema skill docs AND
  add a `folder_of`/`documents_of` traversal hint to `query-knowledge` schemaContextFor
  (so the planner reaches documents from a company/fund entity). Vocab rows already
  added in S0 give the planner the edge names; the prose hint makes traversal reliable.
- **S2b:** load one full fund (Fund III) — depends on this S1 PASS. Apply the edge
  concurrency fix first if loading many companies.
