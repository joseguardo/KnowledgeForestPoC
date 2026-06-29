from __future__ import annotations

from typing import Any

import httpx

from pipeline.config import settings
from pipeline.errors import AdapterError

# Thin, logic-free data-access layer over PostgREST with the service-role key
# (bypasses RLS). Generalises the inline httpx pattern in `connector_state.py` /
# `ingestion_rejections.py`.
#
# Design rule (see the calendar-ingestion rework): edge functions stay *dumb* —
# all matching/dedup/identity/merge *decisions* live in the app (pipeline). This
# module is the passthrough the pipeline uses to read the graph and to apply the
# update/cancel/prune/re-point mutations it has already decided on. It contains no
# business rules: callers pass PostgREST filters and bodies verbatim.
#
# Filters are passed as a list of (key, value) tuples (not a dict) so one column
# can repeat with different operators, e.g. occurred_at gte.. + lte.. for a window.

Filters = list[tuple[str, str]]

_POINTER_COLS = "id,canonical_key,label,type,occurred_at,metadata"
_EDGE_COLS = "id,source_id,target_id,relationship_type,payload"


def _url(table: str) -> str:
    return f"{settings.supabase_url}/rest/v1/{table}"


def _headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _fail(op: str, exc: Exception) -> AdapterError:
    if isinstance(exc, httpx.HTTPStatusError):
        return AdapterError(
            f"PostgREST {op} HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        )
    return AdapterError(f"PostgREST {op} failed: {exc}")


# --- generic verbs -------------------------------------------------------------


async def select_rows(
    http: httpx.AsyncClient, table: str, *, filters: Filters, select: str = "*"
) -> list[dict[str, Any]]:
    """GET rows from `table` matching `filters`, projecting `select`."""
    params: list[tuple[str, str]] = [*filters, ("select", select)]
    try:
        resp = await http.get(
            _url(table),
            headers=_headers(),
            params=params,
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise _fail(f"select {table}", exc)
    return resp.json()


async def patch_rows(
    http: httpx.AsyncClient, table: str, *, filters: Filters, body: dict[str, Any]
) -> list[dict[str, Any]]:
    """PATCH rows in `table` matching `filters` with `body`; returns updated rows."""
    try:
        resp = await http.patch(
            _url(table),
            headers={**_headers(), "Prefer": "return=representation"},
            params=list(filters),
            json=body,
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise _fail(f"patch {table}", exc)
    return resp.json()


async def delete_rows(
    http: httpx.AsyncClient, table: str, *, filters: Filters
) -> list[dict[str, Any]]:
    """DELETE rows from `table` matching `filters`; returns the deleted rows."""
    try:
        resp = await http.delete(
            _url(table),
            headers={**_headers(), "Prefer": "return=representation"},
            params=list(filters),
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise _fail(f"delete {table}", exc)
    return resp.json()


# --- pointer convenience -------------------------------------------------------


async def select_pointers(
    http: httpx.AsyncClient,
    *,
    ptype: str | None = None,
    tenant_id: str | None = None,
    canonical_key: str | None = None,
    occurred_from: str | None = None,
    occurred_to: str | None = None,
    select: str = _POINTER_COLS,
) -> list[dict[str, Any]]:
    """Read pointers, optionally scoped by type, tenant (acl contains tenant_id),
    canonical_key, and an `occurred_at` window. Backs notes→calendar matching and
    the move/cancel existence checks."""
    filters: Filters = []
    if ptype is not None:
        filters.append(("type", f"eq.{ptype}"))
    if canonical_key is not None:
        filters.append(("canonical_key", f"eq.{canonical_key}"))
    if tenant_id is not None:
        filters.append(("acl", "cs.{" + tenant_id + "}"))
    if occurred_from is not None:
        filters.append(("occurred_at", f"gte.{occurred_from}"))
    if occurred_to is not None:
        filters.append(("occurred_at", f"lte.{occurred_to}"))
    return await select_rows(http, "pointers", filters=filters, select=select)


async def patch_pointer(
    http: httpx.AsyncClient, pointer_id: str, fields: dict[str, Any]
) -> list[dict[str, Any]]:
    """Update a single pointer by id (move/retitle, soft-cancel)."""
    return await patch_rows(
        http, "pointers", filters=[("id", f"eq.{pointer_id}")], body=fields
    )


# --- edge convenience ----------------------------------------------------------


async def select_edges(
    http: httpx.AsyncClient, *, filters: Filters, select: str = _EDGE_COLS
) -> list[dict[str, Any]]:
    return await select_rows(http, "edges", filters=filters, select=select)


async def patch_edges(
    http: httpx.AsyncClient, *, filters: Filters, body: dict[str, Any]
) -> list[dict[str, Any]]:
    return await patch_rows(http, "edges", filters=filters, body=body)


async def delete_edges(
    http: httpx.AsyncClient, *, filters: Filters
) -> list[dict[str, Any]]:
    return await delete_rows(http, "edges", filters=filters)
