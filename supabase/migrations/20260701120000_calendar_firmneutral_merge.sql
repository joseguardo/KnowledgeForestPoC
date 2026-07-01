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
