# Handover — ingest an MVP skeleton for a Nzyme sublibrary

How the Kibo `02_Portfolio` SharePoint skeleton was built & loaded, generalized so you
can do an MVP for **one sublibrary of the Nzyme library**. Read alongside the design
plan `.claude/kf/SHAREPOINT_SKELETON_PLAN.md` and `handover-S3.md` (full Kibo load).

## What "skeleton" means (recap)
Mirror SharePoint **structure**, not contents. Every folder → `folder` pointer, every
file → `document` pointer, **empty body**. One pointer per item so each can carry its
own acl and be queried/traversed. Bytes fetched on demand later via
`GET /drives/{driveId}/items/{itemId}/content` (derivable from the key — nothing stored).

## Reusable assets (already built, already in prod)
- **Graph client** `pipeline/pipeline/adapters/sharepoint.py` (`find_sites`,
  `list_drives`, `enumerate_drive` [Graph delta, dedups by id], `traverse_folder`).
  Run with `pipeline/.venv/bin/python` (has msal/requests). Shim: `scripts/sharepoint_client.py`.
- **Skeleton adapter** `pipeline/pipeline/adapters/sharepoint_skeleton.py`
  (`build_skeleton`, `item_key`, `portfolio_context`). Produces pointers + `folder_of`/
  `documents_of` edges.
- **Runner** `scripts/kf_ingest_sharepoint.py` (bulk-insert pointers, concurrent edges).
  ⚠️ Currently **hardcoded to Kibo** — see "What to change" below.
- **Migration** `20260629140000_add_folder_pointer_type.sql` — `folder` enum +
  `folder`/`folder_of`/`documents_of` vocab rows. **Already applied to prod — do NOT
  re-add.** No migration needed for Nzyme.

## Nzyme facts (verified 2026-06-30)
- Site: **"Nzyme"** → `https://kiboventures.sharepoint.com/sites/Nzyme`.
- One document library: **"Documentos"**. Its 16 top-level folders (candidate
  sublibraries): `00_Confidential - MDs RRR`, `00_MDs`, `01_Admin`, `02_Marketing`,
  `03_1_Fundraising`, `03_2_ Investor Relations`, `04_Dealflow`, `05_Portfolio`,
  `06_Market_intelligence`, `07_Value Creation Playbook`, `07b_VC Management`,
  `08_Partnerships & Ambassadors`, `09_Personales`, `JCV`, `PruebaNzymeNoTocar`
  (test folder — skip), `ZZ_Ordenar`.
- **Entra tenant (canonical key)**: SAME as Kibo — `6e409d59-0cb2-468a-8cbc-a1b48ab0f949`
  (both sites are on `kiboventures.sharepoint.com`). Key scheme unchanged:
  `msgraph:{entraTenant}:drive/{driveId}/item/{itemId}`.
- **acl tenant (Nzyme)**: `baa52eca-4c88-4861-9d45-720e743febb4` (= `NZYME_TENANT`,
  see `pipeline/pipeline/mcp_server/tenant_map.py`). **Different from Kibo's `ca61f0e5…`** —
  use the Nzyme one so Nzyme RLS gates these.
- Supabase project (KnowledgeForest): `sjiepibqadbdowcizccw`.

## MVP scope (keep it small)
Ingest the folder/file skeleton of **one** chosen sublibrary (e.g. `04_Dealflow`) as
pointers + hierarchy edges. **Drop entity reconciliation** — Nzyme has no
fund/company folder convention like Kibo's portfolio, so there is nothing to link to
yet. (If you pick `05_Portfolio` and it has company folders, reconciliation can be
added later, same pattern as Kibo.)

## How I proceeded — the method + the gotchas that cost time
1. **Enumerate.** For Kibo I used `enumerate_drive` (whole-drive Graph delta, ~150k
   items, ~2 min) and cached to `/tmp/kibo_drive.json`. For an MVP sublibrary, prefer
   `traverse_folder(site_url, "Documentos/04_Dealflow")` — it walks just that subtree
   (fast), and returns the SAME item dict shape (`id, name, type, sp_path, parent_id,
   webUrl, size, lastModifiedDateTime`). NOTE: `traverse_folder`'s `sp_path` is relative
   to the folder you start from; prepend the base if you want full paths in labels.
2. **Build pointers + edges** via `build_skeleton`. Key per item (folders included).
   Edges point UP: file `documents_of` parent, folder `folder_of` parent.
3. **Insert — use a BULK INSERT, never the dedup path.** The big lesson: the
   `ingest-batch → insert_pointer_with_dedup` path runs a per-item **vector-similarity
   search** over the whole pointer table. It does NOT scale — it decelerates as the
   table grows and times out (the Kibo full run CRASHED at 11.6k/30k after 85 timeouts).
   The skeleton only needs **exact canonical_key identity**, so that search is pure
   overhead. The runner now does a direct PostgREST **bulk INSERT**.
4. **Idempotency without a unique constraint.** There is **NO unique index on
   `canonical_key`** (dedup is RPC-logic only), so a blind upsert/`ON CONFLICT` is not
   available and a blind re-insert would duplicate. The runner fetches existing keys
   first and **inserts only the missing ones**. Re-runs are then no-ops.
5. **Edges are concurrent + 409-tolerant.** `link-pointers` returns **HTTP 409** when an
   edge already exists — treat as idempotent skip (do NOT crash). Serial edge creation
   does not scale (~30k edges); the runner uses an `asyncio.Semaphore` (≈16).
6. **Verification must use SQL `GROUP BY` or keyset pagination — NEVER PostgREST
   `offset` without `ORDER BY`.** Offset pagination returns overlapping/skipped rows and
   produced a totally false "8,288 duplicates" alarm; SQL/keyset showed 0. See
   `handover-dedup-check.md`.
7. Minor: Python **block-buffers stdout to a file**, so progress lines don't appear
   until flush/exit — check progress via a DB count instead. `schema_vocabulary.category`
   is constrained to `{pointer_type, edge_type, attribute_key}` (no `convention`).

## Steps to build the Nzyme MVP
### A. Generalize the runner (it's Kibo-hardcoded)
In `scripts/kf_ingest_sharepoint.py` the constants `SITE_NAME="Kibo Ventures"`,
`LIBRARY="Kibo_Ventures"`, `PORTFOLIO_ROOT="02_Portfolio"`, `ACL_KIBO_TENANT=…` and the
`--company`/`slice_items`/reconciliation wiring are Kibo-specific. Make them
parameters (recommended) or copy to a thin `kf_ingest_nzyme.py`:
- `--site "Nzyme"`, `--library "Documentos"`, `--root "04_Dealflow"`, `--acl baa52eca-…`.
- Add a `--no-reconcile` mode that passes `resolve_company=lambda n: None` and
  `resolve_fund=lambda n: None` to `build_skeleton` (so no entity edges are attempted)
  — or just accept that `portfolio_context` won't match Nzyme paths (its
  `FUND_FOLDER_MAP`/company regex are Kibo-portfolio-specific, so `is_fund_folder`/
  `is_company_folder` are False → no reconciliation edges, which is the MVP goal).
- Set every pointer's `principals=[NZYME_TENANT]` (`baa52eca-…`).
- The pointers keep `metadata.source="sharepoint_skeleton"` and
  `metadata.library="Documentos"` — filter Nzyme rows by `metadata->>'library'='Documentos'`
  (Kibo's is `Kibo_Ventures`, so the two never collide).
- Label fallback: with no portfolio context, `build_skeleton` labels items by their
  path (`📁 04_Dealflow › …`). Fine for MVP; improve later if desired.

### B. Run it (sample-first)
1. Dry-run to see scope + the pointer/edge plan (no writes):
   `pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py --root "04_Dealflow" --dry-run`
2. Real run (bulk insert + edges):
   `pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py --root "04_Dealflow"`
   Re-run = idempotent (inserts 0, edges 409-skip).

### C. Verify (authoritative SQL, MCP `execute_sql` on `sjiepibqadbdowcizccw`)
Isolate Nzyme rows with `metadata->>'library'='Documentos'` (add the root folder
filter if other Nzyme sublibraries get loaded later):
```sql
-- counts: compare to the dry-run's source counts
select count(*) total, count(distinct canonical_key) distinct_keys,
       count(*) filter (where type='folder') folders,
       count(*) filter (where type='document') docs
from pointers where metadata->>'library'='Documentos';
-- duplicates (expect 0)
select canonical_key, count(*) n from pointers where metadata->>'library'='Documentos'
group by 1 having count(*)>1;
-- acl == Nzyme tenant (expect 0 wrong)
select count(*) from pointers where metadata->>'library'='Documentos'
  and acl is distinct from array['baa52eca-4c88-4861-9d45-720e743febb4']::uuid[];
-- edge types from these sources
select e.relationship_type, count(*) from edges e
  join pointers p on p.id=e.source_id and p.metadata->>'library'='Documentos'
  group by 1;
-- orphans (expect just the sublibrary root, like 02_Portfolio was for Kibo)
select label from pointers p where p.metadata->>'library'='Documentos'
  and not exists (select 1 from edges e where e.source_id=p.id);
```
PASS = total == source dry-run count, 0 duplicates, 0 wrong acl, `documents_of`==#files,
`folder_of`==#folders − roots, only the chosen root has no outgoing edge.

## Carry-over open items (from the Kibo load — relevant if you scale Nzyme)
- **Embeddings/search_text are NULL** on bulk-inserted rows → semantic/FTS search won't
  find skeleton nodes until a backfill pass. Graph traversal + exact-label work.
- Consider a `query-knowledge` planner hint for `folder_of`/`documents_of` (so
  "documents of X" traverses the skeleton) — vocab rows already exist.
- Optional DB guard: unique index on `pointers(canonical_key) where canonical_key is not null`
  to make duplicate keys impossible (verify zero existing dups across the whole table first).
