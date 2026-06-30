# SharePoint Skeleton → KnowledgeForest — Implementation Plan

## Context / goal
Mirror the **structure** (not the contents) of the Kibo Ventures SharePoint into the
graph: every folder and every file becomes its own pointer with an **empty body**.
This minimises processing/storage and outsources dedup/versioning to SharePoint. A
pointer-per-item lets us set **access classes per file/folder**, query folders and
documents directly, and traverse the hierarchy. Bodies are fetched on demand later
via `GET /drives/{driveId}/items/{itemId}/content` (derivable from the key — see §3).

First target: the `02_Portfolio/` subtree of the **Kibo_Ventures** library
(7,994 folders + 22,346 files). **Sample-first**: load one company before the bulk.

## 1. Migration — add the `folder` pointer type
Mirror [20260629130000_add_fund_pointer_type.sql](../../supabase/migrations/20260629130000_add_fund_pointer_type.sql):
- `alter type public.pointer_type add value if not exists 'folder';`
- Insert `schema_vocabulary` rows describing the skeleton convention so agents/skills
  understand it:
  - `folder` — "A SharePoint/OneDrive folder mirrored as a structure node. Body-less.
    Children link via `contained_in`. May link to a domain entity (company/fund) via
    `about`."
  - Extend the `document` description — "When body-less with a `msgraph:` canonical_key,
    it is a SharePoint file mirror (skeleton); fetch contents on demand from Graph."
- `document` already exists in the enum — no change there.
- Add `"folder"` to `VALID_POINTER_TYPES` in
  [structured.py:6](../../pipeline/pipeline/adapters/structured.py#L6).

## 2. New adapter — `pipeline/pipeline/adapters/sharepoint_skeleton.py`
Sits beside the Graph client ([adapters/sharepoint.py](../../pipeline/pipeline/adapters/sharepoint.py)).
Consumes `SharePointClient.enumerate_drive()` output (id, name, type, sp_path,
parent_id, webUrl, size, lastModifiedDateTime) + `driveId` + `tenantId`, and produces
pointers + edges (same `EdgeSpec` shape Naluat uses).

### Canonical key (every item, folders included)
```
msgraph:{tenantId}:drive/{driveId}/item/{itemId}
```
Stable across rename/move within a drive ⇒ idempotent delta upserts. Path, name,
webUrl deliberately **excluded** (mutable → metadata).

### Pointer per item
- `type`: `folder` (folders) / `document` (files); `kind="pointer"`, empty content.
- `label`: readable, says it's a folder, and carries company + hierarchy. Convention:
  - folders: `📁 {Company} › {relative path under company}`
  - files:   `{Company} › {relative path under company}`
  - (Company prefix only inside a recognised company folder; otherwise library-relative.)
- `metadata` (all the mutable bits): `sp_path`, `name`, `webUrl`, `driveId`, `itemId`,
  `lastModifiedDateTime`, `size`, `library`, `fund_folder`, `company`.
- No fetch-URL attribute — it's derivable from the key (§3). Future fetch-tuning
  metadata can be added later.
- **acl** (access control is the `pointers.acl` array of principals — there is no
  `access_class` column): set `principals=["ca61f0e5-563e-5894-954f-38f5a9e0eabc"]`
  (`KIBO_TENANT`) on every skeleton pointer — same acl as 299 existing Kibo pointers.
  Widen/narrow per-item later.

### Edges
- **Hierarchy** (mirrors the SharePoint parent; key derived from `parent_id` + same
  `driveId`, no lookup):
  - file   —`documents_of`→ parent folder
  - folder —`folder_of`→ parent folder
  - top-level items → the **library folder pointer**.
- **Library root**: each drive = one `folder` pointer (single root per drive, natural
  acl anchor).
- **Reconciliation** (relate to existing entities — reuses `folder_of`):
  - company folder —`folder_of`→ existing `company` pointer ("the folder *of* Carto")
  - fund folder —`folder_of`→ existing `fund` pointer

  So the SP tree is mirrored faithfully *and* the top company/fund folders also point
  at their entities. Traversal: `company → folder_of (incoming) → folder → documents_of
  (incoming) → documents`.

## 3. Reconciliation maps (live-data grounded)
### Funds → existing `fund` pointers
Graph currently has **Fund II/III/IV + Opportunity Fund** only:
| Folder | canonical_key |
|---|---|
| `2.2 Portfolio Fondo II` | `fund:naluat:fund-ii` |
| `2.3 Portfolio Fondo III` | `fund:naluat:fund-iii` |
| `2.4 Portfolio Fondo IV` | `fund:naluat:fund-iv` |
| `2.5 Opportunity Fund I` | `fund:naluat:opportunity-fund` |
| `2.1 Portfolio Fondo I` | **no fund pointer exists** — create folder, leave unlinked (or add Fund I later) |
| `99. Parking Pre Seed`, `Otros` | not funds — folders only, no `about` edge |

### Companies → existing `company` pointers
Resolve by **normalised-label lookup** against a prefetched index (companies are keyed
by domain, e.g. `company::…::cala.ai`, so we match on label, not key). Normalise =
strip `NNN - ` prefix → lowercase → remove non-alphanumerics.
- **30/39 auto-match** (Carto, Devo, Belvo, Acurable, Capchase, Exoticca, Odilo, Paack,
  Sorare, Trucksters, Zynap, KDPOF, Qida, Cala, Anyformat, NeuralTrust, Fossa, Fermat,
  Theker, Hole19, Hyperspectral, Innovamat, Frenetic, GoTrade, Evernest, PandaGo, Zepo,
  Rewardsweb, Mito, InfiniteWatch).
- **9 need a `COMPANY_ALIAS` override** (mirrors Naluat's `RECONCILIATION`): Clarity,
  DefinedCrowd, Green Eagle (`greeneaglesolutions.com`), Job and Talent, Mitiga, Plenit
  (`jotelulu.com`), Tappx, Tier, Worldsensing. Some may genuinely not exist as pointers
  yet → create the skeleton folder unlinked and report the gap.

## 4. Ingestion runner — `scripts/kf_ingest_sharepoint.py`
Reuses `EdgeFunctionClient` (retry/backoff), `resolve_pointer_id`, `link_pointers`,
`ingest_batch`, and `_load_env_local` (from the SharePoint scripts).
1. `enumerate_drive` the Kibo_Ventures library; slice to `02_Portfolio` (and to one
   company for the first sample: `--company "Carto"` / `--limit N`).
2. Build pointers + edges via the adapter.
3. Upsert pointers via **`ingest-batch` in chunks of 50** (`MAX_BATCH_SIZE`), with
   timeouts/backoff between batches.
4. Resolve canonical_keys → ids, create `contained_in` + `about` edges via `link-pointers`.
5. `--dry-run` prints the pointer/edge plan without calling edge functions.

## 5. Skill vocabulary update
Update kf-ingest / kf-query / kf-schema skill docs (and the `schema_vocabulary` rows in
§1) so the skills know: `folder` pointers and body-less `msgraph:` `document` pointers
are SharePoint **mirror** nodes — query by label/hierarchy, fetch contents on demand,
never expect an inline body.

## 6. Sync (later phase — not now)
- Persist the `@odata.deltaLink` per library (e.g. on the library folder pointer) so
  later runs fetch only changes — `enumerate_drive` must be extended to **return** the
  deltaLink (today it's discarded).
- Capture `deleted` tombstones (today skipped) to soft-delete/remove moved/deleted
  pointers. itemId is stable within a drive; cross-library moves = delete+create (the
  user confirmed portfolio docs won't move between libraries).

## Decisions (resolved)
- **Label** — company-prefixed path (`📁 Carto › 3. RONDAS`; files without the folder
  emoji). Full `sp_path` also in metadata.
- **Embeddings** — keep `ingest-batch` label embeddings (semantic search of names).
- **Edges** — `documents_of` (file→folder) / `folder_of` (folder→folder and
  folder→entity). No `about`/`contained_in`.
- **acl** — `["ca61f0e5-563e-5894-954f-38f5a9e0eabc"]` (Kibo tenant) on all pointers.

## Status
- **S0 DONE (prod):** `folder` enum + vocab rows (`folder`, `folder_of`, `documents_of`).
- **S1 DONE & VERIFIED:** Carto (454 ptr / 454 edges). Handover: `handover-S1.md`.
- **S3 DONE & VERIFIED (prod):** FULL `02_Portfolio` — **30,340 pointers** (7,994 folder
  / 22,346 document) + ~30,378 edges (22,346 documents_of / 8,032 folder_of). 0 errors.
  DD via REST PASSED (counts match source, keys/acl all correct, no file orphans, no
  dangling). Handover: `handover-S3.md`.
- **Pointer phase rewritten:** dedup path (per-item vector-similarity search) does NOT
  scale — crashed at 11.6k. Replaced with direct PostgREST **bulk INSERT keyed on
  canonical_key** (insert-only-missing; no unique constraint exists). Edges stay
  concurrent `link-pointers` with 409-skip. Idempotency bug fixed (409 = skip).
- **OPEN follow-ups:** (1) backfill embeddings + search_text for 18,681 null rows
  (option A); (2) add folder_of/documents_of hint to `query-knowledge` schemaContextFor;
  (3) `COMPANY_ALIAS` for ~7 unresolved companies; (4) Fund I has no entity; (5) full
  site + delta sync (deltaLink + tombstones).

## Execution & orchestration (clean-context agents + handover/DD loop)
**Honest shape:** this pipeline is **sequential-gated** — the migration must land
before any folder-pointer write, and each scale-up must be DD-verified before the
next. So the win is **one fresh executor agent per stage + one DD agent per gate**
(each with clean context, seeded by the prior handover), **not** many parallel
agents. Genuine parallelism is limited (noted per stage). Within a stage, data
parallelism (many funds/companies) belongs as bounded async concurrency *inside the
runner* — not as separate agents, which would just contend on the same edge
functions/DB.

Handover dir: `.claude/kf/sharepoint_run/` (mirrors the existing `naluat_run/`
handover convention).

### The loop (every stage)
`execute → write handover-S{n}.md → spawn DD agent (reads ONLY handover + repo + DB) →
PASS/FAIL with evidence → if PASS, spawn next stage's executor seeded with the handover`.

Each **handover-S{n}.md** records: what changed (code/migration/data), any
**data-structure changes** (enum values, edge relationship_types, key scheme,
metadata shape), exact counts written, how to verify, and open risks. Each **DD agent**
is read-only (Explore-style + SQL), never trusts the executor's claims, and re-derives
counts from source + DB.

### Stages & dependencies
| Stage | Work | Depends on | Parallel? |
|---|---|---|---|
| **S0** | Apply the `folder` migration to prod | — | blocks all |
| **S1** | Real load of **Carto** sample; DD = full coherency suite | S0 | — |
| **S2a** | Skill vocab docs (kf-ingest/query/schema) | S0 | ‖ with S1/S2b (no data dep) |
| **S2b** | Load one full fund (**Fund III**) | S1 PASS | ‖ with S2a |
| **S3** | Full `02_Portfolio` (~30k items). **Prereq: bounded async concurrency for the edge phase + skip-if-exists** (serial link-pointers won't scale to ~30k edges) | S2b PASS | data-parallel inside runner |
| **S4** (later) | Whole site + **delta sync** (persist `@odata.deltaLink`, handle `deleted` tombstones) | S3 PASS | — |

### Per-stage agent brief (what each executor is handed)
Plan file + prior handover + the specific scripts (`kf_ingest_sharepoint.py`,
adapter, migration) + explicit acceptance criteria + the project/Supabase MCP tools.
Tenant facts it must not re-derive: Entra tenant `6e409d59-…` (key), Kibo acl
`ca61f0e5-…`, library `Kibo_Ventures`, funds map, company-index source.

## Data-coherency checks (DD gate checklist)
Run after every data stage; all must hold for PASS:
1. **Count parity** — `pointers written == source items in slice` (folders+files),
   and the folder/document split matches the source.
2. **Key integrity** — all keys match `msgraph:{entra}:drive/{driveId}/item/{itemId}`;
   tenant == Entra GUID; `canonical_key` unique (no dupes).
3. **No orphans** — every pointer except an intended slice-root has exactly one
   structural edge (`documents_of`/`folder_of`) to an in-graph parent.
4. **Reconciliation** — every company/fund folder has a `folder_of` edge to an
   **existing** `company`/`fund` pointer; the unresolved list is reviewed/empty.
5. **acl** — every skeleton pointer's `acl == ['ca61f0e5-…']`.
6. **Edge endpoints resolve** — no dangling `source_id`/`target_id`.
7. **Idempotency** — re-running the stage yields **0 created, all merged** (delta
   upsert proven; no duplicate keys). The single most important coherency proof.
8. **Schema delta** — confirm only the intended structure change landed: `folder`
   enum value + vocab rows present; no other `pointer_type`/edge type perturbed;
   `get_advisors` shows no new RLS/security regressions.

### Verification of S1 (Carto) specifically
- 454 `msgraph:` pointers (112 folder / 342 document), all bodies empty, acl=Kibo.
- `folder_of`/`documents_of` chain reconstructs both Carto subtrees.
- Both Carto company folders → `folder_of` → `company::…::naluat:carto`.
- Re-run → all merged, 0 created.
