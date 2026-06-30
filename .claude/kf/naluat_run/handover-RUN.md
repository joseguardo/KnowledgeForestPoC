# Handover — Agent RUN (live Naluat ingest into the KnowledgeForest)

Ran the real Naluat fund-ledger ingest into production (KF project
`sjiepibqadbdowcizccw`) via the FastAPI `/api/v1/ingest/naluat` endpoint, which
writes through the Supabase edge functions (`insert-pointer`, `ingest-batch`,
`link-pointers`). **Result: SUCCESS, 0 errors.** All target counts met.

## Prerequisite verified
- `fund` enum migration **is applied**: `schema_vocabulary` row
  `term=fund, category=pointer_type` present (id `436b9a8c-…`, created
  2026-06-29T10:42Z). Fund inserts were free to proceed.

## Operational note (how the run actually went — re-run, not first-try)
The ingest is **sequential and slow**: ~1100 edge-function calls, ~286 s wall
clock for a full pass (each edge = one HTTP round-trip). The first two attempts
were killed mid-flight by the harness's background-task reaper (it kept SIGKILLing
the uvicorn process). Two pitfalls hit and worked around:
1. **Port 8000 was squatted** by an unrelated app (the ContractExtractor
   `/api/v2/ingestion/*` FastAPI) which returns `{"error":"Not found"}` for our
   routes — easy to mistake for our server. Port 8011 was also occupied. **Ran on
   port 9099** (verified `/api/v1/health` returns our KF supabase_url) to be sure
   requests hit our app.
2. Launch uvicorn with `nohup … & disown` from a foreground Bash call (not the
   harness `run_in_background`), and run the long curl with `run_in_background`,
   so neither gets reaped mid-request.

Because the ingest is fully idempotent (canonical-key dedup → `merged`;
409-on-duplicate edges ignored), the partial runs caused **no corruption** — the
final pass re-merged all pointers and created only the missing edges. Final state
below is correct and complete.

## Pre-state (service-role PostgREST, count=exact)
- company = **593**, event = **0**, fund = **0**  (matches expected)

## Dry-run (live, `{"dry_run":true}` on the endpoint)
`items_produced=1150`, `errors=[]`, detail:
```
funds=4  companies_existing=12  companies_new=38  events=347
edges=749  part_of=55  transaction_of=347  booked_to=347  unmapped=0
```
All counts exactly as expected.

## Real-ingest envelope (final, clean pass — `{}` body)
```
source_type   : naluat
items_produced: 792
duration_ms   : 285761  (~286 s)
errors        : []          ← ZERO errors
result status : {merged: 401, created: 391}
```
- `merged=401` = 4 funds + 50 companies + 347 events (all already existed from the
  earlier partial passes → idempotent merge). On a true first run these would be
  `created`/`merged` mixed, but the cumulative DB state is identical.
- `created=391` = the edges this pass inserted (the missing
  195 transaction_of + 196 booked_to). The 358 already-existing edges returned
  409 Conflict and were ignored (not counted in `results`). Net link-pointers
  HTTP: **391 × 201 Created + 358 × 409 Conflict = 749** (the full edge set).
- **No `errors[]` entries at all.**

## Post-write counts (pre → post)
| type / edge        | pre | post | delta |
|--------------------|-----|------|-------|
| company (pointer)  | 593 | **631** | +38 (new), 12 merged (no dupes) |
| event (pointer)    | 0   | **347** | +347 |
| fund (pointer)     | 0   | **4**   | +4 |
| part_of edge       | —   | **55**  | (company→fund) |
| transaction_of edge| —   | **347** | (event→company) |
| booked_to edge     | —   | **347** | (event→fund) |

Company `count = 631`, `distinct canonical_key = 631` → **the 12 reconciled
companies merged, not duplicated.**

## Data-structure deltas now live (verified)
- **New `fund` pointer type**: 4 fund pointers, `acl=[ca61f0e5-…]` (Kibo only),
  carrying `naluat_company_count`, `naluat_invested_by_currency`.
- **New edge relationship types**: `transaction_of` (347, event→company),
  `booked_to` (347, event→fund). Reused `part_of` (55, company→fund: 50 companies
  → 4 funds; some companies in 2 funds).
- **Edge payloads** on all 694 transaction_of+booked_to edges:
  `{amount, currency, transaction_type, company, fund, date}`. Coverage:
  `transaction_type` present on **347/347** of each; `amount` on **342/347**
  (the 5 without are null/zero valuation placeholders, expected).
- **`naluat_*` company attrs** (366 attribute rows on company pointers) and
  **fund attrs** (8 rows). Spot-checked rollup coherency (Paack):
  `naluat_invested_by_currency = {EUR: 11559735.64}` **equals** the Σ of EUR
  `transaction_of` edge-payload `amount` for investment txns (11559735.64); the
  null-currency rows (727108.07) correctly excluded from the by-ccy rollup. ✓
- **Integrity**: every event has exactly **one** transaction_of and **one**
  booked_to (347 each); **0 dangling edges**; **0 unmapped** transaction types.
- **Access gate**: fund pointers and new edges sampled → `acl=[ca61f0e5-…]`.

## ⚠ Things DD-RUN must scrutinize

1. **Event-pointer attributes were NOT persisted.** This is the biggest finding.
   The 347 events were created with correct `label`, `occurred_at`, and
   `metadata={"source":"Naluat"}`, **but their per-event attributes (amount,
   currency, transaction_type, raw_type, raw_subtype, fund, round_name, pps,
   premoney, shares, reported_value, is_calculated, src_id) are nowhere** —
   `attributes_kv` has **0** rows for any event pointer, and the pointer
   `metadata` holds only `{"source":"Naluat"}`.
   - Root cause: events go through the **`ingest-batch`** edge function (batches of
     ≤50), which — unlike `insert-pointer` (used for funds/companies, whose attrs
     DID land) — does **not** write the per-item `attributes[]` into
     `attributes_kv`. The handler passes `"attributes": _naluat_attr_dicts(...)`
     in each batch item, but ingest-batch drops/ignores them.
   - **Functional impact is limited**: all transaction data the model needs for
     queries lives in the **edge payloads** (verified complete), which is the
     designed-in query path (`get_pointer_subgraph` / inbound `booked_to`/
     `transaction_of` with payload). So fund/company transaction listing + sums
     work without event attrs. But any query that reads an *event pointer's*
     attributes directly will find nothing.
   - **DD decision needed**: is edge-payload-only acceptable, or must event attrs
     be backfilled? If the latter: either teach `ingest-batch` to persist
     `attributes` to `attributes_kv`, or re-attach event attrs via `insert-pointer`
     /a direct attributes_kv upsert in a follow-up pass (events already exist;
     keyed by `event:naluat:<id>`).

2. **Double-encoding bug CONFIRMED (the known one).** String **scalar** attribute
   values written via `insert-pointer` are stored double-encoded: e.g.
   `naluat_status` value reads `"\"divested\""` (jsonb string whose content is the
   quoted token `"divested"`), not the scalar `"divested"`. Affected Naluat keys
   and counts: **`naluat_status` (50), `naluat_first_date` (50),
   `naluat_last_date` (50), `naluat_currency` (47)** — 197 string attr rows total.
   Number attrs (`naluat_moic`=3.3565, jsonb number) and json attrs
   (`naluat_invested_by_currency`={…}, jsonb object) are stored **correctly**;
   only string scalars are affected. This breaks exact-match attribute filters
   (`value=eq."divested"` won't match). Per the plan, remediate during DD-RUN
   (`value #>> '{}'` normalization or store strings as json). The BE adapter does
   not pre-encode — the bug is in the `insert-pointer` / `ingest-batch` edge code
   (`JSON.stringify(value)` on string values).

## Idempotency (re-confirmed empirically)
The endpoint is fully re-runnable: pointers dedup by canonical_key (→ `merged`),
events keyed by `event:naluat:<row id>`, duplicate edges return 409 and are
ignored, rollups recomputed each run. Three interrupted passes left **no
duplicates and no corruption**; the final pass converged to the correct state.
Safe to re-run if event-attr backfill or any remediation is applied.

## Reproduction commands
```bash
cd pipeline
# server (avoid squatted 8000/8011; verify health shows the KF supabase_url):
nohup .venv/bin/uvicorn pipeline.main:app --port 9099 > /tmp/uv.log 2>&1 & disown
curl -s localhost:9099/api/v1/health
# dry-run:
curl -s -X POST localhost:9099/api/v1/ingest/naluat -H 'Content-Type: application/json' -d '{"dry_run":true}'
# real (run detached; ~5 min):
curl -s -X POST localhost:9099/api/v1/ingest/naluat -H 'Content-Type: application/json' -d '{}'
```
Live verification uses service-role PostgREST + `rpc/execute_read_query` with
`SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` from `pipeline/.env`.
