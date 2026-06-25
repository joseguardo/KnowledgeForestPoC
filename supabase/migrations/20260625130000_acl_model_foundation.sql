-- ============================================================================
-- Per-row acl[] access model — Stage 1 (foundation).
-- ----------------------------------------------------------------------------
-- Replaces the access_class_id + can_read_class (per-row correlated EXISTS into
-- access_grants) model — and the thread_membership email-body gate — with a
-- single mechanism: every gated row carries `acl uuid[]`, the set of *principals*
-- (tenant ids, user ids, and the public sentinel) that may read it. RLS becomes
--   USING ( acl && (select my_principals()) )
-- evaluated once per query (the scalar-subquery wrapper forces an InitPlan), with
-- a GIN index on acl. Fail-closed: a row with acl '{}' is visible to no one.
--
-- This migration is additive + transactional: it adds + backfills acl and swaps
-- the SELECT policies, but leaves access_class_id / access_classes / access_grants
-- / thread_membership in place (now unused by RLS) for Stage 4 cleanup. Deploy the
-- Stage-2 writers (which set acl) together with this so no new row is created
-- acl-empty.
-- ============================================================================

-- The caller's principals: public sentinel + their uid (if authed) + their
-- tenants. SECURITY DEFINER so the tenant_members read doesn't recurse through
-- that table's own RLS. STABLE so the policy's (select …) is an InitPlan.
create or replace function public.my_principals()
returns uuid[]
language sql
stable
security definer
set search_path = public
as $$
  select array['00000000-0000-0000-0000-000000000001'::uuid]
       || case when auth.uid() is null then '{}'::uuid[] else array[auth.uid()] end
       || coalesce(
            (select array_agg(tenant_id) from tenant_members where user_id = auth.uid()),
            '{}'::uuid[]
          );
$$;
grant execute on function public.my_principals() to anon, authenticated;

-- Translate a named access-class key to its principal set, for the write path.
-- 'public'/null → sentinel; 'firm:{uuid}' → [uuid]; 'user:{uuid}' → [uuid].
-- An unknown named key → '{}' (fail-closed; such writers must pass principals).
create or replace function public.principals_for_class(p_key text)
returns uuid[]
language sql
immutable
as $$
  select case
    when p_key is null or p_key = 'public'
      then array['00000000-0000-0000-0000-000000000001'::uuid]
    when p_key like 'firm:%' then array[substring(p_key from 6)::uuid]
    when p_key like 'user:%' then array[substring(p_key from 6)::uuid]
    else '{}'::uuid[]
  end;
$$;

-- 1. acl columns (fail-closed default) + GIN indexes.
alter table public.pointers        add column if not exists acl uuid[] not null default '{}';
alter table public.attributes_kv   add column if not exists acl uuid[] not null default '{}';
alter table public.document_chunks add column if not exists acl uuid[] not null default '{}';
alter table public.edges           add column if not exists acl uuid[] not null default '{}';

create index if not exists idx_pointers_acl   on public.pointers        using gin (acl);
create index if not exists idx_attrs_acl       on public.attributes_kv   using gin (acl);
create index if not exists idx_chunks_acl      on public.document_chunks using gin (acl);
create index if not exists idx_edges_acl        on public.edges           using gin (acl);

-- 2. Backfill acl from the existing class+grant model.
--    public class → sentinel; otherwise → every grantee_id granted that class
--    (tenant ids and/or user ids — both are principals).
update public.pointers p set acl = case
  when p.access_class_id = '00000000-0000-0000-0000-000000000001'
    then array['00000000-0000-0000-0000-000000000001'::uuid]
  else coalesce(
    (select array_agg(g.grantee_id) from public.access_grants g
      where g.access_class_id = p.access_class_id), '{}'::uuid[])
end;

update public.attributes_kv a set acl = case
  when a.access_class_id = '00000000-0000-0000-0000-000000000001'
    then array['00000000-0000-0000-0000-000000000001'::uuid]
  else coalesce(
    (select array_agg(g.grantee_id) from public.access_grants g
      where g.access_class_id = a.access_class_id), '{}'::uuid[])
end;

update public.edges e set acl = case
  when e.access_class_id = '00000000-0000-0000-0000-000000000001'
    then array['00000000-0000-0000-0000-000000000001'::uuid]
  else coalesce(
    (select array_agg(g.grantee_id) from public.access_grants g
      where g.access_class_id = e.access_class_id), '{}'::uuid[])
end;

-- Email bodies were gated by thread_membership, not grants — their class
-- (email_body) is granted to no one. Set those pointers' acl to the thread's
-- member uids so they stay visible to participants (folds membership into acl).
update public.pointers p set acl = coalesce(
  (select array_agg(tm.user_id) from public.thread_membership tm
    where tm.tenant_id = nullif(p.metadata->>'tenant_id','')::uuid
      and tm.thread_id = p.metadata->>'thread_id'), '{}'::uuid[])
where p.access_class_id = (select id from public.access_classes where key = 'email_body')
  and p.metadata ? 'thread_id';

-- Chunks always share their owning pointer's visibility — inherit acl from it
-- (covers email-body chunks too, after the pointer backfill above).
update public.document_chunks c set acl = p.acl
  from public.pointers p where p.id = c.pointer_id;

-- email_content edges (body --> message) carried the ungranted email_body class;
-- inherit the body pointer's (participant) acl so members keep seeing the link.
update public.edges e set acl = p.acl
  from public.pointers p
 where p.id = e.source_id
   and e.access_class_id = (select id from public.access_classes where key = 'email_body');

-- 3. Swap the SELECT policies to the acl gate. Edges keep the endpoint-visibility
--    EXISTS clauses so an edge can't leak the existence of a hidden pointer.
drop policy if exists pointers_read on public.pointers;
create policy pointers_read on public.pointers
  for select to anon, authenticated
  using (acl && (select public.my_principals()));

drop policy if exists attrs_read on public.attributes_kv;
create policy attrs_read on public.attributes_kv
  for select to anon, authenticated
  using (acl && (select public.my_principals()));

drop policy if exists chunks_read on public.document_chunks;
create policy chunks_read on public.document_chunks
  for select to anon, authenticated
  using (acl && (select public.my_principals()));

drop policy if exists edges_read on public.edges;
create policy edges_read on public.edges
  for select to anon, authenticated
  using (
    acl && (select public.my_principals())
    and exists (select 1 from public.pointers s where s.id = source_id)
    and exists (select 1 from public.pointers t where t.id = target_id)
  );

-- 4. Drop the thread-membership permissive policies — folded into acl above.
drop policy if exists pointers_read_thread on public.pointers;
drop policy if exists chunks_read_thread on public.document_chunks;
drop policy if exists edges_read_thread on public.edges;

-- 5. Drop the now-unused access_class btree indexes (acl GIN replaces them; the
--    access_class_id columns themselves linger until Stage 4).
drop index if exists public.idx_pointers_access_class;
drop index if exists public.idx_attrs_access_class;
drop index if exists public.idx_chunks_access_class;
drop index if exists public.idx_edges_access_class;
