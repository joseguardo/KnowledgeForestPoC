# DD-S3 — Re-namespace 305 Nzyme-only companies — **PASS**

Date: 2026-06-30 · Prod `sjiepibqadbdowcizccw` · Verified by orchestrator via MCP `execute_sql`.
Reviews `HANDOVER-S3.md`. Mutation = the C2 UPDATE; code change = `affinidad.py` + `affinidad_nzyme_owned.py`.

## Pre-flight
- **C1 collision pre-check** → 0 rows. No target Nzyme key already occupied. ✅

## Post-update data checks (C3 + FK integrity)
| check | expected | actual | verdict |
|---|---|---|---|
| Nzyme-exclusive companies now keyed `company::baa52eca-%` | 305 | **305** | ✅ |
| Nzyme-exclusive still keyed `company::ca61f0e5-%` | 0 | **0** | ✅ |
| Shared (both-tenant) companies untouched (still Kibo-keyed) | 29 | **29** | ✅ |
| Global duplicate canonical_key | 0 | **0** | ✅ |
| Edges with dangling source id | 0 | **0** | ✅ |
| Edges with dangling target id | 0 | **0** | ✅ |
| Spot: `arjile.co` re-keyed to Nzyme + edges retained | key=baa52eca, 3 edges | **baa52eca, 3** | ✅ |

FK integrity holds because `edges` reference pointer **ids**, which the key rewrite never touched.

## Code-change verdict
- Adapter routes Nzyme-owned companies (allowlist `affinidad_nzyme_owned.is_nzyme_owned`) to the
  Nzyme tenant for BOTH key and acl; shared/Kibo companies unchanged. `pytest -k affinidad` → 27 passed.
- Dry-simulation (in handover): Nzyme-only → `company::baa52eca-…`; shared/Kibo-only → `company::ca61f0e5-…`. ✅
- Idempotency: C2 guarded by `LIKE 'company::ca61f0e5-%'` → re-run is a no-op; adapter re-ingest now
  upserts onto the Nzyme-keyed row (no Kibo dup re-creation).

## Carry-forward (non-blocking)
- Allowlist is a point-in-time snapshot (`TODO(ownership-signal)`): replace with a
  `crm_list_entries → crm_lists` join so new Nzyme-exclusive companies key correctly automatically.
- Pre-existing source dupes (`bdeo.cio`/`bdeo.io`, `Room007Hostels` ×2, `Union/Unión Financiera`)
  get distinct keys; not merged here — separate dedup decision.

**Gate: S3 GREEN.** Reconciliation (S4) may now target the corrected company keys (resolver fetches
the index live at run time).
