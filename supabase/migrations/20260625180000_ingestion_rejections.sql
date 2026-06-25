-- Ingestion rejection log (debugging / observability).
--
-- The ingestion pipeline deterministically *drops* some inputs before they reach
-- the graph: Gmail noise (newsletters, automated/transactional, role-mailbox or
-- brand senders, calendar invites — `_noise_reason`), and Notes attendees /
-- owners that can't be named (`unnamed_attendee` / `unresolved_owner`). Those
-- drops are silent, so a wrongly-rejected mail is invisible. This table records
-- why each input was dropped, with enough context (subject, sender, mailbox) to
-- diagnose a bad heuristic without re-running.
--
-- Reached via PostgREST with the service-role key (bypasses RLS) — an ops/debug
-- table, not user-facing — so no anon/authenticated policies are defined (RLS on,
-- zero policies = deny all but service-role), same posture as connector_state.
create table if not exists public.ingestion_rejections (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null,
  source      text not null check (source in ('gmail', 'notes')),
  reason      text not null,                  -- reason code (e.g. list_mail, unnamed_attendee)
  subject     text,                           -- email subject / meeting title
  sender      text,                           -- gmail sender addr / notes attendee email
  sender_name text,                           -- gmail display name; null for notes
  mailbox     text,                           -- gmail mailbox; null for notes
  ref_id      text,                           -- gmail message_id / notes page_id
  thread_id   text,                           -- gmail thread; null for notes
  -- Stable per-rejection identity for upsert: gmail = message_id,
  -- notes = '{page_id}:{attendee_email}'. Re-seeing the same drop on a later run
  -- (cursor overlap / re-backfill) updates the row instead of duplicating it.
  dedup_key   text not null,
  occurred_at timestamptz,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (tenant_id, source, dedup_key)
);

create index if not exists idx_ingestion_rejections_tenant_source
  on public.ingestion_rejections (tenant_id, source);
create index if not exists idx_ingestion_rejections_reason
  on public.ingestion_rejections (reason);

-- Keep updated_at fresh on every upsert (merge-duplicates → UPDATE).
create or replace function public.touch_ingestion_rejections_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_ingestion_rejections_updated_at on public.ingestion_rejections;
create trigger trg_ingestion_rejections_updated_at
  before update on public.ingestion_rejections
  for each row execute function public.touch_ingestion_rejections_updated_at();

alter table public.ingestion_rejections enable row level security;
