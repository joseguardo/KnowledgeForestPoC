# Handover — Agent BE (backend: Naluat ingest)

Backend for ingesting Kibo's Naluat fund ledger into KnowledgeForest. **Code only
— no migration applied, no real ingest run.** Self-tested via parse-only dry-run.

## Files changed

1. **NEW** `pipeline/pipeline/adapters/naluat.py` — pure/offline parser + model
   builder. Reads `naluat_neo.json` (fallback `naluat_neo.csv`) and produces
   `FundSpec` / `CompanySpec` / `EventSpec` / `EdgeSpec` via `build_model(path)`.
   No DB / network. Holds: `slug()`, `transaction_type()`, the 12-key
   `RECONCILIATION` map, `KIBO_TENANT`, `SOURCE="Naluat"`, canonical-key helpers,
   and all rollup computation.
2. **EDIT** `pipeline/pipeline/api/ingest.py` — added `@router.post("/naluat",
   response_model=IngestResponse)` (`ingest_naluat`) + helper `_naluat_attr_dicts`
   + imports from the adapter. Appended after the `/affinidad` handler.
3. **EDIT** `pipeline/pipeline/models.py` — added `NaluatRequest`; exported it via
   the ingest.py model import block.

## `NaluatRequest` shape
```python
class NaluatRequest(BaseModel):
    source_path: str | None = None   # defaults to repo naluat_neo.json
    dry_run: bool = False            # True → parse + return counts, NO writes
```

## Dry-run command + actual output

Adapter-level (uses the pipeline venv; base python3 lacks fastapi):
```bash
cd pipeline && .venv/bin/python -c "from pipeline.adapters.naluat import build_model; import json; print(json.dumps(build_model().counts()))"
```
Output:
```json
{"funds": 4, "companies_existing": 12, "companies_new": 38, "events": 347,
 "edges": 749, "edges_part_of": 55, "edges_transaction_of": 347,
 "edges_booked_to": 347, "unmapped": 0}
```

Endpoint-level dry_run (no client/http touched — verified with a stub Request
that has no `app.state.client`): `source_type="naluat"`, `items_produced=1150`,
`results[0].detail` = the counts above, `errors=[]`.

Self-test assertions all pass: 347 rows, **0 unmapped** types; 347 unique event
keys; **0 dangling edges** (every edge endpoint references a known pointer key);
all 12 reconciliation companies resolve to their existing canonical_key. Module
imports clean (`import pipeline.api.ingest` OK).

## Data-structure deltas introduced

- **New pointer type `fund`** (4 pointers) — requires Agent M's enum migration
  (`ALTER TYPE public.pointer_type ADD VALUE 'fund'`) to exist **before** the real
  run, or the fund inserts 4xx. Canonical key `fund:naluat:<slug(name)>`.
- **Pointer types reused:** `company` (12 merge by existing key, 38 new under
  `company::<kibo>::naluat:<slug>`), `event` (347, key `event:naluat:<row id>`,
  occurred_at = row `date`, label `"<company> — <txn_type> — <YYYY-MM-DD>"`).
- **New edge relationship types:** `transaction_of` (event→company, 347),
  `booked_to` (event→fund, 347); plus reused `part_of` (company→fund, 55).
- **Edge payload schema** (on transaction_of + booked_to, 694 edges, uniform;
  empty fields omitted): `{amount, currency, transaction_type, company, fund,
  date(YYYY-MM-DD)}`.
- **`naluat_*` attribute keys** (all `source="Naluat"`):
  - Fund: `naluat_company_count` (number), `naluat_invested_by_currency` (json).
  - Company: `naluat_status` (active|partially_divested|divested|written_off),
    `naluat_invested_by_currency`, `naluat_realized_by_currency`,
    `naluat_current_value_by_currency`, `naluat_moic` (number, primary-ccy only),
    `naluat_first_date`, `naluat_last_date`, `naluat_currency`, `naluat_funds`
    (json), `naluat_valuation_series` (json array of `{date,currency,amount}`,
    time-ordered).
  - Event: `amount, currency, transaction_type, raw_type, raw_subtype, fund,
    round_name, follow_on, pps, premoney, shares, reported_value, is_calculated,
    src_id` (empty-valued attrs omitted).

## transaction_type mapping (verified against live data, 10 combos, 0 unmapped)
`investment/*`→investment (280); `valuation/*`→valuation (24);
`partial_divestment/*` + `full_divestment/*`→divestment (38);
`write_off/*`→write_off (5). Match on the row `type` prefix; raw preserved in
`raw_type`/`raw_subtype`.

## Assumptions / deviations
- **Row id**: each row's unique `id` (== `elementId`) keys the event. Confirmed
  unique across all 347 rows.
- **part_of = 55**, not "one per company" — it's one per distinct (company,fund)
  pair; several companies appear in 2 funds (e.g. Fund II + Opportunity Fund).
- **MOIC** computed only in the company's primary (most-frequent) currency as
  `(realized + current_value) / invested`; omitted when invested in that ccy is 0
  or absent (cross-currency MOIC is not meaningful).
- **current_value_by_currency** = latest (max-date) valuation `amount` per ccy.
- **valuation_series** includes only valuation rows with a usable amount **and**
  currency **and** date (some valuation rows are null/zero placeholders → skipped).
- **primary currency**: ~67 rows have null currency; those rows still produce an
  event (currency attr omitted) and still link/roll up by-currency only when a
  currency is present. `naluat_currency` is the most frequent non-null ccy.
- **Round name** comes from `data.nombre_ronda` (there is no `data.round_name`
  column in the export).
- Endpoint mirrors Affinidad's `_ok`/`_fail` accumulation; edges ignore
  `EdgeFunctionError` 409 (duplicate) for idempotent re-runs.

## KNOWN BUG TO WATCH (double-encoding) — for DD-RUN, not fixed here
`ingest-batch/index.ts` line 146 and `insert-pointer` both do
`JSON.stringify(value)` for **string** attribute values, so scalar strings land
as `"\"x\""` in `attributes_kv.value` (breaks exact-match attribute filters).
This is the same write path Affinidad uses. Per the plan this is verified/
remediated during DD-RUN (apply `value #>> '{}'` normalization or store strings
as json) — the BE adapter does not pre-encode.

## Exact command to run the REAL ingest (DO NOT run until Agent M's `fund` enum
migration is applied)
With the pipeline service running (`cd pipeline && .venv/bin/uvicorn
pipeline.api.app:app --port 8000` — confirm the app module path), POST:
```bash
# 1) dry-run sanity (no writes)
curl -s localhost:8000/ingest/naluat -H 'content-type: application/json' \
  -d '{"dry_run": true}' | jq

# 2) REAL ingest (writes via edge functions)
curl -s localhost:8000/ingest/naluat -H 'content-type: application/json' \
  -d '{"dry_run": false}' | jq
```
Order enforced by the handler: funds → companies → events (batches ≤50) → edges
(part_of, transaction_of, booked_to). Re-runnable (canonical-key dedup, 409-
ignored edges, rollups recomputed each run).
