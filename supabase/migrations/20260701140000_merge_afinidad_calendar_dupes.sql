-- 20260701140000_merge_afinidad_calendar_dupes.sql
-- Legacy cleanup: the one-off "Affinidad ingestion v1" import (2026-06-29) created
-- communication meeting nodes (communication::{tenant}::afinidad::{uuid}, origin=gcal)
-- that duplicate real Google-Calendar meetings. The current adapter already excludes
-- meetings (type NOT IN ('meeting','email')), so none recur. Here we merge ONLY the
-- afinidad meeting nodes whose external_id matches a live calendar node
-- (communication:gcal:{iCalUID}) — the confirmed cross-source dupes (~193). The
-- afinidad meetings with NO calendar counterpart are intentionally LEFT ALONE.
--
-- Merge = calendar node (survivor) absorbs the afinidad node (loser): union acl,
-- re-point every FK table (collision-safe, respecting unique indexes), delete loser.
begin;

-- loser (afinidad meeting) -> survivor (matching calendar node by external_id)
create temp table af_map on commit drop as
select p.id as loser, s.id as survivor
from pointers p
join pointers s
  on s.canonical_key = 'communication:gcal:' ||
       regexp_replace(coalesce(p.metadata->>'external_id',''),'@google\.com$','')
where p.type='communication'
  and p.canonical_key like 'communication::%afinidad%'
  and coalesce(p.metadata->>'origin','') = 'gcal'
  and p.metadata->>'external_id' is not null;
create index af_map_loser_idx on af_map(loser);
create index af_map_survivor_idx on af_map(survivor);

-- 1. Union each loser's acl into its survivor.
update pointers s set
  acl = (select array(select distinct e from unnest(s.acl ||
           coalesce((select array_agg(x) from af_map m
                       join pointers l on l.id=m.loser
                       cross join lateral unnest(l.acl) x
                      where m.survivor=s.id), '{}'::uuid[])) e)),
  updated_at = now()
from (select distinct survivor from af_map) d
where s.id = d.survivor;

-- 2a. Pre-dedupe child tables with UNIQUE(pointer_id,key/sequence): keep one row per
-- (survivor,key) across the merge group, drop the rest, so 2b can't unique-violate.
delete from attributes_kv x using (
  select a.ctid, row_number() over (partition by m.survivor, a.key
                     order by (a.pointer_id=m.survivor) desc, a.pointer_id) rn
  from attributes_kv a join af_map m on m.loser=a.pointer_id) d
where x.ctid=d.ctid and d.rn>1;
delete from document_chunks x using (
  select c.ctid, row_number() over (partition by m.survivor, c.sequence
                     order by (c.pointer_id=m.survivor) desc, c.pointer_id) rn
  from document_chunks c join af_map m on m.loser=c.pointer_id) d
where x.ctid=d.ctid and d.rn>1;
delete from attribute_history x using (
  select h.ctid, row_number() over (partition by m.survivor, h.key
                     order by (h.pointer_id=m.survivor) desc, h.pointer_id) rn
  from attribute_history h join af_map m on m.loser=h.pointer_id where h.valid_to is null) d
where x.ctid=d.ctid and d.rn>1;

-- 2b. Re-point the simple FK tables (edges handled in step 3).
update attributes_kv a  set pointer_id=m.survivor from af_map m where a.pointer_id=m.loser;
update document_chunks d set pointer_id=m.survivor from af_map m where d.pointer_id=m.loser;
update timeseries_data t set pointer_id=m.survivor from af_map m where t.pointer_id=m.loser;
update attribute_history h set pointer_id=m.survivor from af_map m where h.pointer_id=m.loser;

-- 2c. duplicate_flags (CHECK a<b + partial unique) / tenant_coaccess (unique) — a
-- flag/coaccess row about a node we are de-duplicating carries no value; drop it.
delete from duplicate_flags f using af_map m where f.pointer_id_a=m.loser or f.pointer_id_b=m.loser;
delete from tenant_coaccess t using af_map m where t.pointer_a=m.loser or t.pointer_b=m.loser;

-- 3. Edges: remap loser endpoints to survivor + dedupe collisions, respecting
-- UNIQUE(source_id,target_id,relationship_type). Scoped to loser edges only.
create temp table edge_fix on commit drop as
select e.id, e.acl, e.created_at, e.relationship_type,
       coalesce(ms.survivor,e.source_id) as eff_source,
       coalesce(mt.survivor,e.target_id) as eff_target
from edges e
left join af_map ms on ms.loser=e.source_id
left join af_map mt on mt.loser=e.target_id
where ms.survivor is not null or mt.survivor is not null;

create temp table edge_occ on commit drop as
select ef.eff_source, ef.eff_target, ef.relationship_type, ef.id, ef.acl, ef.created_at, false as is_existing from edge_fix ef
union all
select k.eff_source, k.eff_target, k.relationship_type, x.id, x.acl, x.created_at, true
from (select distinct eff_source,eff_target,relationship_type from edge_fix) k
join edges x on x.source_id=k.eff_source and x.target_id=k.eff_target and x.relationship_type=k.relationship_type;
create index edge_occ_grp_idx on edge_occ(eff_source,eff_target,relationship_type);

create temp table edge_win on commit drop as
select distinct on (eff_source,eff_target,relationship_type) eff_source,eff_target,relationship_type,id as winner_id,is_existing as winner_existing
from edge_occ order by eff_source,eff_target,relationship_type,is_existing desc,created_at,id;
create index edge_win_id_idx on edge_win(winner_id);

create temp table edge_acl on commit drop as
select eff_source,eff_target,relationship_type, array_agg(distinct u) as macl
from edge_occ o, lateral unnest(coalesce(o.acl,'{}'::uuid[])) u group by eff_source,eff_target,relationship_type;

update edges e set acl=a.macl from edge_win w
join edge_acl a on a.eff_source=w.eff_source and a.eff_target=w.eff_target and a.relationship_type=w.relationship_type
where e.id=w.winner_id;

delete from edges e using edge_occ o where e.id=o.id and not exists (select 1 from edge_win w where w.winner_id=e.id);

update edges e set source_id=w.eff_source, target_id=w.eff_target from edge_win w
where e.id=w.winner_id and not w.winner_existing and (e.source_id<>w.eff_source or e.target_id<>w.eff_target);

-- 4. Delete the merged-away afinidad meeting nodes.
delete from pointers p using af_map m where p.id=m.loser;

commit;
