# Email → tenant auto-assignment (MCP login) — Design

**Date:** 2026-06-22
**Status:** Approved (design); implementing
**Scope:** When a user logs into the MCP server, automatically grant them membership in the right tenant based on their email, so the existing per-tenant RLS visibility "just works" — no manual `tenant_members` inserts.

## Context

The MCP server authenticates users via Supabase (Google). A freshly-created `auth.users` row has **no** `tenant_members` entry, so RLS shows it only `public` data + the user's own `user:{uid}` ingests — never the firm data (Affinidad/Gmail under Kibo, Notes under Nzyme). There is no email→entitlement mapping today; this adds it.

Live tenants (from the `tenants` table):
- **Kibo** `ca61f0e5-563e-5894-954f-38f5a9e0eabc` — Affinidad + Gmail data.
- **Nzyme** `baa52eca-4c88-4861-9d45-720e743febb4` — meeting-notes (Notes) data.

Most Nzyme people currently use `@kiboventures.com` addresses (shared Workspace; migrating to `nzalpha.com`), so a plain domain lookup is wrong for them — they need an explicit override, exactly the carve-out from the Gmail connector design.

## Resolution rule (additive — every matching firm)

Both Kibo and Nzyme are explicit email lists (the `@kiboventures.com` domain is **shared** between the two firms, so domain alone can't decide). Membership is **additive**: a user joins every firm whose email list or domain matches. `nzalpha.com` is the only domain rule (Nzyme).

`resolve_tenants(email) -> list[str]`:
- email ∈ Kibo list → include **Kibo** (`ca61f0e5-…`)
- email ∈ Nzyme list, or domain `nzalpha.com` → include **Nzyme** (`baa52eca-…`)
- no match → no membership (public + own ingests only)

`niklas@`, `jaaz@`, `juan@kiboventures.com` are on **both** lists → members of both tenants. `juan@aallende.com` is on the Kibo list despite a non-Kibo domain (why a list, not domain, is needed).

**Kibo list (16):** nacho@, niklas@, jaaz@, ines@, jose@, juan@, hello@, sara@, juan@aallende.com, sonia@, covadonga@, edvinas@, jma@, jordi@, aquilino@, lucia@.
**Nzyme list (24):** reyes@, santiago@, alf@, vicente@, gpa@, pablo@, juan@, jmg@, jaimegervas@, jaimepedrosa@, pablomayoral@, miguel@, aris@, jacob@, guillermo@, natalia@, mar@, jaaz@, fernando@, gsa@, ignacio@, niklas@ (all `@kiboventures.com`) + sakhee.joisher@nzalpha.com, alvaro.fresnillo@nzalpha.com.

## Components

### `mcp_server/tenant_map.py` (new)
- Holds the mapping: `DOMAIN_TENANTS` (`kiboventures.com`→Kibo, `nzalpha.com`→Nzyme) and `NZYME_EMAILS` (the override set, lowercased).
- `resolve_tenant(email) -> str | None` applies the rule above.
- Defaults baked in so the demo works out of the box; an optional `MCP_TENANT_FIRMS` env JSON (`[{tenant_id, domains[], emails[]}]`) overrides the defaults if set (mirrors the `GMAIL_FIRMS` env posture). Moving the map to a Supabase table is a documented follow-up.

### `access.py` (extend)
- `ensure_tenant_member(http, user_id, tenant_id, role="viewer")` — idempotent upsert into `public.tenant_members` via PostgREST + service role (`on_conflict=user_id,tenant_id`, `Prefer: resolution=ignore-duplicates`), mirroring the existing `_ensure_grant`. Role is `viewer` (RLS read-visibility is role-independent).

### `mcp_server/server.py` (wire in)
- In `_supabase_callback`, after the Supabase code exchange + email-domain check (where `uid`/`email` are known), call `resolve_tenant(email)`; if it returns a tenant, `await ensure_tenant_member(get_http(), uid, tenant)`. Runs once per login, idempotent, best-effort (a failure logs but doesn't block login).

## Data flow

login → Supabase callback → exchange code → `{uid, email}` → `resolve_tenant(email)` → `ensure_tenant_member(uid, tenant)` → subsequent `query_knowledge` runs under the user's JWT and RLS now admits that tenant's `firm:{tenant}` data.

## Demo effect

- `nacho@kiboventures.com` (Kibo only) → sees Affinidad/Gmail, **not** notes.
- `reyes@kiboventures.com` / any `@nzalpha.com` (Nzyme only) → sees meeting-notes, **not** Affinidad → visible tenant isolation.
- `niklas@kiboventures.com` (both lists) → sees both firms' data → cross-tenant user.

## Testing

- `resolve_tenant`: override email → Nzyme; `@nzalpha.com` → Nzyme; other `@kiboventures.com` (e.g. niklas) → Kibo; unknown domain → None.
- `ensure_tenant_member`: posts the right `{user_id, tenant_id, role}` to `tenant_members` with the idempotent header (httpx `MockTransport`).
- callback: given a session + mocked code exchange returning a user, the resolved tenant is passed to `ensure_tenant_member`.

## Out of scope

`confidential`/`restricted` class grants (separate from tenant membership); auto-creating tenants (Kibo + Nzyme already exist); de-provisioning (removing a `tenant_members` row when someone leaves a list).
