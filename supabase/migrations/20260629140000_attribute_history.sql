-- ============================================================================
-- Opt-in temporal historization for selected attributes_kv keys.
-- ----------------------------------------------------------------------------
-- A change to a *tracked* attribute (listed in historized_keys) is preserved as a
-- closed time interval in a separate `attribute_history` table, instead of being
-- overwritten in place. The live `attributes_kv` row stays the single "current"
-- value — its (pointer_id,key) unique constraint, the edge-function upsert, every
-- search RPC and RLS policy are untouched — so history never competes with current
-- data for relevance. History is reachable only via get_attribute_history().
--
-- Capture is mechanical, in a trigger (like moddatetime): "if the key is tracked and
-- the value changed, snapshot the old state." No business logic in the DB.
-- See docs/handovers/ingestion/attribute-history.md.
-- ============================================================================

-- 1. Config: which keys are historized. Opt-in is data, not a migration.
create table if not exists public.historized_keys (
  pattern      text primary key,                 -- LIKE pattern over attributes_kv.key
  pointer_type pointer_type,                      -- optional scope (null = any type)
  note         text,
  created_at   timestamptz not null default now()
);

-- Seed: CRM list membership + pipeline stage (e.g. 'Dealflow:Stage').
insert into public.historized_keys (pattern, pointer_type, note)
values ('%:Stage', null, 'CRM list membership + pipeline stage (enter/move/exit)')
on conflict (pattern) do nothing;

-- historized_keys is non-sensitive config: readable by all, writable by service role
-- only (no write policy). The trigger reads it as definer regardless.
alter table public.historized_keys enable row level security;
drop policy if exists historized_keys_read on public.historized_keys;
create policy historized_keys_read on public.historized_keys
  for select to anon, authenticated using (true);

-- 2. The history table. The open row (valid_to is null) mirrors the current value;
--    closed rows are the past. `acl` is copied from the attributes_kv row so RLS
--    visibility is identical (a tenant sees only its own history).
create table if not exists public.attribute_history (
  id          uuid primary key default gen_random_uuid(),
  pointer_id  uuid not null references public.pointers(id) on delete cascade,
  key         text not null,
  value       jsonb,                              -- value during this interval
  data_type   attribute_data_type,
  source      text,
  acl         uuid[] not null default '{}',
  valid_from  timestamptz not null default now(), -- observed start
  valid_to    timestamptz,                        -- null = current open interval
  recorded_at timestamptz not null default now()
);

create index if not exists idx_attr_history_pointer_key
  on public.attribute_history (pointer_id, key, valid_from desc);
-- At most one open interval per (pointer_id, key) — mirrors attributes_kv's unique row.
create unique index if not exists uq_attr_history_open
  on public.attribute_history (pointer_id, key) where valid_to is null;
create index if not exists idx_attr_history_acl
  on public.attribute_history using gin (acl);

alter table public.attribute_history enable row level security;
drop policy if exists attribute_history_read on public.attribute_history;
create policy attribute_history_read on public.attribute_history
  for select to anon, authenticated
  using (acl && (select public.my_principals()));

-- 3. The capture trigger. AFTER row trigger on attributes_kv; security definer so the
--    history write + pointer-type lookup succeed regardless of the writer's role.
create or replace function public.track_attribute_history()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_key     text;
  v_pointer uuid;
begin
  if tg_op = 'DELETE' then
    v_key := old.key; v_pointer := old.pointer_id;
  else
    v_key := new.key; v_pointer := new.pointer_id;
  end if;

  -- Tracked? (cheap LIKE against the tiny config table; optional pointer_type scope)
  if not exists (
    select 1 from public.historized_keys h
    where v_key like h.pattern
      and (h.pointer_type is null
           or h.pointer_type = (select p.type from public.pointers p where p.id = v_pointer))
  ) then
    return null;  -- after trigger: return value ignored
  end if;

  if tg_op = 'INSERT' then
    insert into public.attribute_history
      (pointer_id, key, value, data_type, source, acl, valid_from, valid_to)
    values (new.pointer_id, new.key, new.value, new.data_type, new.source, new.acl, now(), null);

  elsif tg_op = 'UPDATE' then
    if new.value is distinct from old.value then
      update public.attribute_history
         set valid_to = now()
       where pointer_id = old.pointer_id and key = old.key and valid_to is null;
      insert into public.attribute_history
        (pointer_id, key, value, data_type, source, acl, valid_from, valid_to)
      values (new.pointer_id, new.key, new.value, new.data_type, new.source, new.acl, now(), null);
    else
      -- Value unchanged (e.g. full re-backfill): keep the open interval's acl current.
      update public.attribute_history
         set acl = new.acl
       where pointer_id = new.pointer_id and key = new.key and valid_to is null
         and acl is distinct from new.acl;
    end if;

  elsif tg_op = 'DELETE' then
    update public.attribute_history
       set valid_to = now()
     where pointer_id = old.pointer_id and key = old.key and valid_to is null;
  end if;

  return null;
end;
$$;

drop trigger if exists attributes_kv_history on public.attributes_kv;
create trigger attributes_kv_history
  after insert or update or delete on public.attributes_kv
  for each row execute function public.track_attribute_history();

-- 4. Read path. SECURITY INVOKER (default) so RLS on attribute_history filters by acl.
create or replace function public.get_attribute_history(
  p_pointer_id uuid, p_key_pattern text default '%'
)
returns jsonb
language sql
stable
as $$
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'key', key,
        'value', value,
        'valid_from', valid_from,
        'valid_to', valid_to
      )
      order by key, valid_from
    ),
    '[]'::jsonb
  )
  from public.attribute_history
  where pointer_id = p_pointer_id
    and key like p_key_pattern;
$$;
grant execute on function public.get_attribute_history(uuid, text) to anon, authenticated;
