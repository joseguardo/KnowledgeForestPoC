# HANDOVER-S3 — Affinidad: re-namespace the 305 Nzyme-owned companies

Date: 2026-06-30 · Prod project: `sjiepibqadbdowcizccw`
Author: ingestion-adapter pass (S3). **No DB writes were performed.** Read-only
PostgREST queries only; the production UPDATE below is for the orchestrator to run.

Tenants:
- KIBO  `ca61f0e5-563e-5894-954f-38f5a9e0eabc`
- NZYME `baa52eca-4c88-4861-9d45-720e743febb4`

---

## (a) Findings — the ownership signal

**Problem.** 305 companies are Nzyme-exclusive (`acl = [NZYME]`, no Kibo) yet remain
keyed under the Kibo namespace `company::ca61f0e5-…::{domain}`. Key and acl disagree.

**What I verified in prod (read-only):**

| set | count |
|---|---|
| `type=company AND metadata->>source=affinidad` (all) | 591 |
| acl contains NZYME | 334 |
| acl contains NZYME **and NOT** Kibo (the target set) | **305** |
| acl contains both (shared — must NOT touch) | **29** |
| acl contains Kibo | 286 |
| of the 305: keyed `company::ca61f0e5-%` | **305** (all) |
| of the 305: keyed `company::baa52eca-%` | 0 |

**Where the acl signal comes from / why the key is wrong.**
- The adapter (`fetch_entities` → `_to_entity` → `company_key` + `access_class=firm:{ent.tenant_id}`)
  drives BOTH the key namespace and the acl from a single per-entity tenant.
- Before this change, that tenant was `_entity_tenant(firm, kind)`, which returns
  the ingest firm (Kibo) for every company (only `kind=="opportunity"` → Nzyme).
  So the adapter, on its own, **can never** produce a Nzyme-only company — neither
  key nor acl. Git history confirms there is only one version of this adapter
  (`5a9006f` → `fe0d2f6` → `bb5258c`); no prior list-ownership variant existed.
- Therefore the `acl=[NZYME]` on the 305 was applied by a **separate one-time prod
  reclassification** (the same class of operation we are now doing for the key). It
  rewrote acl but left `canonical_key` under Kibo — hence the mismatch.
- The true ground-truth ownership lives in the **source CRM list membership**
  (`crm_list_entries` → `crm_lists`): Nzyme dealflow / LP-funnel lists vs Kibo
  dealflow. But `fetch_entities` issues a plain `SELECT … FROM entities` and never
  joins lists, so that signal is **not available at key-build time**. Confirmed on
  the graph side too: across all 305 pointers the ONLY attribute key present is
  `Domain` (no `<List>:Stage`, no `<List>:Owners`, no `Owner`) — i.e. no list/owner
  signal survived onto the pointers either.

**Conclusion for the fix:** the clean programmatic signal (list membership) is not
derivable at this layer today. The authoritative ownership decision that already
exists is **the acl** (Nzyme-exclusive). So the fix makes the company **key follow
the same Nzyme-exclusive decision the acl encodes**, sourced from a seeded
allowlist of exactly those 305 (297 domains + 8 domain-less id-keyed), with a
documented TODO to replace the allowlist with the real list-membership join.

Edge sanity (per task brief, re-confirmed): the 305 have 0 edges to Kibo-only
pointers and ≤6 edges each; re-namespacing them does not orphan Kibo content.

---

## (b) Adapter code change

Two files. Change is minimal, idempotent, and leaves Kibo / opportunity / person
logic untouched.

### New file — `pipeline/pipeline/adapters/affinidad_nzyme_owned.py`
Seeds the ownership allowlist (from the verified 305) and exposes:

```python
NZYME_OWNED_DOMAINS: frozenset[str]      # 297 lowercased domains
NZYME_OWNED_ENTITY_IDS: frozenset[str]   # 8 source entities.id (domain-less companies)

def is_nzyme_owned(domain: str | None, entity_id: str) -> bool:
    d = (domain or "").strip().lower()
    if d:
        return d in NZYME_OWNED_DOMAINS      # domain match first (mirrors company_key)
    return entity_id in NZYME_OWNED_ENTITY_IDS
```
Carries a `TODO(ownership-signal)` to replace the static list with a
`crm_list_entries → crm_lists` join that classifies each list Kibo/Nzyme/shared.

### Edit — `pipeline/pipeline/adapters/affinidad.py`
1. import `is_nzyme_owned`.
2. add `_company_tenant(firm, row)` — returns `NZYME_TENANT` when
   `is_nzyme_owned(row.domain, row.id)` else `firm.tenant_id`. Shared companies are
   deliberately absent from the allowlist, so they stay under Kibo (no churn for the
   29). Opportunity/person paths unchanged (`_entity_tenant`).
3. `fetch_entities` now resolves each row's tenant via a new static helper
   `_row_tenant(firm, row)`: `company → _company_tenant`, else `_entity_tenant`.
   (Previously: `_to_entity(_entity_tenant(firm, r.get("kind")), r, emails)`.)

Because the company key AND `access_class` both derive from `ent.tenant_id`, a
Nzyme-owned company now keys `company::baa52eca-…::{domain}` **and** writes
`acl=[NZYME]` consistently. Downstream `_apply_deal_attributes` and edge/person
acl-unioning already read `ent.tenant_id`, so they inherit the corrected tenant
with no further change. No change to `api/ingest.py` was required.

Tests: `pytest -k affinidad` → **27 passed**.

---

## (c) Production SQL (idempotent) — DO NOT auto-run; orchestrator runs via Supabase MCP

> Run on prod `sjiepibqadbdowcizccw`, schema `public`, table `pointers`.
> The target-set predicate is reused verbatim in every block.

### C1 — Collision pre-check (must return 0 rows)
Confirms no row already occupies the NEW Nzyme key for any target tail.

```sql
-- C1: collision pre-check. Expect ZERO rows. If any row returns, STOP.
SELECT p.canonical_key AS old_key,
       'company::baa52eca-4c88-4861-9d45-720e743febb4::' || split_part(p.canonical_key, '::', 3) AS new_key
FROM pointers p
WHERE p.type = 'company'
  AND p.metadata->>'source' = 'affinidad'
  AND p.acl @> ARRAY['baa52eca-4c88-4861-9d45-720e743febb4']::uuid[]
  AND NOT p.acl @> ARRAY['ca61f0e5-563e-5894-954f-38f5a9e0eabc']::uuid[]
  AND p.canonical_key LIKE 'company::ca61f0e5-%'
  AND EXISTS (
      SELECT 1 FROM pointers q
      WHERE q.canonical_key =
            'company::baa52eca-4c88-4861-9d45-720e743febb4::' || split_part(p.canonical_key, '::', 3)
  );
```
(Verified read-only on 2026-06-30: 0 collisions.)

### C2 — The UPDATE (rewrites exactly the 305; idempotent)
The `LIKE 'company::ca61f0e5-%'` guard makes a re-run a no-op: after the update the
rows no longer match it (their key now starts `company::baa52eca-`), so a second run
touches 0 rows even though the acl/source/type predicate still selects them.

```sql
-- C2: re-namespace the 305 Nzyme-exclusive companies Kibo->Nzyme, preserving tail.
UPDATE pointers
SET canonical_key =
      'company::baa52eca-4c88-4861-9d45-720e743febb4::' || split_part(canonical_key, '::', 3)
WHERE type = 'company'
  AND metadata->>'source' = 'affinidad'
  AND acl @> ARRAY['baa52eca-4c88-4861-9d45-720e743febb4']::uuid[]
  AND NOT acl @> ARRAY['ca61f0e5-563e-5894-954f-38f5a9e0eabc']::uuid[]
  AND canonical_key LIKE 'company::ca61f0e5-%';
-- Expect: UPDATE 305  (UPDATE 0 on any re-run).
```

### C3 — Post-update verification

```sql
-- C3a: rows now correctly keyed under Nzyme for the set (expect 305).
SELECT count(*) AS now_nzyme_keyed
FROM pointers
WHERE type = 'company' AND metadata->>'source' = 'affinidad'
  AND acl @> ARRAY['baa52eca-4c88-4861-9d45-720e743febb4']::uuid[]
  AND NOT acl @> ARRAY['ca61f0e5-563e-5894-954f-38f5a9e0eabc']::uuid[]
  AND canonical_key LIKE 'company::baa52eca-%';

-- C3b: no Nzyme-exclusive company still keyed under Kibo (expect 0).
SELECT count(*) AS still_kibo_keyed
FROM pointers
WHERE type = 'company' AND metadata->>'source' = 'affinidad'
  AND acl @> ARRAY['baa52eca-4c88-4861-9d45-720e743febb4']::uuid[]
  AND NOT acl @> ARRAY['ca61f0e5-563e-5894-954f-38f5a9e0eabc']::uuid[]
  AND canonical_key LIKE 'company::ca61f0e5-%';

-- C3c: the 29 shared companies untouched — still Kibo-keyed (expect 29).
SELECT count(*) AS shared_untouched
FROM pointers
WHERE type = 'company' AND metadata->>'source' = 'affinidad'
  AND acl @> ARRAY['ca61f0e5-563e-5894-954f-38f5a9e0eabc']::uuid[]
  AND acl @> ARRAY['baa52eca-4c88-4861-9d45-720e743febb4']::uuid[]
  AND canonical_key LIKE 'company::ca61f0e5-%';

-- C3d: no duplicate canonical_key introduced anywhere (expect 0 rows).
SELECT canonical_key, count(*) AS n
FROM pointers
GROUP BY canonical_key
HAVING count(*) > 1;
```

---

## (d) Dry-simulation of the fixed adapter logic

Ran against the live (fixed) code, ingest firm = Kibo:

```python
from pipeline.adapters.affinidad import _to_entity, AffinidadFirm, AffinidadAdapter
firm = AffinidadFirm(tenant_id="ca61f0e5-563e-5894-954f-38f5a9e0eabc", source_dsn="x")

rows = {
 "NZYME-only (domain)":    {"id":"f96a3fff-…","kind":"company","name":"Stay U-nique","domain":"stay-u-nique.com"},
 "SHARED":                 {"id":"abc","kind":"company","name":"Cofrai","domain":"cofrai.com"},
 "KIBO-only":              {"id":"def","kind":"company","name":"Welinq","domain":"welinq.fr"},
 "NZYME-only (no domain)": {"id":"172e68d8-…","kind":"company","name":"NoDomainCo","domain":None},
}
for label,row in rows.items():
    t = AffinidadAdapter._row_tenant(firm,row)
    print(label, _to_entity(t,row,{}).canonical_key)
```

Output:

```
NZYME-only (domain)     company::baa52eca-4c88-4861-9d45-720e743febb4::stay-u-nique.com      (acl→firm:NZYME)
SHARED                  company::ca61f0e5-563e-5894-954f-38f5a9e0eabc::cofrai.com            (acl→firm:KIBO)
KIBO-only               company::ca61f0e5-563e-5894-954f-38f5a9e0eabc::welinq.fr             (acl→firm:KIBO)
NZYME-only (no domain)  company::baa52eca-4c88-4861-9d45-720e743febb4::id:172e68d8-…         (acl→firm:NZYME)
```

The Nzyme-exclusive ones now yield the Nzyme namespace; the shared and Kibo-only
ones stay under Kibo. Key and acl agree, and the SQL above produces exactly these
keys for the existing 305.

---

## (e) Risks / edge cases

- **id-keyed companies (no domain) — 8 of the 305.** Re-namespaced by source id
  (`…::id:{entity_id}`); SQL preserves the whole `::id:{uuid}` tail via
  `split_part(canonical_key,'::',3)`. Adapter matches them via
  `NZYME_OWNED_ENTITY_IDS`. No special-casing needed in SQL.
- **Pre-existing duplicate domains (`bdeo.cio` vs `bdeo.io`).** Both are in the
  allowlist as two distinct companies. They get two **distinct** new keys
  (`…::bdeo.cio`, `…::bdeo.io`) and do **not** merge — `bdeo.cio` is almost
  certainly a source typo for `bdeo.io`, but de-duping is out of scope for this
  re-namespace and would require a separate merge decision. Flagging for follow-up.
- **No collisions / no merges.** Verified 0 rows already at any target Nzyme key,
  and no duplicate tails within the 305 → the UPDATE creates 305 fresh distinct
  keys; C3d guards globally.
- **Idempotency.** The `LIKE 'company::ca61f0e5-%'` clause makes C2 a no-op on
  re-run. The adapter is idempotent too: a re-ingest now writes the Nzyme key, so
  it upserts onto the re-namespaced row rather than re-creating a Kibo duplicate.
- **Allowlist drift (TODO).** The allowlist is a point-in-time snapshot of the 305.
  A genuinely new Nzyme-exclusive company added to the CRM later would (until the
  list-membership join lands) be keyed Kibo again — same class of bug, smaller
  blast radius. Tracked by `TODO(ownership-signal)` in `affinidad_nzyme_owned.py`.
- **Edges/attributes follow automatically.** Because `ent.tenant_id` now = Nzyme
  for these companies, future deal attributes write `firm:NZYME` and edge
  principals include Nzyme — consistent with the corrected key/acl. Existing edges
  in prod reference pointer **ids**, not canonical_keys, so the C2 key rewrite does
  not break any existing edge.
```
