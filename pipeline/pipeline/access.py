from __future__ import annotations

from typing import Any

import httpx

from pipeline.config import settings
from pipeline.errors import AdapterError

# Service-role helpers for provisioning access classes + grants and resolving
# Supabase users. Reached via PostgREST / GoTrue with the service-role key
# (bypasses RLS). Mirrors connector_state.py's style.
#
# Used by the Gmail connector to enforce firm isolation + content privacy:
#   - firm-wide tier:  class "firm:<tenant_id>"  granted to the tenant
#   - private tier:    class "gmailthread:<tenant_id>:<hash>"  granted to users
# The global "public" class is never used for email-derived data. Callers must
# ensure a class exists BEFORE ingesting under it (fail closed) — an unknown key
# would otherwise fall back to public downstream.

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


async def ensure_class(http: httpx.AsyncClient, key: str, description: str) -> str:
    """Idempotently create the access class `key` and return its id. access_classes
    has a UNIQUE(key), so this upserts on conflict and reads the id back."""
    try:
        resp = await http.post(
            _rest_url("access_classes") + "?on_conflict=key",
            headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
            json={"key": key, "description": description},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"access_classes upsert HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"access_classes upsert failed: {exc}")

    rows: list[dict[str, Any]] = resp.json()
    if rows and rows[0].get("id"):
        return rows[0]["id"]

    # Some PostgREST configs don't return a representation on a no-op merge; read it.
    try:
        get = await http.get(
            _rest_url("access_classes"),
            headers=_headers(),
            params={"key": f"eq.{key}", "select": "id"},
            timeout=settings.web_scrape_timeout,
        )
        get.raise_for_status()
    except httpx.HTTPError as exc:
        raise AdapterError(f"access_classes read-back failed: {exc}")
    got: list[dict[str, Any]] = get.json()
    if not got or not got[0].get("id"):
        raise AdapterError(f"access_classes: could not resolve id for key {key!r}")
    return got[0]["id"]


async def _ensure_grant(
    http: httpx.AsyncClient, class_id: str, grantee_type: str, grantee_id: str
) -> None:
    """Idempotently grant `class_id` to a tenant or user. access_grants has a
    UNIQUE(access_class_id, grantee_type, grantee_id) — ignore duplicates."""
    try:
        resp = await http.post(
            _rest_url("access_grants")
            + "?on_conflict=access_class_id,grantee_type,grantee_id",
            headers={**_headers(), "Prefer": "resolution=ignore-duplicates"},
            json={
                "access_class_id": class_id,
                "grantee_type": grantee_type,
                "grantee_id": grantee_id,
            },
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"access_grants upsert HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"access_grants upsert failed: {exc}")


async def ensure_tenant_grant(http: httpx.AsyncClient, class_id: str, tenant_id: str) -> None:
    await _ensure_grant(http, class_id, "tenant", tenant_id)


async def ensure_user_grant(http: httpx.AsyncClient, class_id: str, user_id: str) -> None:
    await _ensure_grant(http, class_id, "user", user_id)


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
