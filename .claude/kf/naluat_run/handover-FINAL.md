# Handover — FINAL (Naluat ingest complete)

**Date:** 2026-06-29 · **KF project:** sjiepibqadbdowcizccw · **Access:** Kibo only
(`acl=[ca61f0e5-563e-5894-954f-38f5a9e0eabc]`).

## Outcome: COMPLETE and DD-green

Ingested Neo's Naluat fund ledger (347 txns / 50 companies / 4 funds) as an
event-per-transaction graph, all writes through the edge functions.

| | count |
|---|---|
| `fund` pointers (NEW type) | 4 (`fund:naluat:<slug>`) |
| `company` pointers | 631 (was 593; **+38 new, 12 merged, no dupes**) |
| `event` pointers (one per txn) | 347 (`event:naluat:<row id>`) |
| `transaction_of` edges (event→company) | 347 |
| `booked_to` edges (event→fund) | 347 |
| `part_of` edges (company→fund) | 55 |
| event attribute rows | 347 × ~13 keys |

- Edge payloads on transaction_of/booked_to: `{amount,currency,transaction_type,company,fund,date}`.
- Company attrs (source=Naluat): naluat_status, naluat_invested_by_currency,
  naluat_realized_by_currency, naluat_current_value_by_currency, naluat_moic,
  naluat_first_date, naluat_last_date, naluat_currency, naluat_funds,
  naluat_valuation_series. Fund attrs: naluat_company_count, naluat_invested_by_currency.
- Rollups verified == Σ edge-payload amounts; access gate verified (anon sees nothing).

## Two bugs found by DD-RUN and remediated

1. **Event attributes were dropped** — adapter emitted `data_type="bool"` but the
   DB enum only accepts `"boolean"`; the enum cast failed and ingest-batch swallowed
   the per-item `attribute_error`. Fixed [naluat.py:252](../../pipeline/pipeline/adapters/naluat.py) (`bool`→`boolean`) + re-ran the ingest (idempotent). All 347 events now carry attributes; `is_calculated` stored as proper boolean.
2. **String double-encoding** (pre-existing edge-fn bug: `JSON.stringify` on string
   values in insert-pointer:121 / ingest-batch:146) → strings stored as `"\"EUR\""`.
   Fixed by de-double-encoding all **2665** Naluat string/date attr rows via
   PostgREST PATCH (service role), idempotent. 0 remaining. Exact-match attr filters
   now work (`value=eq."written_off"`).

## Downstream code updated (additive) to surface the new type/edges
- pipeline/pipeline/adapters/structured.py — added `fund` to VALID_POINTER_TYPES.
- supabase/functions/query-knowledge/index.ts — SCHEMA_CONTEXT now lists `event`,
  `fund`, `transaction_of`, `booked_to` + a Naluat/portfolio hint. ⚠ **needs edge-fn
  redeploy to take effect.**
- src/components/InsertPanel.jsx, src/explainer/ExplainerPage.jsx — added event/fund
  to the type lists. (Left src/demo/simulationTimeline.js alone — curated demo.)

## Outstanding (need access I don't have)
- **Redeploy `query-knowledge`** so the NL planner knows about fund/event/edges.
  (Structured RPCs — get_pointer_subgraph, traverse_graph, direct edge queries — already work.)
- **Recommended permanent fix**: remove `JSON.stringify(value)` on strings in
  insert-pointer & ingest-batch edge functions (fixes the double-encoding system-wide;
  otherwise it recurs on every re-ingest and the PostgREST normalization must be re-run).

## Re-run / maintenance
- Real ingest: `cd pipeline && nohup .venv/bin/uvicorn pipeline.main:app --port 9099 ... ` then `curl -X POST :9099/api/v1/ingest/naluat -d '{}'`. Fully idempotent.
- **After any re-ingest, re-run the de-double-encoding** PostgREST PATCH (until the
  edge functions are fixed): de-double-encode rows where `source='Naluat'` and the
  jsonb value is a quoted string.
- Querying a fund's transactions: inbound `booked_to` edges
  (`edges?target_id=eq.<fund>&relationship_type=eq.booked_to`) or
  `get_pointer_subgraph(fund_id)`; fund totals via `naluat_invested_by_currency`.
