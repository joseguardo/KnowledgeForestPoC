# Phase B Audit: Edge Functions + Seed Data

**Auditor**: Claude Opus 4.6 (fresh context, no prior conversation)
**Date**: 2026-06-10
**Project**: `rkuyvzcxaoulhjiflrmp` (eu-central-1)

---

## Summary

Phase B is **PASS**. All 4 Edge Functions are deployed and ACTIVE. All 58 pointers, 93 edges, and 75 attributes are correctly seeded with deterministic UUIDs. The `get_tenant_forest` RPC returns 13 trees whose structure exactly matches what `buildScene.js` expects. The `get_pointer_subgraph` RPC works correctly for all tested pointer types (company, person, regulation). No blocking issues found. No fixes required.

---

## Verification Steps (Handover Steps 1-5)

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Table counts | **PASS** | pointers=58, edges=93, attributes=75, tenants=1, tenant_trees=13, tenant_branches=58. All match handover expectations exactly. |
| 2 | `get_tenant_forest` returns 13 trees | **PASS** | `jsonb_array_length` = 13 |
| 3 | First tree shape matches buildScene.js | **PASS** | Returns `{ id, label, subtitle, type, pos, is_seed, version, branches: [{ id, name, leaves, links, pointer_ids }] }` |
| 4 | Edge Functions deployed | **PASS** | All 4 ACTIVE: `insert-pointer`, `link-pointers`, `log-query-path`, `compute-forest`. All have `verify_jwt: true`. |
| 5 | `get_pointer_subgraph` for NVIDIA | **PASS** | Returns pointer, 3 attributes (Rev, PE, CEO), 1 outbound edge (to AI Infrastructure), 2 inbound edges (Jensen Huang CEO, United States HQ). |

---

## Correctness

### get_pointer_subgraph tested for 3+ types

| Pointer | Type | Result | Notes |
|---------|------|--------|-------|
| NVIDIA | company | **PASS** | 3 attributes, 1 outbound (primary_sector -> AI Infra), 2 inbound (ceo from Jensen Huang, hq_location from United States) |
| George Kurtz | person | **PASS** | 2 attributes (Title, Location), 2 outbound (ceo -> CrowdStrike, related -> Jensen Huang), 0 inbound |
| GDPR | regulation | **PASS** | 3 attributes (Scope, Enacted, Max fine), 3 outbound (jurisdiction -> Europe, related -> Cybersecurity, related -> CrowdStrike), 2 inbound (related from Europe, ensures_compliance from Security Practices) |

### Edge relationship_types verified

| Relationship | Example | Semantic correctness |
|-------------|---------|---------------------|
| `primary_sector` | company -> sector | **CORRECT** (CrowdStrike -> Cybersecurity, NVIDIA -> AI Infra, etc.) |
| `ceo` | person -> company | **CORRECT** (Kurtz -> CrowdStrike, Cook -> Apple, Collison -> Stripe, Huang -> NVIDIA) |
| `competitor` | company -> company | **CORRECT** (CrowdStrike -> Wiz) |
| `hq_location` | geography -> company | **CORRECT** (Spain -> Factorial, US -> CrowdStrike/Stripe/NVIDIA) |
| `jurisdiction` | regulation -> geography | **CORRECT** (GDPR -> Europe, SEC -> US) |
| `ensures_compliance` | best_practice -> regulation | **CORRECT** (Security Practices -> GDPR) |
| `related` | various | **ACCEPTABLE** (used as catch-all for person-person, sector-sector, geo-regulation links) |
| `uses_skill` | agent -> skill | **CORRECT** (10 edges) |
| `guides` | best_practice -> agent/component | **CORRECT** (6 edges) |
| `follows` | skill -> best_practice | **CORRECT** (Report Gen -> Prompt Design) |

All 26 distinct relationship_types make semantic sense for their source/target pairs.

### Tree structure correctness (all 13 trees)

| Tree | Label | Subtitle | Type | Pos | Branch Count | Matches trees.js? |
|------|-------|----------|------|-----|-------------|-------------------|
| SECTOR TREE | SECTOR TREE | Sectors | entity | [-22,0,-7] | 5 | **YES** |
| COMPANY TREE | COMPANY TREE | Companies | entity | [0,0,-16] | 10 | **YES** |
| PEOPLE TREE | PEOPLE TREE | People | entity | [22,0,-7] | 4 | **YES** |
| GEOGRAPHY TREE | GEOGRAPHY TREE | Geographies | entity | [-32,0,-18] | 4 | **YES** |
| REGULATION TREE | REGULATION TREE | Regulation | entity | [22,0,-22] | 4 | **YES** |
| COMPONENT TREE | COMPONENT TREE | Components | system | [-29,0,11] | 4 | **YES** |
| AGENT TREE | AGENT TREE | Agents | system | [-25,0,25] | 4 | **YES** |
| SKILL TREE | SKILL TREE | Skills | system | [-11,0,32] | 4 | **YES** |
| TOOL TREE | TOOL TREE | Tools | system | [11,0,32] | 5 | **YES** |
| FLOW TREE | FLOW TREE | Flows | system | [25,0,25] | 4 | **YES** |
| TREES TREE | TREES TREE | Trees (Meta) | system | [32,0,-7] | 2 | **YES** |
| BEST PRACTICES TREE | BEST PRACTICES TREE | Best Practices | system | [-32,0,0] | 4 | **YES** |
| ARCHITECTURE TREE | ARCHITECTURE TREE | Architecture | system | [29,0,11] | 4 | **YES** |

---

## Completeness

### Pointer count by type (all 58 represented)

| Type | Count | Expected from trees.js | Match? |
|------|-------|----------------------|--------|
| company | 10 | 10 | **YES** |
| sector | 5 | 5 | **YES** |
| tool | 5 | 5 | **YES** |
| flow | 4 | 4 | **YES** |
| architecture | 4 | 4 | **YES** |
| component | 4 | 4 | **YES** |
| geography | 4 | 4 | **YES** |
| agent | 4 | 4 | **YES** |
| regulation | 4 | 4 | **YES** |
| best_practice | 4 | 4 | **YES** |
| person | 4 | 4 | **YES** |
| skill | 4 | 4 | **YES** |
| meta | 2 | 2 | **YES** |
| **Total** | **58** | **58** | **YES** |

### Cross-links spot-checked (5 of 93)

| # | Source | Target | Expected relationship | Found? | Correct why? |
|---|--------|--------|----------------------|--------|-------------|
| 1 | Cybersecurity | AI Infrastructure | sector-sector link | **YES** | "AI powers next-gen threat detection..." |
| 2 | CrowdStrike | Wiz | competitor | **YES** | "Direct competitor in cloud security..." |
| 3 | Tim Cook | Apple | ceo | **YES** | "CEO since 2011, succeeded Steve Jobs" |
| 4 | Tim Cook | Patrick Collison | related | **YES** | "Apple Pay partnership..." |
| 5 | Tim Cook | Jensen Huang | related | **YES** | "Silicon Valley peers..." |

Additional spot-checks also passed: Fintech -> Consumer Tech, Seedtag -> Consumer Tech + AI Infra, Jobandtalent -> Consumer Tech, Clarity AI -> AI Infra, GDPR -> Europe + Cybersecurity + CrowdStrike, Report Generation -> Prompt Design.

### Bidirectional links verified

Where trees.js has mutual links (A links to B and B links to A), both directional edges exist:
- Europe -> GDPR (`related`) AND GDPR -> Europe (`jurisdiction`) -- **PASS**
- United States -> SEC (`related`) AND SEC -> United States (`jurisdiction`) -- **PASS**

### Total link count from forest output: 93

The forest output's total links across all branches = 93, matching the 93 edges in the database exactly.

### Attributes (75 total)

All 75 attributes are correctly parsed from the "Key: Value" format in trees.js leaves:
- Only entity tree pointers have attributes (sectors, companies, people, geographies, regulations)
- System tree pointers have 0 attributes (confirmed as Known Issue #5 in handover)
- All attributes have: `source: "seed"`, `data_type: "string"`, correct `sort_order`
- No malformed key/value splits detected

### Canonical keys

| Company | Canonical Key | Correct? |
|---------|--------------|----------|
| CrowdStrike | CRWD | **YES** |
| Apple | AAPL | **YES** |
| NVIDIA | NVDA | **YES** |
| Moderna | MRNA | **YES** |
| Wiz | null | **YES** (private) |
| Stripe | null | **YES** (private) |
| Factorial | null | **YES** (private) |
| Jobandtalent | null | **YES** (private) |
| Clarity AI | null | **YES** (private) |
| Seedtag | null | **YES** (private) |

---

## Data Quality

| Check | Result | Notes |
|-------|--------|-------|
| Orphan pointers (no edges) | **PASS** | 0 orphans. Every pointer has at least one edge. |
| Edges to non-existent pointers | **PASS** | 0 dangling edges. All source_id and target_id reference existing pointers. |
| COMPANY TREE has all 10 companies | **PASS** | CrowdStrike, Wiz, Apple, Stripe, NVIDIA, Moderna, Factorial, Jobandtalent, Clarity AI, Seedtag |
| Geography -> company edges sensible | **PASS** | Spain -> Factorial (HQ Barcelona), Spain -> Seedtag (HQ Madrid), US -> CrowdStrike (HQ Austin), US -> Stripe (HQ SF), US -> NVIDIA (HQ Santa Clara). All 5 correct. |
| Null relationship_types | **PASS** | 0 edges with NULL relationship_type |
| Null why fields | **PASS** | 0 edges with NULL why |
| Link IDs in forest reference real pointers | **PASS** | All link IDs in the forest output resolve to existing pointers (0 missing) |
| Embeddings | **N/A** | All NULL as documented in Known Issue #1 |

---

## Interface Contracts

### `get_tenant_forest()` output vs. buildScene.js expectations

| Field | buildScene.js expects | get_tenant_forest returns | Compatible? |
|-------|----------------------|--------------------------|-------------|
| `trees[i].id` | any identifier | UUID string | **YES** |
| `trees[i].label` | string | string (e.g., "SECTOR TREE") | **YES** |
| `trees[i].subtitle` | string | string (e.g., "Sectors") | **YES** |
| `trees[i].type` | "entity" or "system" | "entity" or "system" | **YES** |
| `trees[i].pos` | array of 3 numbers [x,y,z] | JSON array of 3 numbers | **YES** |
| `branches[j].id` | any identifier | UUID string | **YES** |
| `branches[j].name` | string | string | **YES** |
| `branches[j].leaves` | string array | string array (e.g., ["Rev: $3.06B", "PE: 7.8", "CEO: Kurtz"]) | **YES** |
| `branches[j].links` | array of `{id, why}` | array of `{id, why}` | **YES** |

### pos format verification (all 13 trees)

All 13 trees return `pos` as a JSON array of exactly 3 elements, each of type `number`. No strings, no nulls.
Positions match trees.js exactly (e.g., SECTOR TREE = [-22,0,-7], COMPANY TREE = [0,0,-16]).

### Extra fields in output (non-breaking)

The output includes `is_seed` (boolean), `version` (integer), and `pointer_ids` (UUID array) which are not in trees.js but are harmless additions that `buildScene.js` will simply ignore. **PASS** -- no breaking contract violations.

### leaves format

Entity tree leaves are formatted as `"Key: Value"` strings matching the trees.js format. System tree branches return empty `leaves: []` arrays (not null), which is safe for array iteration.

---

## Blocking Issues Found

**None.**

---

## Non-Blocking Issues

### 1. System tree attributes not seeded (Known Issue #5 in handover)

System trees (Agents, Skills, Tools, Flows, Components, Architecture, Best Practices, Trees Meta) have leaves in trees.js (e.g., "Type: core", "Runtime: Node.js", "Manages agent lifecycle") but these were not parsed into `attributes_kv`. As a result, all 31 system tree branches return `leaves: []` in the forest output. This means the 3D visualization will show system tree branches without any leaf detail.

**Impact**: Visual regression for system trees compared to the hardcoded trees.js. Entity trees (the primary business data) are unaffected.

**Recommendation**: Either seed the system tree attributes in a follow-up, or accept that system trees are display-only placeholders until dynamic data replaces them.

### 2. `related` used as catch-all relationship type (18 of 93 edges)

Many edges use the generic `related` type where a more specific type could be useful:
- Person-to-person links: Cook -> Collison ("Apple Pay partnership") could be `business_partnership`
- Person-to-person links: Cook -> Huang ("Silicon Valley peers") could be `industry_peer`
- Geography-to-regulation links: Europe -> GDPR could be `governed_by` instead of `related`
- Sector-to-sector links: Cybersecurity -> AI Infra could be `synergy` or `complementary`

**Impact**: None for MVP. These types are display/filtering metadata only. The `why` field provides the context.

### 3. No embeddings in seed data

All 58 pointers have `embedding: null`. This means the embedding-based dedup tier will not function until embeddings are backfilled. Only trigram matching and canonical key matching will work for dedup.

**Impact**: Documented in handover Known Issue #1. Non-blocking for MVP seed data, but must be addressed before production inserts.

### 4. Bidirectional links create 2 edges

When both sides of a relationship define links to each other in trees.js (e.g., Europe -> GDPR and GDPR -> Europe), 2 separate edges are created. This is correct behavior (they are directional edges with different relationship_types and different `why` text), but the forest output's `links` array only shows outbound edges from each branch's pointer. This means the Cybersecurity branch shows a link to AI Infrastructure, but the AI Infrastructure branch does NOT show a reciprocal link to Cybersecurity (because in trees.js, AI Infra has no outbound links). This is faithful to the source data.

---

## Residual Items for Human Review

1. **OpenAI API key**: Still not in Supabase vault (noted in Phase A audit as well). Edge Functions will gracefully degrade but full embedding/naming functionality requires this key.

2. **System tree leaves**: Decide whether to seed system tree attributes before Phase C, or accept empty leaves for system branches. If the frontend relies on leaf data for tooltips or info panels, empty system branches could look broken.

3. **Edge Function testing**: This audit verified the functions are deployed and ACTIVE but did not invoke them via HTTP (they require JWT authentication). End-to-end HTTP testing should be done when the frontend is wired up in Phase C.

---

## Test Data Status

Seed data is in place and verified. No test data cleanup needed. Tables contain production-ready seed data:
- 58 pointers, 93 edges, 75 attributes
- 1 tenant (Kibo), 13 tenant_trees, 58 tenant_branches
- 2 system_config rows (dedup thresholds from Phase A)
