-- Per-connector incremental-sync state. Lets source connectors (Notion, and
-- future live connectors) persist a "last synced" cursor between runs so a
-- scheduled pull can fetch only what changed since the previous run.
--
-- The ingestion pipeline reaches this table via PostgREST using the service-role
-- key, which bypasses RLS — so no anon/authenticated policies are defined here.
create table if not exists public.connector_state (
  connector  text primary key,
  cursor     timestamptz,
  updated_at timestamptz not null default now()
);

-- Keep updated_at fresh on every upsert.
create or replace function public.touch_connector_state_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_connector_state_updated_at on public.connector_state;
create trigger trg_connector_state_updated_at
  before update on public.connector_state
  for each row execute function public.touch_connector_state_updated_at();

alter table public.connector_state enable row level security;
