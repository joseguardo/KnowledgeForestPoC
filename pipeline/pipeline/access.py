from __future__ import annotations

from typing import Any

import httpx

from pipeline.config import settings
from pipeline.errors import AdapterError

# Service-role helpers reached via PostgREST / GoTrue with the service-role key
# (bypasses RLS). Visibility itself is the per-row `acl uuid[]` (see
# docs/handovers/access-model.md); these helpers only manage tenant membership
# (which feeds my_principals()) and resolve user ids / pointer ids.

PUBLIC_CLASS_ID = "00000000-0000-0000-0000-000000000001"


def _rest_url(table: str) -> str:
    return f"{settings.supabase_url}/rest/v1/{table}"


def _headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def ensure_tenant_member(
    http: httpx.AsyncClient, user_id: str, tenant_id: str, role: str = "viewer"
) -> None:
    """Idempotently add a user to a tenant. tenant_members has PK
    (user_id, tenant_id) — ignore duplicates. Grants the user visibility of that
    tenant's class-gated data via the can_read_class RLS path."""
    try:
        resp = await http.post(
            _rest_url("tenant_members") + "?on_conflict=user_id,tenant_id",
            headers={**_headers(), "Prefer": "resolution=ignore-duplicates"},
            json={"user_id": user_id, "tenant_id": tenant_id, "role": role},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"tenant_members upsert HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"tenant_members upsert failed: {exc}")


async def resolve_pointer_id(http: httpx.AsyncClient, canonical_key: str) -> str | None:
    """Look up an existing pointer's id by canonical_key (service role, bypasses
    RLS). Lets a connector link to an entity ingested in an earlier batch/run."""
    try:
        resp = await http.get(
            _rest_url("pointers"),
            headers=_headers(),
            params={"canonical_key": f"eq.{canonical_key}", "select": "id", "limit": 1},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"pointers lookup HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"pointers lookup failed: {exc}")
    rows: list[dict[str, Any]] = resp.json()
    return rows[0]["id"] if rows and rows[0].get("id") else None


async def resolve_user_ids(http: httpx.AsyncClient) -> dict[str, str]:
    """Map lowercased email -> auth.users id via the GoTrue Admin API. Used to
    grant the per-thread private class to participants who have Supabase accounts.
    Returns a single-page snapshot (sufficient for the org sizes in scope)."""
    try:
        resp = await http.get(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers=_headers(),
            params={"per_page": 1000},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"GoTrue admin users HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"GoTrue admin users request failed: {exc}")

    data = resp.json()
    users = data.get("users", data) if isinstance(data, dict) else data
    mapping: dict[str, str] = {}
    for u in users or []:
        email = (u.get("email") or "").strip().lower()
        if email and u.get("id"):
            mapping[email] = u["id"]
    return mapping
