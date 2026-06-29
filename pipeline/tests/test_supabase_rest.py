from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pipeline import supabase_rest as sr
from pipeline.config import settings
from pipeline.errors import AdapterError


def _http(rows: list | None = None) -> AsyncMock:
    """Async http client whose verb methods return a response with a *sync*
    raise_for_status / json (matching httpx)."""
    http = AsyncMock()
    resp = MagicMock()
    resp.json.return_value = rows if rows is not None else []
    for verb in ("get", "patch", "delete", "post"):
        getattr(http, verb).return_value = resp
    return http


def _params_list(call_kwargs) -> list[tuple[str, str]]:
    """PostgREST filters are passed as a list of (key, value) tuples so a column
    (e.g. occurred_at) can repeat with different operators."""
    return list(call_kwargs["params"])


@pytest.mark.asyncio
async def test_select_pointers_builds_window_and_tenant_filters():
    http = _http([{"id": "p1"}])
    rows = await sr.select_pointers(
        http,
        ptype="event",
        tenant_id="ca61f0e5-0000-0000-0000-000000000000",
        occurred_from="2026-06-19T11:00:00+00:00",
        occurred_to="2026-06-19T12:00:00+00:00",
    )
    assert rows == [{"id": "p1"}]
    http.get.assert_awaited_once()
    _, kwargs = http.get.call_args
    params = _params_list(kwargs)
    assert ("type", "eq.event") in params
    assert ("acl", "cs.{ca61f0e5-0000-0000-0000-000000000000}") in params
    assert ("occurred_at", "gte.2026-06-19T11:00:00+00:00") in params
    assert ("occurred_at", "lte.2026-06-19T12:00:00+00:00") in params
    assert kwargs["headers"]["apikey"] == settings.supabase_service_role_key


@pytest.mark.asyncio
async def test_select_pointers_by_canonical_key():
    http = _http([])
    await sr.select_pointers(http, canonical_key="event:T1:gcal:abc")
    _, kwargs = http.get.call_args
    assert ("canonical_key", "eq.event:T1:gcal:abc") in _params_list(kwargs)


@pytest.mark.asyncio
async def test_patch_pointer_targets_id_and_returns_rows():
    http = _http([{"id": "p1", "occurred_at": "2026-06-19T13:00:00+00:00"}])
    out = await sr.patch_pointer(
        http, "p1", {"occurred_at": "2026-06-19T13:00:00+00:00", "label": "Renamed"}
    )
    assert out[0]["occurred_at"] == "2026-06-19T13:00:00+00:00"
    http.patch.assert_awaited_once()
    _, kwargs = http.patch.call_args
    assert ("id", "eq.p1") in _params_list(kwargs)
    assert kwargs["json"]["label"] == "Renamed"
    assert kwargs["headers"]["Prefer"] == "return=representation"


@pytest.mark.asyncio
async def test_delete_edges_filters_by_source_provenance():
    http = _http([{"id": "e1"}])
    await sr.delete_edges(
        http,
        filters=[
            ("target_id", "eq.p1"),
            ("relationship_type", "eq.attended"),
            ("payload->>source", "eq.calendar"),
        ],
    )
    http.delete.assert_awaited_once()
    _, kwargs = http.delete.call_args
    params = _params_list(kwargs)
    assert ("payload->>source", "eq.calendar") in params
    assert ("relationship_type", "eq.attended") in params


@pytest.mark.asyncio
async def test_patch_edges_repoints_source():
    http = _http([{"id": "e1", "source_id": "into"}])
    await sr.patch_edges(
        http, filters=[("source_id", "eq.from")], body={"source_id": "into"}
    )
    _, kwargs = http.patch.call_args
    assert ("source_id", "eq.from") in _params_list(kwargs)
    assert kwargs["json"] == {"source_id": "into"}


@pytest.mark.asyncio
async def test_http_error_raises_adapter_error():
    http = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock(status_code=400, text="bad")
    )
    http.get.return_value = resp
    with pytest.raises(AdapterError):
        await sr.select_pointers(http, ptype="event")
