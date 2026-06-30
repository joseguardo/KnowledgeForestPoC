# Handover — verify & merge duplicate skeleton pointers

For a clean-context agent **with working SQL access** (Supabase MCP `execute_sql` on
project `sjiepibqadbdowcizccw`, or psql). Goal: prove the SharePoint skeleton has no
duplicate pointers/edges, and merge any that exist — correctly.

## Why this matters
There is **NO unique constraint on `pointers.canonical_key`** (dedup is RPC-logic
only). The skeleton was loaded across multiple runs (a crashed dedup run + a bulk
insert + Carto re-runs), so duplicate rows for the same `canonical_key` are *possible*
in principle. Identity for a skeleton item is the exact key
`msgraph:{entraTenant=6e409d59-0cb2-468a-8cbc-a1b48ab0f949}:drive/{driveId}/item/{itemId}`.

**CRITICAL measurement gotcha:** do NOT verify counts with PostgREST `offset`
pagination without `ORDER BY` — it returns overlapping/skipped rows and will report
phantom duplicates. Use SQL `GROUP BY`, or keyset pagination ordered by `id`. A REST
offset probe already produced a *false* "8,288 duplicate keys" result this way; SQL/
keyset showed 0.

## Current state (verified 2026-06-29 via stable keyset pagination)
30,340 distinct rows = 30,340 distinct canonical_keys → **0 duplicate pointers**;
7,994 folder + 22,346 document (matches source). Re-confirm with the queries below.

## Step 1 — verify (authoritative SQL)
```sql
-- a) duplicate POINTERS by canonical_key (expect 0 rows)
select canonical_key, count(*) n
from pointers
where metadata->>'source'='sharepoint_skeleton'
group by canonical_key having count(*) > 1
order by n desc limit 50;

-- b) totals (expect 30340 / 30340 / 7994 / 22346)
select count(*) total, count(distinct canonical_key) distinct_keys,
       count(*) filter (where type='folder') folders,
       count(*) filter (where type='document') docs
from pointers where metadata->>'source'='sharepoint_skeleton';

-- c) duplicate EDGES (expect 0 rows; link-pointers 409 should prevent these)
select e.source_id, e.target_id, e.relationship_type, count(*) n
from edges e
join pointers p on p.id=e.source_id and p.metadata->>'source'='sharepoint_skeleton'
group by 1,2,3 having count(*)>1 order by n desc limit 50;
```
If (a) and (c) return 0 rows → **no duplicates; stop here, report PASS.**

## Step 2 — merge (ONLY if Step 1 finds duplicates)
For each duplicated `canonical_key`, keep ONE survivor and fold the rest in:
1. **Pick survivor** per key: prefer the row WITH a non-null `embedding`; tie-break on
   earliest `created_at`. (Skeleton metadata is identical across copies, so no field
   merge is needed beyond keeping the embedding.)
2. **Re-point edges** from loser ids to the survivor id, avoiding duplicate edges:
```sql
-- map: losers -> survivor
with ranked as (
  select id, canonical_key,
         row_number() over (partition by canonical_key
            order by (embedding is not null) desc, created_at asc) rn
  from pointers where metadata->>'source'='sharepoint_skeleton'
), survivor as (select canonical_key, id from ranked where rn=1),
   loser as (select r.id loser_id, s.id keep_id
             from ranked r join survivor s using (canonical_key) where r.rn>1)
-- repoint source side (skip if it would collide with an existing edge)
update edges e set source_id = l.keep_id
from loser l where e.source_id=l.loser_id
  and not exists (select 1 from edges x
                  where x.source_id=l.keep_id and x.target_id=e.target_id
                    and x.relationship_type=e.relationship_type);
-- repoint target side similarly
update edges e set target_id = l.keep_id
from loser l where e.target_id=l.loser_id
  and not exists (select 1 from edges x
                  where x.target_id=l.keep_id and x.source_id=e.source_id
                    and x.relationship_type=e.relationship_type);
-- delete now-redundant edges still pointing at losers
delete from edges e using loser l
 where e.source_id=l.loser_id or e.target_id=l.loser_id;
-- delete loser pointers
delete from pointers p using loser l where p.id=l.loser_id;
```
3. **Re-verify** with Step 1 (expect 0) and confirm totals are 30,340 / 30,340.

## Step 3 — also check for MISSING items (completeness, not just dups)
Duplicates and gaps are different failures. Confirm every source item is present:
- distinct_keys (Step 1b) must equal the source item count (30,340 for full
  `02_Portfolio`). If distinct_keys < 30,340, items are missing → re-run the bulk
  loader (`scripts/kf_ingest_sharepoint.py --cache /tmp/kibo_drive.json`); it is
  idempotent (inserts only missing, edges 409-skip).

## Step 4 — prevent recurrence (recommended)
Add a DB guard so duplicate keys become impossible:
```sql
-- verify zero dups across the WHOLE table first, then:
create unique index concurrently if not exists pointers_canonical_key_uniq
  on public.pointers (canonical_key) where canonical_key is not null;
```
Check first that no existing non-skeleton pointers share a canonical_key, or the index
build fails. This makes the bulk insert safe to switch to a true upsert later.
