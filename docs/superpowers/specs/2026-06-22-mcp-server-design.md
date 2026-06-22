# MCP Server (demo) — Design

**Date:** 2026-06-22
**Status:** Approved (design); pending implementation plan
**Scope:** A minimal, localhost-only Model Context Protocol server that lets a Claude user query the knowledge graph and ingest ad-hoc content **as themselves**, with the existing per-user access-control (RLS) gate enforced end-to-end.

## Context

The Knowledge Forest backend already implements per-user/per-tenant visibility: every content row carries an `access_class_id`, and the `can_read_class()` RLS gate (migration `20260613100000_access_classes_grants_rls.sql`) lets a row through only if it is `public`, the caller has a direct user grant, or the caller belongs to a tenant with a grant. The gate keys on `auth.uid()` — i.e. it only works when a query runs under a **Supabase-signed user JWT**.

Today that path is exercised only by the web app (`useKnowledgeSearch.js` forwards the signed-in user's `session.access_token` to the `query-knowledge` edge function). There is **no MCP server**. We want one for a demo so a Claude user can log in and see exactly their own data — proving the visibility model — and ingest content that lands in their private slice.

This is a **demo**: localhost-only, smallest reasonable surface. Production hosting, TLS, scaling, and admin tooling are explicitly out of scope.

## Goals

- A Claude user adds a **localhost MCP connector**, logs in via OAuth, and gets two tools: `query_knowledge` and `ingest_document`.
- Every tool call runs under that user's **Supabase JWT**, so the existing RLS gate enforces per-user visibility with no backend changes.
- Ingested content is **private to the ingesting user** and immediately queryable by them (and invisible to others) — the save→query loop demonstrates isolation in one shot.

## Non-goals (YAGNI for the demo)

- Connector-trigger tools (Gmail/Notes batch pulls) — those are tenant/admin, service-role operations that don't ride a per-user JWT.
- Tenant/firm-class ingestion, role-based write checks, multi-page user pagination, admin tools.
- Public hosting, TLS termination, multi-instance/session-store concerns.

## Architecture

A remote **HTTP** MCP server built on **FastMCP**, living in the pipeline repo at `pipeline/pipeline/mcp_server.py` and run locally (`python -m pipeline.mcp_server` → `http://localhost:<port>/mcp`). It reuses existing pipeline code rather than reimplementing it:

- `pipeline.config.settings` — Supabase URL, anon key, service-role key, JWT secret.
- `pipeline.access` — `ensure_class`, `ensure_user_grant` (idempotent, service-role; used by the ingest tool).
- `httpx` — to call the existing edge functions.

**No edge-function or schema changes are required.**

```
Claude ──OAuth (loopback redirect)──▶ MCP server (FastMCP, HTTP, localhost)
   │                                     │  validates Supabase JWT per call → uid
   ├─ query_knowledge ──▶ POST /functions/v1/query-knowledge  (Bearer = user JWT) ─▶ RLS gates results
   └─ ingest_document ──▶ ensure class "user:{uid}" + user grant   (service role, idempotent)
                           └─▶ POST /functions/v1/ingest-document (access_class="user:{uid}", Bearer service role)
```

## Components

### Unit: OAuth / identity (the one nuanced part)

The MCP server is the **OAuth 2.1 authorization server** Claude talks to. It hosts the endpoints MCP clients require — `.well-known` metadata, dynamic client registration (DCR), `/authorize`, `/token` — because Supabase GoTrue does not offer DCR and cannot be pointed at directly.

The login step authenticates the user against **Supabase Auth (GoTrue)**, and **the access token the server issues to Claude *is* the Supabase `access_token`**. Consequences:

- RLS accepts the token directly; `auth.uid()` resolves to the real user. No identity mapping table, no "trust a second issuer" config.
- Token validation per call = verify the Supabase JWT (signature against the project JWT secret / JWKS, plus expiry). FastMCP exposes the validated token and `sub` to each tool.
- Refresh uses the Supabase refresh token.
- Redirect URI is a **loopback** (`http://127.0.0.1:<port>/...`), the default-allowed pattern for local OAuth — nothing to register publicly.

**Primary approach:** use FastMCP's auth support (`OAuthProxy`/remote-auth + a JWT verifier) with GoTrue as the backing login.

**Risk + fallback:** wiring FastMCP's auth to use GoTrue as the backing login is the only non-trivial integration and the most likely thing to need iteration. If it fights us, fall back to a **minimal hand-rolled authorization-code flow** in the same server: it performs a GoTrue password/OTP sign-in and returns the Supabase token as the bearer. Same end result (RLS gets a real Supabase JWT), less framework magic. The fallback is acceptable for a demo and does not change the tools or data flow.

### Unit: `query_knowledge(query: str, mode: str | None = None)`

Forwards the request to the `query-knowledge` edge function with `Authorization: Bearer <caller's Supabase JWT>`. The edge function already creates its Supabase client with the caller's header (`query-knowledge/index.ts:261-263`), so RLS filters restricted rows in-query — they never reach the model or the answer. Returns the composed answer plus sources. Thin pass-through (~10 lines of logic).

- **Depends on:** the validated caller JWT; `query-knowledge` edge function.
- **Visible behavior:** caller sees only what their grants allow; no token → anon → `public` only.

### Unit: `ingest_document(title: str, content: str)`

1. Derive `uid` from the validated JWT (`sub`).
2. `ensure_class(f"user:{uid}", ...)` then `ensure_user_grant(class_id, uid)` — idempotent, service-role (these are admin/provisioning ops; the grant is always to the *authenticated* caller, never an arbitrary id).
3. POST to `ingest-document` with `access_class="user:{uid}"` (service-role bearer). The edge function embeds the content and tags every row with that class. It refuses to fall back to `public` if the class is missing (`ingest-document/index.ts:150-156`), which is why step 2 ensures it first.

Result: the document is **private to that user**, embedded, and immediately findable via `query_knowledge`.

- **Depends on:** validated caller JWT; `pipeline.access.ensure_class`/`ensure_user_grant`; `ingest-document` edge function; service-role key.
- **Visible behavior:** ingesting user can query the doc back; other users cannot see it.

## Data flow (end to end)

1. User adds `http://localhost:<port>/mcp` as a Claude connector → OAuth loopback flow → GoTrue login → server holds the user's Supabase access/refresh tokens.
2. **Query:** `query_knowledge` → edge function under user JWT → RLS-filtered answer.
3. **Ingest:** `ingest_document` → ensure `user:{uid}` class+grant → `ingest-document` tags rows `user:{uid}` → later `query_knowledge` by the same user returns it; another user's query does not.

## Error handling

- No / invalid token → 401; the tools are unavailable until the user completes login.
- Expired access token → refresh via the stored Supabase refresh token; retry once.
- Edge-function non-2xx → surfaced as a tool error including the status/body snippet, matching the pipeline's existing `AdapterError` style.
- `ingest_document` never silently downgrades to `public`: if `ensure_class`/grant fails, the tool errors out (fail-closed), consistent with the edge function's own refusal.

## Testing

- **Unit (mocked Supabase via httpx `MockTransport`, mirroring the Gmail adapter tests):**
  - `query_knowledge` forwards exactly the caller's bearer token to `query-knowledge`.
  - `ingest_document` ensures `user:{uid}` class + grant *before* calling `ingest-document`, passes `access_class="user:{uid}"`, and never falls back to `public`.
  - Auth: a request without a valid token is rejected; `uid` is taken from the validated JWT, not from tool input.
- **Manual end-to-end (the demo itself):** log in as two demo users; ingest a doc as user A; confirm user A's `query_knowledge` returns it and user B's does not.

## Open implementation detail (to settle during planning)

- Exact FastMCP auth API surface for "issue the upstream (Supabase) token as the MCP token" vs. the hand-rolled fallback — decide by spiking the FastMCP path first, with the fallback ready.
- Port and env var names (`MCP_PORT`, reuse of `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` / JWT secret from `pipeline.config`).
