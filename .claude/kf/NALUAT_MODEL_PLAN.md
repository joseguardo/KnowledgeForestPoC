# NALUAT → KnowledgeForest modeling plan

## Context

The Neo project (`yphbrpbwpakjduhmoimw`) holds `public."NALUAT_all_Funds_Merged"`
— **347 ledger rows** (investments, valuations, divestments, write-offs) for
**50 portfolio companies** across **4 funds** (Fund II/III/IV, Opportunity Fund).
This is the firm's live portfolio ledger and **will grow** (recurring updates).

We are ingesting it into the KnowledgeForest (`sjiepibqadbdowcizccw`). The prior
"meta-funds + per-company `naluat` attributes" attempt left `naluat_*` keys
registered in `schema_vocabulary` but **no live rows** (it was never applied to
this DB). Clean slate, with vocabulary scaffolding to reuse.

Decisions taken with the user:
- **Grain = timeseries.** The ledger is a recurring operational time series per
  company, not one-off events. Model it as `timeseries_data` on the company,
  with platform-facing **rollups as company attributes**. No per-row pointers.
- **Access class = firm-scoped (confidential)**, acl = the firm
  `ca61f0e5-563e-5894-954f-38f5a9e0eabc`.
- **Company reconciliation = proposed mapping for approval** (the §Reconciliation
  table below) — match hard before creating duplicates.

## The three governing questions

### 1. Vocabulary (advisory; `pointers.type` is hard enum, edges/attr keys free text)

- **Pointer types** — reuse only. `company` (portfolio cos), `meta` (funds, as the
  existing "opportunity" rows already use `meta`). No new types; the enum is hard
  and every value we need is already active.
- **Edge types** — reuse `part_of` (registered, currently 0 live edges) for
  `company → fund` portfolio membership. **No new edge types.** (We are not
  adding `regarding`/`booked_to` because there are no event pointers.)
- **Attribute keys** — reuse the already-registered `naluat_*` set
  (`naluat_status`, `naluat_invested_by_currency`,
  `naluat_current_value_by_currency`, `naluat_first_date`, `naluat_last_date`,
  `naluat_currency`, `naluat_company_count`). **New keys to register**
  (then re-run `backfill-vocab-embeddings`): `naluat_funds`,
  `naluat_realized_by_currency`, `naluat_moic`.
- **Timeseries `metric_name`** is NOT governed by `schema_vocabulary` (only the
  three categories are). Adopt and document a convention:
  `naluat:investment | naluat:valuation | naluat:divestment | naluat:write_off`.

### 2. Source / provenance (two places)

- **Trust** — every NALUAT fact carries `source = 'neo:naluat'` on both
  `attributes_kv.source` and `timeseries_data.source`. `confidence = 1.0` for
  reported rows; `0.6` where the source row has `isCalculated = true` (platform-
  derived marks). This is what conflict-resolution/dedup lean on.
- **Identity** — fold the source system into canonical keys (below) so
  re-ingestion is idempotent.

### 3. Canonical key (the upsert identity — namespace by type, stable natural key)

- **Funds**: `fund:neo:<source fund_id>` (e.g. `fund:neo:qxsDposBzWTQuO_KVE_Q`).
  Native id, stable.
- **Companies (new)**: `company:neo:<slug(name)>`, acl = firm. (NALUAT has no
  domain/company-id column, so we cannot reconstruct the `company:<domain>` key;
  slug-on-name + the reconciliation pass is how we avoid duplicating real cos.)
- **Companies (matched)**: reuse the existing pointer's id/key — prefer the
  **firm-scoped variant** `company::ca61f0e5…::<domain>` when it exists, else the
  public `company:<domain>`.
- **Timeseries rows**: `timeseries_data` has **no canonical key / unique
  constraint**. Idempotency = **full refresh by source**: delete
  `WHERE source='neo:naluat' AND pointer_id = ANY(targets)` then bulk re-insert,
  carrying the source row `id` in `value->>'src_id'` for traceability.

## Target model

```
fund (meta)  ──◄ part_of ──  company (company)
                                  │
                                  ├─ timeseries_data  (one row per ledger entry)
                                  │     ts=date, metric_name=naluat:<type>,
                                  │     value={amount,currency,subtype,fund,
                                  │            round_name,follow_on,pps,premoney,
                                  │            shares,reported_value,is_calculated,src_id},
                                  │     source='neo:naluat'
                                  │
                                  └─ attributes_kv  (rollups, naluat_* keys,
                                        source='neo:naluat', acl=firm)
```

Type/subtype → metric mapping (from the live data, 10 combos):
- `investment/{primary,secondary,convertible_notes}` → `naluat:investment`
- `valuation/{fair_value,pps}` → `naluat:valuation`
- `partial_divestment/{cash,escrow_account}`, `full_divestment/cash` → `naluat:divestment`
- `write_off/{equity,debt}` → `naluat:write_off`
(raw `type`/`subtype` preserved inside `value` for fidelity.)

Per-company rollups (reuse `naluat_*`): `naluat_status`
(active / partially_divested / divested / written_off), `naluat_invested_by_currency`,
`naluat_realized_by_currency`, `naluat_current_value_by_currency` (latest
valuation per ccy), `naluat_first_date`, `naluat_last_date`, `naluat_currency`,
`naluat_funds`. Fund-level: `naluat_company_count` on the fund pointer.

## Reconciliation (50 companies — approve before ingest)

**Attach to existing pointer** (prefer the `ca61f0e5` firm variant if present):
Anyformat, Cala, Devo, Fossa Systems, Innovamat, Job&talent→Jobandtalent,
NeuralTrust, Odilo, Onum, Paack, Qida, Trucksters, Zynap, Circular→Cocircular,
Green Eagle→Green Eagle Solutions, Theker→THEKER Robotics.

**Ambiguous — need a call:**
- **KD** → `company::ca61f0e5…::kd.tech` *or* KDPOF (`company:kdpof.com`)? (person `kdteams@kdpof.com` hints KDPOF.)
- **Plenit** → exists only as Affinity *opportunity* (`opportunity:affinity:101004347`, type meta). Create a `company` pointer and optionally `related` to the opportunity.

**Create new** (firm-scoped, `company:neo:<slug>`; no real match found):
21 Buttons, Acurable, Aerial Technologies, Apartum, Belvo, Billin, Bipi,
Capchase, Carto, Cibeles, Clarity AI, CoverWallet, Defined AI, EnjoyHQ,
Evernest, Exoticca, Frenetic, Gamelearn, Gamestry, Gestoos, Gotrade, Hole19,
Hyperspectral, Mitiga Solutions, PandaGo, Proportunity, Rewardsweb, Sorare,
Stoyo, Tier Mobility, Vilynx, Zepo. (Domain can be inferred for some from
existing person-email pointers, e.g. Evernest→evernest.com, Exoticca→exoticca.com.)

## Ingest / sync mechanics

Neo and KF are **separate projects**, so the connector reads Neo and writes KF.
Build `pipeline/naluat_sync.py` (reusable for recurring syncs), or drive via the
exported [naluat_neo.json](../../naluat_neo.json) we already pulled:
1. Load approved company mapping (name → existing pointer id, or "create").
2. Upsert **fund** + new **company** pointers via KF `insert-pointer` /
   `ingest-batch` edge functions (handles embedding, dedup, acl). Stamp
   `access_class: "firm:ca61f0e5-563e-5894-954f-38f5a9e0eabc"`.
3. Create `company → fund` `part_of` edges via `link-pointers`.
4. **Full-refresh `timeseries_data`** for the target companies (delete-by-source,
   then insert 347 rows) — via KF service role (`execute_sql`) since there is no
   timeseries ingest edge function.
5. Compute & upsert the `naluat_*` rollup attributes per company / fund.
6. Register the 3 new attribute keys in `schema_vocabulary` + run
   `backfill-vocab-embeddings`.

## Open items to resolve before ingest

- **⚠ `timeseries_data` is world-readable — blocks firm-scoping.** Confirmed:
  RLS is on, but the policies are `ts_anon_read USING (true)` and
  `ts_auth_read USING (true)` (no `acl` column, no gating). If the ledger goes
  into `timeseries_data` as-is, **any anon caller can read every mark** —
  incompatible with the firm-scoped requirement. Options:
  - **(Recommended) Add an `acl uuid[]` column to `timeseries_data` + rewrite the
    read policies** to `can_read_acl(acl)` (mirroring `attributes_kv`). Keeps the
    timeseries grain and enforces firm confidentiality. One migration; backfill
    existing rows' acl to public so current behavior is preserved.
  - Store the sensitive marks as acl'd `attributes_kv` instead — rejected: the
    `UNIQUE(pointer_id,key)` constraint can't hold many dated points per metric.
  - Accept public-readable ledger — rejected for portfolio financials.
- Confirm the **KD** (kd.tech vs KDPOF) and **Plenit** (opportunity→company) calls.
- Confirm currency handling for `naluat_*_by_currency` (data has EUR + others).

## Verification (expose results multiple ways, per the brief)

- **SQL rollup**: invested vs. current value vs. realized, MOIC, grouped by fund
  and by company (`execute_sql`).
- **Timeseries retrieval**: `get_pointer_subgraph(company_id)` → latest marks;
  trend of `naluat:valuation` over `ts` for a company.
- **Graph**: `traverse_graph` from a fund over `part_of` → its portfolio.
- **NL**: `query-knowledge` as a firm member — "What has Neo invested in Paack?"
  / "Which Fund II companies are written off?" (restricted-class clearance).
- Spot-check idempotency: re-run sync → row counts stable, no duplicate pointers.

## FINAL DECISIONS (user, supersede above where they differ)

- **Funds = new pointer type `kibo_funds`** (NOT `meta`). Requires
  `ALTER TYPE pointer_type ADD VALUE 'kibo_funds'` (irreversible) + a
  `schema_vocabulary` row (category `pointer_type`). Canonical key
  `kibo_fund:<fund_name>` (e.g. `kibo_fund:Fund II`).
- **Company canonical key (new) = `company:<company_name>`** (e.g.
  `company:Belvo`). Matched companies reuse the existing pointer (prefer the
  `ca61f0e5` firm variant).
- **Attributes follow the Afinidad storage pattern exactly**: `value` = JSON
  scalar, `data_type` per value, `sort_order=0`, `confidence=null`,
  `acl=[ca61f0e5…]`. Keys stay the registered `naluat_*` set.
- **Source string = `Naluat`** (not `neo:naluat`) on `attributes_kv.source` and
  `timeseries_data.source`.
- **Timeseries RLS**: add `acl uuid[]` to `timeseries_data` (default = public
  sentinel so existing rows stay readable), drop `ts_anon_read`/`ts_auth_read`
  (`USING true`), add `ts_read USING (acl && (SELECT my_principals()))` —
  mirroring `pointers_read`/`attrs_read`. NALUAT ts rows get `acl=[ca61f0e5…]`.
- **Reconciliation resolved**: **Plenit → Jotelulu** (rebrand) →
  `company::ca61f0e5…::jotelulu.com` (id `e19e59f3-04d8-4e52-9ed3-f27a2033e594`).
  **KD → KDPOF** → `company:kdpof.com`.
