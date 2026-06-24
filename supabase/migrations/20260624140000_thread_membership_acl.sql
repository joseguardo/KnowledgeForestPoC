-- Email bodies are private to a thread's participants, without minting an
-- access_class per thread. Bodies carry one shared sentinel class `email_body`
-- (non-public, never granted → invisible via can_read_class); a thread_membership
-- table + a second PERMISSIVE RLS policy authorizes participants. Membership rows
-- are the irreducible (thread × participant) set; no class proliferation.

-- 1. Membership: which platform users may read a thread's bodies.
create table if not exists public.thread_membership (
  tenant_id  uuid not null,
  thread_id  text not null,
  user_id    uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (tenant_id, thread_id, user_id)
);
create index if not exists idx_thread_membership_user
  on public.thread_membership (user_id, thread_id);

alter table public.thread_membership enable row level security;
-- Users see only their own membership; writes are service-role only (bypasses RLS).
drop policy if exists thread_membership_self_read on public.thread_membership;
create policy thread_membership_self_read on public.thread_membership
  for select to authenticated using (user_id = auth.uid());

-- 2. Sentinel class for all email bodies (not public, no grants → can_read_class false).
insert into public.access_classes (key, description)
values ('email_body', 'Email bodies — gated by thread_membership, not grants')
on conflict (key) do nothing;

-- 3. Membership gates (SECURITY DEFINER to read thread_membership / pointers under RLS).
create or replace function public.can_read_thread(p_tenant uuid, p_thread text)
returns boolean language sql stable security definer set search_path = public as $$
  select p_thread is not null and exists (
    select 1 from public.thread_membership tm
    where tm.tenant_id = p_tenant and tm.thread_id = p_thread and tm.user_id = auth.uid()
  );
$$;
grant execute on function public.can_read_thread(uuid, text) to anon, authenticated;

-- Authorize a chunk/edge off its owning document's tenant_id/thread_id metadata,
-- so no extra columns are needed on chunks/edges.
create or replace function public.can_read_thread_doc(p_pointer uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select public.can_read_thread(
    (p.metadata->>'tenant_id')::uuid, p.metadata->>'thread_id'
  ) from public.pointers p where p.id = p_pointer;
$$;
grant execute on function public.can_read_thread_doc(uuid) to anon, authenticated;

-- 4. Additional PERMISSIVE select policies (OR'd with the existing class gate).
--    Non-email rows have a null thread → these contribute nothing.
drop policy if exists pointers_read_thread on public.pointers;
create policy pointers_read_thread on public.pointers
  for select to anon, authenticated
  using (public.can_read_thread((metadata->>'tenant_id')::uuid, metadata->>'thread_id'));

drop policy if exists chunks_read_thread on public.document_chunks;
create policy chunks_read_thread on public.document_chunks
  for select to anon, authenticated
  using (public.can_read_thread_doc(pointer_id));

drop policy if exists edges_read_thread on public.edges;
create policy edges_read_thread on public.edges
  for select to anon, authenticated
  using (
    public.can_read_thread_doc(source_id)
    and exists (select 1 from public.pointers s where s.id = source_id)
    and exists (select 1 from public.pointers t where t.id = target_id)
  );
