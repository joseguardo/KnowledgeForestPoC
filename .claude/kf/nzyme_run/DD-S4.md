# DD-S4 + S5 — Reconciliation & integrated coherency — **PASS**

Date: 2026-06-30 · Prod `sjiepibqadbdowcizccw` · Verified by orchestrator via MCP `execute_sql`.

## DD-S4 (reconciliation)
| check | expected | actual | verdict |
|---|---|---|---|
| edges created (run) | ~110 | 110 (66 opp + 44 co) | ✅ |
| unresolved edge endpoints | 0 | 0 | ✅ |
| opportunity_documents → opportunity | 66 | 66 | ✅ |
| company_documents → company | 44 | 44 | ✅ |
| Nzyme-exclusive co targets use new key | baa52eca | `Arjile`,`Bip&Drive` → baa52eca | ✅ |
| shared co targets keep old key | ca61f0e5 | `Civislend`,`White Vega` → ca61f0e5 | ✅ |
| idempotency | 409-skip on re-run | already_exists=22107 | ✅ |

## S5 (integrated coherency, whole subgraph)
| check | expected | actual | verdict |
|---|---|---|---|
| global duplicate canonical_key | 0 | 0 | ✅ |
| dangling edge source / target | 0 / 0 | 0 / 0 | ✅ |
| Nzyme skeleton pointers | 22,109 | 22,109 | ✅ |
| Nzyme outgoing edges | 22,217 | 22,217 | ✅ |
| reconciliation edges w/ bad target type | 0 | 0 | ✅ |
| Nzyme-only companies still Kibo-keyed | 0 | 0 | ✅ |

**Gate: PIPELINE GREEN.** All five steps (S1–S4) + integrated DD pass.
