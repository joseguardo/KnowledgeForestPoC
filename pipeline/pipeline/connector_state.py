from __future__ import annotations

from typing import Any

import httpx

from pipeline.config import settings
from pipeline.errors import AdapterError

# Small key/value store for per-connector incremental sync cursors. Lives in a
# Supabase table reached via PostgREST with the service-role key (which bypasses
# RLS) — no edge function needed.


def _table_url() -> str:
    return f"{settings.supabase_url}/rest/v1/connector_state"


def _headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def get_cursor(http: httpx.AsyncClient, connector: str) -> str | None:
    """Return the stored cursor (ISO timestamp) for a connector, or None if the
    connector has never synced."""
    try:
        resp = await http.get(
            _table_url(),
            headers=_headers(),
            params={"connector": f"eq.{connector}", "select": "cursor"},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"connector_state read HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"connector_state read failed: {exc}")

    rows: list[dict[str, Any]] = resp.json()
    if not rows:
        return None
    return rows[0].get("cursor")


async def set_cursor(http: httpx.AsyncClient, connector: str, cursor_iso: str) -> None:
    """Upsert the cursor for a connector (keyed by the connector name)."""
    try:
        resp = await http.post(
            _table_url(),
            headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
            json={"connector": connector, "cursor": cursor_iso},
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"connector_state write HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"connector_state write failed: {exc}")
