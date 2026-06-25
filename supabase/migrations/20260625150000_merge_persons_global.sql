-- ============================================================================
-- Stage 3 data migration: re-key existing person nodes to the global identity
-- `person::{email}` and merge cross-tenant duplicates of the same email.
-- ----------------------------------------------------------------------------
-- Pre-acl, people were keyed per-tenant (`person::{tenant}::{email}`), so the
-- same human was a separate node per firm. This collapses each email to ONE
-- node: survivor keeps the email's global key, its acl becomes the UNION of the
-- group's acls (so the node is visible to every related firm), and the group's
-- edges + attributes are repointed onto it (conflicts dropped). Going-forward
-- ingestion already writes `person::{email}`, so this only touches legacy rows;
-- on a fresh DB it's a no-op. The no-email id-fallback keys are left untouched.
-- ============================================================================
do $$
declare
  r record;
  survivor uuid;
  losers uuid[];
  v_acl uuid[];
begin
  for r in
    select split_part(canonical_key, '::', 3) as email,
           array_agg(id order by created_at, id) as ids
    from public.pointers
    where type = 'person'
      and canonical_key like 'person::%'
      and array_length(string_to_array(canonical_key, '::'), 1) = 3
      and split_part(canonical_key, '::', 3) like '%@%'
    group by 1
  loop
    survivor := r.ids[1];
    losers := r.ids[2:cardinality(r.ids)];

    -- survivor: global key + acl = union of the whole group's acls
    select coalesce(array_agg(distinct e), '{}'::uuid[]) into v_acl
      from public.pointers p, unnest(p.acl) e
     where p.id = any(r.ids);
    update public.pointers
       set canonical_key = 'person::' || r.email, acl = v_acl, updated_at = now()
     where id = survivor;

    if cardinality(losers) >= 1 then
      -- repoint edges (drop those that would duplicate a survivor edge)
      update public.edges e set source_id = survivor
       where e.source_id = any(losers)
         and not exists (select 1 from public.edges x
                          where x.source_id = survivor and x.target_id = e.target_id
                            and x.relationship_type = e.relationship_type);
      update public.edges e set target_id = survivor
       where e.target_id = any(losers)
         and not exists (select 1 from public.edges x
                          where x.target_id = survivor and x.source_id = e.source_id
                            and x.relationship_type = e.relationship_type);

      -- repoint attributes (drop those whose key already exists on the survivor)
      update public.attributes_kv a set pointer_id = survivor
       where a.pointer_id = any(losers)
         and not exists (select 1 from public.attributes_kv x
                          where x.pointer_id = survivor and x.key = a.key);

      update public.document_chunks c set pointer_id = survivor where c.pointer_id = any(losers);

      -- drop the losers (cascade removes their leftover conflicting edges/attrs)
      delete from public.pointers where id = any(losers);
    end if;
  end loop;
end $$;