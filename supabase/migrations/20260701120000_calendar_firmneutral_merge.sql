-- 20260701120000_calendar_firmneutral_merge.sql
-- Collapse per-tenant calendar duplicates into one firm-neutral node whose acl
-- is the union of every firm's copy. Also fixes malformed gcal-series:<id>_R…
-- nodes (a series must never carry a per-occurrence suffix). Idempotent: after
-- it runs, all calendar keys already match `communication:gcal…` and the
-- selection set is empty on a re-run.
--
-- Tenancy in this DB is the tenant UUID present as a principal inside the acl
-- array (there is no tenant_id column); scoping is `acl @> '{tenant}'`. Merging
-- two per-tenant copies therefore unions their acls so the survivor stays
-- visible to every firm that had a copy. Meeting bodies/attachments carry their
-- own per-participant acl rows and are NOT touched here.
--
-- Every FK to pointers(id) is ON DELETE CASCADE, so losers are re-pointed across
-- all FK tables BEFORE deletion. tenant_pointer_assignments is empty (skipped).
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
create index cal_map_loser_idx on cal_map(loser);
create index cal_map_survivor_idx on cal_map(survivor);

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

-- 4a. Pre-dedupe child tables with a UNIQUE(pointer_id, key/sequence): within
-- each merge group (a survivor and all its losers) keep exactly ONE row per key
-- — the survivor's if present, else the lowest-pointer loser's — and drop the
-- rest, so the re-point in 4b cannot raise a unique violation and abort the
-- whole migration. Ranking across the whole group (not just loser-vs-survivor)
-- also covers the loser-vs-loser case. These tables are empty for calendar
-- pointers today, but the notes/CRM convergence design attaches attributes/
-- chunks/history onto calendar meetings — the same meeting across firms, the
-- exact same-key scenario. Join on cal_map.loser (which includes the survivor's
-- own self-row) so the survivor participates in the ranking.
delete from attributes_kv x using (
  select a.ctid,
         row_number() over (partition by m.survivor, a.key
                            order by (a.pointer_id = m.survivor) desc, a.pointer_id) rn
  from attributes_kv a join cal_map m on m.loser = a.pointer_id
) d where x.ctid = d.ctid and d.rn > 1;
delete from document_chunks x using (
  select c.ctid,
         row_number() over (partition by m.survivor, c.sequence
                            order by (c.pointer_id = m.survivor) desc, c.pointer_id) rn
  from document_chunks c join cal_map m on m.loser = c.pointer_id
) d where x.ctid = d.ctid and d.rn > 1;
delete from attribute_history x using (
  select h.ctid,
         row_number() over (partition by m.survivor, h.key
                            order by (h.pointer_id = m.survivor) desc, h.pointer_id) rn
  from attribute_history h join cal_map m on m.loser = h.pointer_id
  where h.valid_to is null
) d where x.ctid = d.ctid and d.rn > 1;

-- 4b. Re-point the simple FK tables (edges handled separately in step 5 because
-- of its UNIQUE(source_id,target_id,relationship_type) index).
update attributes_kv a  set pointer_id=m.survivor from cal_map m where a.pointer_id=m.loser and m.loser<>m.survivor;
update document_chunks d set pointer_id=m.survivor from cal_map m where d.pointer_id=m.loser and m.loser<>m.survivor;
update timeseries_data t set pointer_id=m.survivor from cal_map m where t.pointer_id=m.loser and m.loser<>m.survivor;
update attribute_history h set pointer_id=m.survivor from cal_map m where h.pointer_id=m.loser and m.loser<>m.survivor;

-- 4c. duplicate_flags has CHECK(pointer_id_a < pointer_id_b) + a partial UNIQUE,
-- and tenant_coaccess a UNIQUE(tenant_id, pointer_a, pointer_b); re-pointing a
-- loser into a survivor can violate the ordering or the unique. A flag/coaccess
-- row *about a calendar meeting we are actively de-duplicating* carries no value
-- once merged, so drop any row referencing a loser rather than re-point it.
-- (Both tables hold zero calendar rows today.)
delete from duplicate_flags f using cal_map m
 where m.loser<>m.survivor and (f.pointer_id_a=m.loser or f.pointer_id_b=m.loser);
delete from tenant_coaccess t using cal_map m
 where m.loser<>m.survivor and (t.pointer_a=m.loser or t.pointer_b=m.loser);

-- 5. Edges: remap loser endpoints to survivors AND dedupe the resulting
--    (source_id,target_id,relationship_type) collisions IN ONE PASS, to respect
--    the UNIQUE index idx_edges_unique_pair. A plain re-point would violate that
--    index the instant e.g. a person's "attended" edge to both firms' copies of
--    a meeting both resolve to the survivor. Effective endpoints never contain a
--    loser id (always coalesced to the survivor), so the final remap of keepers
--    cannot collide.
-- effective endpoints per edge (only edges touching a loser get remapped)
create temp table edge_eff on commit drop as
select e.id, e.acl, e.created_at, e.relationship_type,
       coalesce(ms.survivor, e.source_id) as eff_source,
       coalesce(mt.survivor, e.target_id) as eff_target,
       (ms.survivor is not null or mt.survivor is not null) as remapped
from edges e
left join cal_map ms on ms.loser=e.source_id and ms.loser<>ms.survivor
left join cal_map mt on mt.loser=e.target_id and mt.loser<>mt.survivor;
create index edge_eff_grp_idx on edge_eff(eff_source, eff_target, relationship_type);

-- one keeper per effective (source,target,rel) group (earliest; stable on id)
create temp table edge_keep on commit drop as
select distinct on (eff_source, eff_target, relationship_type)
       id as keep_id, eff_source, eff_target, relationship_type
from edge_eff
order by eff_source, eff_target, relationship_type, created_at, id;
create index edge_keep_id_idx on edge_keep(keep_id);
create index edge_keep_grp_idx on edge_keep(eff_source, eff_target, relationship_type);

-- effective groups that actually contain >1 edge (i.e. a merge happened) — the
-- only ones whose keeper needs an acl re-union or has non-keepers to delete.
create temp table edge_dupgrp on commit drop as
select eff_source, eff_target, relationship_type
from edge_eff group by 1,2,3 having count(*)>1;
create index edge_dupgrp_idx on edge_dupgrp(eff_source, eff_target, relationship_type);

-- union every group member's acl into its keeper (dup groups only)
update edges e set acl = coalesce((
  select array_agg(distinct u)
  from edge_eff ee, lateral unnest(coalesce(ee.acl,'{}'::uuid[])) u
  where ee.eff_source=k.eff_source and ee.eff_target=k.eff_target
    and ee.relationship_type=k.relationship_type), '{}'::uuid[])
from edge_keep k
join edge_dupgrp g on g.eff_source=k.eff_source and g.eff_target=k.eff_target
                  and g.relationship_type=k.relationship_type
where e.id=k.keep_id;

-- delete every non-keeper (the duplicates the remap would otherwise create).
-- Must NOT restrict to remapped edges: if a remapped edge is its group's keeper
-- (earlier created_at), a non-remapped member becomes the non-keeper and must be
-- removed too, else the keeper's remap collides with it. Indexed not-exists keeps
-- this cheap despite scanning all edges.
delete from edges e
 where not exists (select 1 from edge_keep k where k.keep_id=e.id);

-- remap the surviving keepers to their effective endpoints (now collision-free)
update edges e set source_id=k.eff_source, target_id=k.eff_target
from edge_keep k
where e.id=k.keep_id
  and (e.source_id<>k.eff_source or e.target_id<>k.eff_target);

-- (duplicate_flags / tenant_coaccess loser rows were dropped in step 4c.)

-- 6. Rewrite survivor keys to the firm-neutral form, then delete losers.
update pointers s set canonical_key=m.newkey, updated_at=now()
from (select distinct survivor, newkey from cal_map) m
where s.id=m.survivor and s.canonical_key<>m.newkey;

delete from pointers p using cal_map m where p.id=m.loser and m.loser<>m.survivor;

commit;
