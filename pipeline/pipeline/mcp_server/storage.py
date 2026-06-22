from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from pipeline.config import settings
from pipeline.errors import AdapterError

from ._runtime import get_http

# CRUD for the mcp_oauth_state table (kinds: client / session / auth_code).
# Reached via PostgREST with the service-role key (bypasses RLS), mirroring
# connector_state.py. Expiry is enforced on read (and rows are best-effort
# pruned), so a short-lived demo never needs a sweeper job.


def _table_url() -> str:
    return f"{settings.supabase_url}/rest/v1/mcp_oauth_state"


def _headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def put(kind: str, id: str, data: dict[str, Any], ttl_seconds: int | None = None) -> None:
    """Upsert a state row (keyed by id)."""
    expires_at = (
        (_now() + timedelta(seconds=ttl_seconds)).isoformat() if ttl_seconds else None
    )
    try:
        resp = await get_http().post(
            _table_url() + "?on_conflict=id",
            headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
            json={"id": id, "kind": kind, "data": data, "expires_at": expires_at},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"mcp_oauth_state write HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"mcp_oauth_state write failed: {exc}")


async def get(id: str) -> dict[str, Any] | None:
    """Return the row's `data` if present and not expired, else None."""
    try:
        resp = await get_http().get(
            _table_url(),
            headers=_headers(),
            params={"id": f"eq.{id}", "select": "data,expires_at"},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"mcp_oauth_state read HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"mcp_oauth_state read failed: {exc}")

    rows: list[dict[str, Any]] = resp.json()
    if not rows:
        return None
    row = rows[0]
    exp = row.get("expires_at")
    if exp and datetime.fromisoformat(exp) < _now():
        await delete(id)  # best-effort prune
        return None
    return row.get("data")


async def delete(id: str) -> None:
    try:
        resp = await get_http().delete(
            _table_url(),
            headers=_headers(),
            params={"id": f"eq.{id}"},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"mcp_oauth_state delete HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"mcp_oauth_state delete failed: {exc}")
