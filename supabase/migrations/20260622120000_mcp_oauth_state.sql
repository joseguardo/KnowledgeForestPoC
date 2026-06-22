-- Transient state for the demo MCP server's OAuth 2.1 Authorization Server.
-- The MCP server (pipeline/pipeline/mcp_server/) is the AS; Supabase (Google)
-- is the IdP, and the tokens handed to clients ARE Supabase JWTs (never stored
-- here). This table holds only the short-lived OAuth machinery:
--   kind='client'     dynamic client registrations (RFC 7591), long-lived
--   kind='session'    pending /authorize, bridges to the Supabase login leg (TTL ~600s)
--   kind='auth_code'  one-time callback->token bridge holding the Supabase tokens (TTL ~60s)
--
-- Reached via PostgREST with the service-role key (bypasses RLS), same posture
-- as connector_state. No anon/authenticated policies -> default-deny.
create table if not exists public.mcp_oauth_state (
  id         text primary key,
  kind       text not null check (kind in ('client','session','auth_code')),
  data       jsonb not null,
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_mcp_oauth_state_kind on public.mcp_oauth_state (kind);
create index if not exists idx_mcp_oauth_state_expires on public.mcp_oauth_state (expires_at);

alter table public.mcp_oauth_state enable row level security;

comment on table public.mcp_oauth_state is
  'Short-lived OAuth machinery for the demo MCP server (client regs, pending authorize sessions, one-time auth codes). Service-role only; Supabase JWTs are passed through, not stored long-term.';
