from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline import crm_sync


def _http(get_rows=None) -> AsyncMock:
    http = AsyncMock()
    for verb in ("get", "patch", "delete", "post"):
        resp = MagicMock()
        resp.json.return_value = []
        getattr(http, verb).return_value = resp
    if get_rows is not None:
        http.get.return_value.json.return_value = get_rows
    return http


@pytest.mark.asyncio
async def test_reconcile_deletes_membership_key_absent_from_source():
    # pA is still in "Hot" but left "Dealflow"; pA is a resolved source entity.
    http = _http(get_rows=[
        {"pointer_id": "pA", "key": "Dealflow:Stage"},
        {"pointer_id": "pA", "key": "Hot:Stage"},
    ])
    deleted = await crm_sync.reconcile_list_memberships(
        http, tenant_id="T1", managed_keys_by_pointer={"pA": {"Hot:Stage"}},
    )
    assert deleted == [("pA", "Dealflow:Stage")]
    # Queried the firm's :Stage attributes.
    _, gkw = http.get.call_args
    params = list(gkw["params"])
    assert ("key", "like.*:Stage") in params
    assert ("acl", "cs.{T1}") in params
    # Deleted exactly the vanished (pointer, key).
    http.delete.assert_awaited_once()
    _, dkw = http.delete.call_args
    dparams = list(dkw["params"])
    assert ("pointer_id", "eq.pA") in dparams
    assert ("key", "eq.Dealflow:Stage") in dparams


@pytest.mark.asyncio
async def test_reconcile_captures_full_exit_when_listless():
    # pA is a resolved source entity but now has no lists → all its :Stage keys close.
    http = _http(get_rows=[{"pointer_id": "pA", "key": "Dealflow:Stage"}])
    deleted = await crm_sync.reconcile_list_memberships(
        http, tenant_id="T1", managed_keys_by_pointer={"pA": set()},
    )
    assert deleted == [("pA", "Dealflow:Stage")]
    http.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_never_touches_unmanaged_pointer():
    # pB has a graph :Stage key but is NOT in this sync's resolved source set
    # (partial run / resolve failure) → must be left untouched.
    http = _http(get_rows=[{"pointer_id": "pB", "key": "Dealflow:Stage"}])
    deleted = await crm_sync.reconcile_list_memberships(
        http, tenant_id="T1", managed_keys_by_pointer={"pA": {"Dealflow:Stage"}},
    )
    assert deleted == []
    http.delete.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_noop_when_all_present():
    http = _http(get_rows=[
        {"pointer_id": "pA", "key": "Dealflow:Stage"},
        {"pointer_id": "pA", "key": "Hot:Stage"},
    ])
    deleted = await crm_sync.reconcile_list_memberships(
        http, tenant_id="T1",
        managed_keys_by_pointer={"pA": {"Dealflow:Stage", "Hot:Stage"}},
    )
    assert deleted == []
    http.delete.assert_not_called()
