-- ============================================================================
-- Access classes + grants + tenant membership + class-gated RLS
-- ----------------------------------------------------------------------------
-- Implements per-pointer / per-attribute access control (the feature the user
-- described as an "encryption gate"). With a trusted backend the goal is
-- confidentiality *between* users/tenants, which is access control, not
-- cryptography. So:
--   "encryption type"          -> access_class (a classification label on a row)
--   "datalake gate"            -> RLS predicate (can_read_class) run IN-query
--   "what the user can decrypt"-> grants linking users (direct or via tenant)
--                                 to classes
--
-- Why this is non-breaking to apply: every content row defaults to the 'public'
-- class, and the gate lets 'public' through to everyone (incl. the anon role).
-- The currently-deployed anonymous app keeps working unchanged. Restriction
-- only takes effect once a row is tagged with a non-public class AND grants are
-- issued. RLS is already enabled on these tables; the existing read policies
-- are `USING (true)` and are replaced here with the class gate.
--
-- Why no search RPC needs rewriting: search_pointers / search_hierarchy_aware /
-- search_knowledge / search_by_coaccess / traverse_graph / get_tenant_forest
-- are all SECURITY INVOKER, so the tightened SELECT policies apply automatically
-- inside them -- including the `total` count -- making restricted rows
-- "completely invisible" (filtered in-query, never retrieved-then-stripped).
-- ============================================================================

-- Fixed id for the open/default class so it can be a column default literal.
-- '00000000-0000-0000-0000-000000000001' == public.

-- ----------------------------------------------------------------------------
-- 1. Access class registry
-- ----------------------------------------------------------------------------
create table if not exists public.access_classes (
  id          uuid primary key default gen_random_uuid(),
  key         text not null unique check (length(trim(key)) > 0),
  description text,
  created_at  timestamptz not null default now()
);

insert into public.access_classes (id, key, description)
values ('00000000-0000-0000-0000-000000000001', 'public',
        'Readable by everyone; default class for untagged rows')
on conflict (key) do nothing;

alter table public.access_classes enable row level security;
drop policy if exists access_classes_read on public.access_classes;
create policy access_classes_read on public.access_classes
  for select to anon, authenticated using (true);

-- ----------------------------------------------------------------------------
-- 2. Tenant membership (maps authenticated users -> tenants + write role)
-- ----------------------------------------------------------------------------
create table if not exists public.tenant_members (
  user_id    uuid not null references auth.users(id) on delete cascade,
  tenant_id  uuid not null references public.tenants(id) on delete cascade,
  role       text not null default 'viewer' check (role in ('viewer','editor','admin')),
  created_at timestamptz not null default now(),
  primary key (user_id, tenant_id)
);

alter table public.tenant_members enable row level security;
drop policy if exists tenant_members_self_read on public.tenant_members;
create policy tenant_members_self_read on public.tenant_members
  for select to authenticated using (user_id = auth.uid());

-- ----------------------------------------------------------------------------
-- 3. Grants: connect an access class to a whole tenant OR an individual user.
--    This is how one class serves "one user or many" -- the class is the unit,
--    grants fan it out to grantees.
-- ----------------------------------------------------------------------------
create table if not exists public.access_grants (
  id              uuid primary key default gen_random_uuid(),
  access_class_id uuid not null references public.access_classes(id) on delete cascade,
  grantee_type    text not null check (grantee_type in ('tenant','user')),
  grantee_id      uuid not null,   -- tenants.id when 'tenant', auth.users.id when 'user'
  created_at      timestamptz not null default now(),
  unique (access_class_id, grantee_type, grantee_id)
);
create index if not exists idx_access_grants_lookup
  on public.access_grants (grantee_type, grantee_id);

alter table public.access_grants enable row level security;
-- Grant rows are managed by the backend (service role) only; no anon/auth policy
-- -> default-deny for normal roles. can_read_class() reads them via SECURITY DEFINER.

-- ----------------------------------------------------------------------------
-- 4. Tag columns on the content tables (default -> public, backfills existing rows)
-- ----------------------------------------------------------------------------
alter table public.pointers
  add column if not exists access_class_id uuid not null
  default '00000000-0000-0000-0000-000000000001'
  references public.access_classes(id);

alter table public.attributes_kv
  add column if not exists access_class_id uuid not null
  default '00000000-0000-0000-0000-000000000001'
  references public.access_classes(id);

alter table public.document_chunks
  add column if not exists access_class_id uuid not null
  default '00000000-0000-0000-0000-000000000001'
  references public.access_classes(id);

alter table public.edges
  add column if not exists access_class_id uuid not null
  default '00000000-0000-0000-0000-000000000001'
  references public.access_classes(id);

create index if not exists idx_pointers_access_class on public.pointers (access_class_id);
create index if not exists idx_attrs_access_class    on public.attributes_kv (access_class_id);
create index if not exists idx_chunks_access_class   on public.document_chunks (access_class_id);
create index if not exists idx_edges_access_class     on public.edges (access_class_id);

-- ----------------------------------------------------------------------------
-- 5. The gate: can_read_class(class) -> boolean
--    SECURITY DEFINER so it can read access_grants / tenant_members (which are
--    default-deny under RLS) without recursion. STABLE so the planner can cache
--    it per row-batch. auth.uid() is NULL for the anon role -> only 'public'
--    passes, which is the desired default-deny for restricted classes.
-- ----------------------------------------------------------------------------
create or replace function public.can_read_class(p_class uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select
    p_class = '00000000-0000-0000-0000-000000000001'                 -- public: always
    or exists (                                                       -- direct user grant
      select 1 from public.access_grants g
      where g.access_class_id = p_class
        and g.grantee_type = 'user'
        and g.grantee_id = auth.uid()
    )
    or exists (                                                       -- grant via a tenant the user belongs to
      select 1
      from public.access_grants g
      join public.tenant_members m on m.tenant_id = g.grantee_id
      where g.access_class_id = p_class
        and g.grantee_type = 'tenant'
        and m.user_id = auth.uid()
    );
$$;

grant execute on function public.can_read_class(uuid) to anon, authenticated;

-- ----------------------------------------------------------------------------
-- 6. Replace allow-all SELECT policies with the class gate.
--    One policy per table covering both anon and authenticated; the helper
--    handles the anon case (auth.uid() IS NULL -> public only).
--    Edges additionally require both endpoints to be visible, so an edge can
--    never leak the existence of a hidden pointer. (The pointers subqueries are
--    themselves RLS-filtered, so an unreadable endpoint hides the edge.)
-- ----------------------------------------------------------------------------
drop policy if exists pointers_anon_read on public.pointers;
drop policy if exists pointers_auth_read on public.pointers;
create policy pointers_read on public.pointers
  for select to anon, authenticated
  using (public.can_read_class(access_class_id));

drop policy if exists attrs_anon_read on public.attributes_kv;
drop policy if exists attrs_auth_read on public.attributes_kv;
create policy attrs_read on public.attributes_kv
  for select to anon, authenticated
  using (public.can_read_class(access_class_id));

drop policy if exists chunks_anon_read on public.document_chunks;
drop policy if exists chunks_auth_read on public.document_chunks;
create policy chunks_read on public.document_chunks
  for select to anon, authenticated
  using (public.can_read_class(access_class_id));

drop policy if exists edges_anon_read on public.edges;
drop policy if exists edges_auth_read on public.edges;
create policy edges_read on public.edges
  for select to anon, authenticated
  using (
    public.can_read_class(access_class_id)
    and exists (select 1 from public.pointers s where s.id = source_id)
    and exists (select 1 from public.pointers t where t.id = target_id)
  );

-- NOTE: write policies (INSERT/UPDATE/DELETE for `authenticated`) are intentionally
-- left as-is. Ingestion runs through edge functions on the service role (which
-- bypasses RLS); write-time class assignment + permission checks are handled
-- there in a follow-up phase, not by these policies.

comment on table public.access_classes is
  'Classification labels ("access classes"). Rows in content tables carry an access_class_id; can_read_class() gates visibility. The fixed-id public class is readable by everyone.';
comment on function public.can_read_class(uuid) is
  'RLS gate: true if the class is public, or auth.uid() has a direct user grant, or a grant via a tenant the user belongs to. SECURITY DEFINER to read grant tables without RLS recursion.';
