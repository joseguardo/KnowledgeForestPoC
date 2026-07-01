# Cross-Tenant Calendar Merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make calendar meetings one graph node per real-world meeting (not one-per-firm), by keying them firm-neutrally and letting the `acl` array carry multi-tenant visibility — then merge the existing per-tenant duplicates and delete the garbage recurring-series nodes.

**Architecture:** Tenancy in this DB is *not* a column on `pointers`; it is a tenant UUID present as a principal inside `pointers.acl` / `edges.acl` (queries scope with `acl @> '{tenant_id}'`, see `supabase_rest.py:127`). Persons are already firm-neutral (`person::{email}`, one node whose `acl` lists every tenant that can see them). Calendar is the outlier: `event_key`/`series_key` bake the tenant into the `canonical_key`, forcing a separate node per firm for the *same* Google event. Fix = drop the tenant from calendar keys (aligning them with the person model), so `insert_pointer_with_dedup` finds the existing node on the second firm's ingest and just **unions the acl** (both tenant UUIDs end up on one node). A one-time SQL migration collapses the ~490 existing cross-tenant pairs and the 217 malformed series nodes the same way.

**Tech Stack:** Python 3 pipeline (`pipeline/`), pytest, Supabase Postgres 17 (project `sjiepibqadbdowcizccw`), SQL migrations under `supabase/migrations/`.

## Global Constraints

- Calendar canonical keys after this change: meeting = `communication:gcal:{iCalUID}`, series = `communication:gcal-series:{recurringEventId}`. **No tenant segment.**
- `iCalUID` and `recurringEventId` must be normalized before keying: strip a trailing `@google.com`; for the series id also strip any trailing `_R<digits>[T<digits>]` recurrence-instance suffix (a series id must never contain `_R…`).
- The `:gcal:` / `:gcal-series:` markers must survive (both `event_sync.py` and `check_duplicates` discriminate on the substring `:gcal`).
- Tenancy is `acl @> '{tenant_id}'`. A merge **unions** the acl of every duplicate so the survivor is visible to every firm that had a copy. Never drop a tenant UUID from an acl during merge.
- Meeting **bodies/attachments** carry their own per-participant acl (separate rows) — the meeting-node merge must not touch them; body visibility stays as-is.
- Scope is **calendar only**. Companies (`company::{tenant}::{domain}`) are also tenant-scoped but are out of scope here — noted as a follow-up in Task 6.
- Every FK table that references `pointers(id)` is `ON DELETE CASCADE`, so losers MUST be re-pointed before deletion or their edges/attributes vanish. FK tables to re-point: `edges(source_id,target_id)`, `attributes_kv(pointer_id)`, `document_chunks(pointer_id)`, `timeseries_data(pointer_id)`, `attribute_history(pointer_id)`, `duplicate_flags(pointer_id_a,pointer_id_b)`, `tenant_coaccess(pointer_a,pointer_b)`. (`tenant_pointer_assignments` is empty — ignore.)
- The data migration is destructive and runs against live prod. It MUST be executed first on a Supabase **branch** (`create_branch`), verified, then merged — never applied directly.

---

## File Structure

- `pipeline/pipeline/adapters/calendar_entities.py` — `event_key` / `series_key` become firm-neutral + normalized. (Modify)
- `pipeline/tests/test_adapters/test_calendar_entities.py` — key-shape tests. (Modify)
- `pipeline/pipeline/event_sync.py` — verify tenant-scoped convergence still works against firm-neutral, multi-tenant-acl calendar nodes. (Modify only if a test fails.)
- `pipeline/tests/test_event_sync.py` — regression test locking cross-tenant behavior. (Modify)
- `supabase/migrations/20260701120000_calendar_firmneutral_merge.sql` — one-time normalize + merge. (Create)

---

### Task 1: Firm-neutral, normalized calendar keys

**Files:**
- Modify: `pipeline/pipeline/adapters/calendar_entities.py:43-53` (`event_key`, `series_key`) and their call sites at `:114` and `:133`.
- Test: `pipeline/tests/test_adapters/test_calendar_entities.py`

**Interfaces:**
- Produces: `event_key(ical_uid: str) -> str` → `"communication:gcal:{normalized_uid}"`; `series_key(recurring_event_id: str) -> str` → `"communication:gcal-series:{normalized_series_id}"`. Both drop the `tenant` parameter. `_normalize_gcal_id` and `_normalize_series_id` module helpers.

- [ ] **Step 1: Write the failing tests**

```python
# in test_calendar_entities.py
from pipeline.adapters.calendar_entities import event_key, series_key

def test_event_key_is_firm_neutral_and_strips_google_suffix():
    assert event_key("abc123@google.com") == "communication:gcal:abc123"
    # occurrence iCalUID keeps its _R instance suffix (distinct occurrence identity)
    assert event_key("abc123_R20260223T150000@google.com") == "communication:gcal:abc123_R20260223T150000"

def test_series_key_is_firm_neutral_and_strips_instance_suffix():
    assert series_key("abc123") == "communication:gcal-series:abc123"
    # a recurringEventId that leaked an instance suffix must collapse to the bare series id
    assert series_key("abc123_R20260223T150000") == "communication:gcal-series:abc123"
    assert series_key("abc123@google.com") == "communication:gcal-series:abc123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pipeline && python -m pytest tests/test_adapters/test_calendar_entities.py -k "firm_neutral" -v`
Expected: FAIL — current `event_key` requires 2 args and includes the tenant.

- [ ] **Step 3: Implement the firm-neutral keys**

```python
# calendar_entities.py — replace lines 43-53
import re

_GOOGLE_SUFFIX = re.compile(r"@google\.com$")
_INSTANCE_SUFFIX = re.compile(r"_R\d{8}(T\d{6})?$")


def _normalize_gcal_id(ical_uid: str) -> str:
    """Occurrence identity: drop the `@google.com` suffix so the same occurrence
    keys identically regardless of which extraction produced it. The `_R…`
    instance suffix is part of an occurrence's identity and is kept."""
    return _GOOGLE_SUFFIX.sub("", ical_uid or "")


def _normalize_series_id(recurring_event_id: str) -> str:
    """Series identity: drop `@google.com` AND any `_R…` instance suffix — a
    series parent is one node per recurring meeting, never per occurrence."""
    return _INSTANCE_SUFFIX.sub("", _GOOGLE_SUFFIX.sub("", recurring_event_id or ""))


def event_key(ical_uid: str) -> str:
    """Firm-neutral canonical key for a calendar meeting node, keyed by its
    (normalized) iCalUID. One node per real meeting across all firms; the
    `acl` array carries which tenants/people may see it. `:gcal:` marks the
    Google-Calendar source (event_sync discriminates on it)."""
    return f"communication:gcal:{_normalize_gcal_id(ical_uid)}"


def series_key(recurring_event_id: str) -> str:
    """Firm-neutral canonical key for a recurring-meeting *series* node, keyed
    by Google's (normalized) recurringEventId so every occurrence groups under
    one series shared across firms."""
    return f"communication:gcal-series:{_normalize_series_id(recurring_event_id)}"
```

Update the two call sites:
```python
# line ~114
event_ck = event_key(ev.ical_uid)
# line ~133
series_ck = series_key(ev.recurring_event_id)
```

Also update the module docstring lines 10 and 50-53 to say `communication:gcal:{iCalUID}` / `communication:gcal-series:{recurringEventId}` (no `{tenant}`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd pipeline && python -m pytest tests/test_adapters/test_calendar_entities.py -v`
Expected: PASS (fix any other tests in that file that passed `tenant` into `event_key`/`series_key` — drop the argument).

- [ ] **Step 5: Commit**

```bash
git add pipeline/pipeline/adapters/calendar_entities.py pipeline/tests/test_adapters/test_calendar_entities.py
git commit -m "feat(calendar): firm-neutral, normalized calendar canonical keys"
```

---

### Task 2: Lock cross-tenant convergence behavior in event_sync

**Files:**
- Read/verify: `pipeline/pipeline/event_sync.py:110-175`, `pipeline/pipeline/supabase_rest.py:112-130`.
- Test: `pipeline/tests/test_event_sync.py`

**Interfaces:**
- Consumes: `search_pointers(..., tenant_id=<uuid>)` which filters `acl @> '{tenant_id}'` (`supabase_rest.py:127`).

**Rationale (no code change expected):** After Task 1 a shared meeting is one node whose `acl` contains *both* tenant UUIDs (via the merge in Task 3 / via acl-union on live re-ingest). `event_sync`'s tenant-scoped searches (`tenant_id=...`) therefore still match it for either firm, and the `:gcal` substring guards (`event_sync.py:134,169`) are unaffected because the marker survives. This task proves that with a test; only touch `event_sync.py` if the test fails.

- [ ] **Step 1: Write the regression test**

```python
# test_event_sync.py — a firm-neutral calendar node carrying two tenant UUIDs
# in its acl is discoverable when scoping by EITHER tenant.
def test_shared_calendar_node_visible_to_both_tenants(fake_http_with_pointers):
    tenant_a = "baa52eca-4c88-4861-9d45-720e743febb4"
    tenant_b = "ca61f0e5-563e-5894-954f-38f5a9e0eabc"
    node = {
        "id": "11111111-1111-1111-1111-111111111111",
        "canonical_key": "communication:gcal:abc123",
        "type": "communication",
        "acl": [tenant_a, tenant_b],
        "occurred_at": "2026-02-02T15:00:00+00:00",
    }
    http = fake_http_with_pointers([node])
    from pipeline.supabase_rest import search_pointers
    assert search_pointers(http, ptype="communication", tenant_id=tenant_a)
    assert search_pointers(http, ptype="communication", tenant_id=tenant_b)
```

If `fake_http_with_pointers` does not exist, assert on the request filters instead: call `search_pointers(http, ptype="communication", tenant_id=tenant_a)` against a recording fake and assert the outgoing query contains `acl=cs.{%s}` % tenant_a and `type=eq.communication`.

- [ ] **Step 2: Run the test**

Run: `cd pipeline && python -m pytest tests/test_event_sync.py -k "both_tenants" -v`
Expected: PASS. If FAIL, inspect whether `search_pointers` builds the `acl @> '{tenant}'` filter as in `supabase_rest.py:127`; fix the filter, not the test.

- [ ] **Step 3: Commit**

```bash
git add pipeline/tests/test_event_sync.py
git commit -m "test(event_sync): shared firm-neutral calendar node visible to both tenants"
```

---

### Task 3: One-time normalize + merge migration (on a branch)

**Files:**
- Create: `supabase/migrations/20260701120000_calendar_firmneutral_merge.sql`

**Interfaces:**
- Consumes: the FK table list from Global Constraints. Operates only on rows where `type='communication' AND canonical_key LIKE 'communication:%:gcal%'` (the *old*, tenant-bearing calendar keys).

**Approach:** Compute each old calendar node's new firm-neutral key; the survivor per new-key is the earliest `created_at` (tie-break `id`); union all losers' acls into the survivor; re-point every FK table from loser→survivor; dedupe edges that collide after re-pointing (union their acls); rewrite the survivor's `canonical_key` to the new key; delete losers.

- [ ] **Step 1: Create a Supabase branch and point the tooling at it**

Use the Supabase MCP `create_branch` on project `sjiepibqadbdowcizccw`. All of Step 2–4 run against the **branch**, not prod.

- [ ] **Step 2: Write the migration**

```sql
-- 20260701120000_calendar_firmneutral_merge.sql
-- Collapse per-tenant calendar duplicates into one firm-neutral node whose acl
-- is the union of every firm's copy. Also fixes malformed gcal-series:<id>_R…
-- nodes (a series must never carry a per-occurrence suffix). Idempotent: after
-- it runs, all calendar keys already match `communication:gcal…` and the
-- selection set is empty on a re-run.
begin;

-- 1. New firm-neutral key per existing calendar node.
create temp table cal_new on commit drop as
select
  p.id,
  p.acl,
  p.created_at,
  case
    when p.canonical_key like 'communication:%:gcal-series:%'
      then 'communication:gcal-series:' ||
           regexp_replace(regexp_replace(split_part(p.canonical_key,':',4),'@google\.com$',''),'_R\d{8}(T\d{6})?$','')
    else 'communication:gcal:' ||
           regexp_replace(split_part(p.canonical_key,':',4),'@google\.com$','')
  end as newkey
from pointers p
where p.type='communication' and p.canonical_key like 'communication:%:gcal%';

-- 2. Survivor per new key (earliest created; stable tie-break on id).
create temp table cal_map on commit drop as
select c.id as loser,
       first_value(c.id) over (partition by c.newkey order by c.created_at, c.id) as survivor,
       c.newkey
from cal_new c;

-- 3. Union every loser's acl into its survivor.
update pointers s set
  acl = (select array(select distinct e from unnest(s.acl ||
           coalesce((select array_agg(x) from cal_map m
                       join pointers l on l.id=m.loser
                       cross join lateral unnest(l.acl) x
                      where m.survivor=s.id), '{}'::uuid[])) e)),
  updated_at = now()
from (select distinct survivor from cal_map) d
where s.id = d.survivor;

-- 4. Re-point every FK table from loser -> survivor (survivor rows skip self).
update edges e set source_id=m.survivor from cal_map m where e.source_id=m.loser and m.loser<>m.survivor;
update edges e set target_id=m.survivor from cal_map m where e.target_id=m.loser and m.loser<>m.survivor;
update attributes_kv a  set pointer_id=m.survivor from cal_map m where a.pointer_id=m.loser and m.loser<>m.survivor;
update document_chunks d set pointer_id=m.survivor from cal_map m where d.pointer_id=m.loser and m.loser<>m.survivor;
update timeseries_data t set pointer_id=m.survivor from cal_map m where t.pointer_id=m.loser and m.loser<>m.survivor;
update attribute_history h set pointer_id=m.survivor from cal_map m where h.pointer_id=m.loser and m.loser<>m.survivor;

-- duplicate_flags / tenant_coaccess use a<b column pairs: re-point then let the
-- self/duplicate rows fall out via the dedupe + delete below. Re-point both sides.
update duplicate_flags f set pointer_id_a=m.survivor from cal_map m where f.pointer_id_a=m.loser and m.loser<>m.survivor;
update duplicate_flags f set pointer_id_b=m.survivor from cal_map m where f.pointer_id_b=m.loser and m.loser<>m.survivor;
update tenant_coaccess t set pointer_a=m.survivor from cal_map m where t.pointer_a=m.loser and m.loser<>m.survivor;
update tenant_coaccess t set pointer_b=m.survivor from cal_map m where t.pointer_b=m.loser and m.loser<>m.survivor;

-- 5. Dedupe edges that now collide (union acl into the kept row, drop the rest).
--    An edge is identified by (source_id, target_id, relationship_type).
with ranked as (
  select id, source_id, target_id, relationship_type, acl,
         row_number() over (partition by source_id, target_id, relationship_type order by created_at, id) rn,
         first_value(id) over (partition by source_id, target_id, relationship_type order by created_at, id) keep_id
  from edges
)
update edges e set acl = (
  select array(select distinct x from unnest(
    coalesce(e.acl,'{}'::uuid[]) ||
    coalesce((select array_agg(y) from ranked r cross join lateral unnest(r.acl) y where r.keep_id=e.id),'{}'::uuid[])) x))
from ranked k where k.keep_id=e.id and k.rn=1;

delete from edges e using (
  select id from (
    select id, row_number() over (partition by source_id, target_id, relationship_type order by created_at, id) rn
    from edges
  ) z where z.rn>1
) dup where e.id=dup.id;

-- Drop self-referential / now-duplicate duplicate_flags & tenant_coaccess rows.
delete from duplicate_flags where pointer_id_a = pointer_id_b;
delete from tenant_coaccess  where pointer_a   = pointer_b;
delete from duplicate_flags a using duplicate_flags b
  where a.ctid > b.ctid and a.pointer_id_a=b.pointer_id_a and a.pointer_id_b=b.pointer_id_b;
delete from tenant_coaccess a using tenant_coaccess b
  where a.ctid > b.ctid and a.pointer_a=b.pointer_a and a.pointer_b=b.pointer_b;

-- 6. Rewrite survivor keys to the firm-neutral form, then delete losers.
update pointers s set canonical_key=m.newkey, updated_at=now()
from (select distinct survivor, newkey from cal_map) m
where s.id=m.survivor and s.canonical_key<>m.newkey;

delete from pointers p using cal_map m where p.id=m.loser and m.loser<>m.survivor;

commit;
```

- [ ] **Step 3: Run verification queries on the branch**

Run each; confirm the expected result:

```sql
-- (a) No calendar key still carries a tenant segment.
select count(*) from pointers
 where type='communication' and canonical_key like 'communication:%:gcal%'
   and canonical_key !~ '^communication:gcal(-series)?:';
-- Expected: 0

-- (b) No malformed series node remains.
select count(*) from pointers where canonical_key ~ 'gcal-series:.*_R\d';
-- Expected: 0

-- (c) Every firm-neutral calendar key is now unique (no residual dupes).
select count(*) - count(distinct canonical_key)
  from pointers where type='communication' and canonical_key like 'communication:gcal%';
-- Expected: 0

-- (d) No orphaned / dangling edges (all endpoints resolve).
select count(*) from edges e
  where not exists (select 1 from pointers where id=e.source_id)
     or not exists (select 1 from pointers where id=e.target_id);
-- Expected: 0

-- (e) Spot-check: the "Int.VC Institutional Partner Network" meeting is now ONE
--     node whose acl contains BOTH tenant UUIDs.
select canonical_key, cardinality(acl) acl_size,
       acl @> array['baa52eca-4c88-4861-9d45-720e743febb4'::uuid,
                    'ca61f0e5-563e-5894-954f-38f5a9e0eabc'::uuid] both_tenants
from pointers where label='Int.VC Institutional Partner Network';
-- Expected: exactly 1 row, both_tenants = true
```

- [ ] **Step 4: Merge the branch to prod (only if all checks pass)**

Use Supabase MCP `merge_branch`. If any check fails, `delete_branch` and revise the migration — do NOT merge.

- [ ] **Step 5: Commit the migration file**

```bash
git add supabase/migrations/20260701120000_calendar_firmneutral_merge.sql
git commit -m "fix(db): merge cross-tenant calendar dupes into firm-neutral nodes"
```

---

### Task 4: Re-ingest smoke test — prove idempotency

**Files:** none (operational verification).

- [ ] **Step 1: Re-run one firm's calendar connector for a small window** (e.g. one week already ingested) against prod after Tasks 1 & 3 are live.

- [ ] **Step 2: Verify no new calendar nodes were created for that window**

```sql
select count(*) from pointers
 where canonical_key like 'communication:gcal%'
   and created_at > now() - interval '10 minutes';
-- Expected: 0 (all events matched existing firm-neutral nodes; acl unioned in place)
```

- [ ] **Step 3: Verify a re-ingested shared meeting still carries both tenants**

Re-check query (e) from Task 3 for a meeting in the re-ingested window. Expected: still one node, `both_tenants = true`.

---

### Task 5: Drop the dead pre-ACL overload (housekeeping)

**Files:**
- Create: `supabase/migrations/20260701130000_drop_legacy_insert_pointer_overload.sql`

**Rationale:** Two overloads of `insert_pointer_with_dedup` exist; the 6-arg one (`…, p_access_class text)` without `p_acl`) still inserts into the dropped `access_class_id` column and will error if PostgREST ever resolves to it. Only the 7-arg `p_acl uuid[]` overload is live.

- [ ] **Step 1: Write the drop**

```sql
-- 20260701130000_drop_legacy_insert_pointer_overload.sql
drop function if exists public.insert_pointer_with_dedup(
  text, pointer_type, text, jsonb, vector, text);
```

- [ ] **Step 2: Verify only the acl overload remains**

```sql
select pg_get_function_identity_arguments(oid)
from pg_proc where proname='insert_pointer_with_dedup';
-- Expected: exactly one row, ending in "p_acl uuid[]"
```

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260701130000_drop_legacy_insert_pointer_overload.sql
git commit -m "chore(db): drop dead pre-acl insert_pointer_with_dedup overload"
```

---

### Task 6: Update the calendar handover doc + note follow-ups

**Files:**
- Modify: `docs/handovers/ingestion/calendar.md`

- [ ] **Step 1: Document the firm-neutral keying** — record that calendar meetings/series are keyed `communication:gcal:{iCalUID}` / `communication:gcal-series:{recurringEventId}` with no tenant segment, and that multi-firm visibility rides on the unioned `acl` (both tenant UUIDs on one node), mirroring the person model.

- [ ] **Step 2: Note the deferred follow-up** — companies are still tenant-scoped (`company::{tenant}::{domain}`) and will duplicate across firms the same way; if that becomes a problem, apply the identical firm-neutral-key + acl-union treatment. Not done here.

- [ ] **Step 3: Commit**

```bash
git add docs/handovers/ingestion/calendar.md
git commit -m "docs(calendar): firm-neutral keying + acl-carried multi-tenancy"
```

---

## Self-Review Notes

- **Spec coverage:** cross-tenant meeting merge (Tasks 1,3), garbage `_R` series fix (Task 1 normalization + Task 3 collapse), idempotent re-ingest (Tasks 1,4), event_sync compatibility (Task 2), FK-complete re-pointing (Task 3 uses the full FK list from Global Constraints), housekeeping overload (Task 5). Person same-name flagging was completed separately (26 `pending` flags backfilled) and is intentionally not in this plan.
- **Destructive-op safety:** Task 3 is branch-first, verified, then merged; all losers re-pointed before delete.
- **Out of scope (stated):** company cross-tenant dedup; email keying (no live cross-tenant collision).
