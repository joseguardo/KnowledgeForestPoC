"""Endpoint orchestration for /api/v1/ingest/calendar.

Mirrors the Gmail/Notes endpoints: the real `calendar_entities.extract_graph`
runs; only I/O (the calendar fetch, CRM domain load, access provisioning, cursor
store, the edge client) is mocked. One event → an `event` pointer,
`attended`/`attended_by`/`regarding`/`affiliated_with` edges via insert_pointer +
link_pointers, plus a firm-wide description document.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import pytest

from pipeline.config import settings

TENANT = "T1"
OWNER = "gp@kiboventures.com"


def _event(**kw):
    from pipeline.adapters.calendar import CalendarEvent

    base = dict(
        tenant_id=TENANT,
        calendar_email=OWNER,
        owner_name="Guillermo Puebla",
        ical_uid="uid-1@google.com",
        event_id="evt1",
        title="Sync with Poseidon",
        start="2026-06-25T10:00:00Z",
        end="2026-06-25T11:00:00Z",
        location="Zoom",
        description="Agenda for the call.",
        organizer=(OWNER, "Guillermo Puebla"),
        attendees=[("lp@poseidon.vc", "Laura Páez")],
        recurring_event_id=None,
    )
    base.update(kw)
    return CalendarEvent(**base)


def _wire(monkeypatch, *, events, get_cursor=None, set_cursor=None):
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings,
        "gmail_firms",
        json.dumps([{
            "tenant_id": TENANT,
            "mailboxes": [OWNER],
            "sa_key_b64": base64.b64encode(b'{"client_email": "sa@x.iam"}').decode(),
        }]),
    )

    async def fake_fetch(firm, subject, http, *, updated_min=None, max_results=None, sa_info=None):
        fake_fetch.calls.append({"subject": subject, "updated_min": updated_min, "sa_info": sa_info})
        return events
    fake_fetch.calls = []

    monkeypatch.setattr(ingest_mod, "fetch_calendar_events", fake_fetch)
    monkeypatch.setattr(
        ingest_mod, "_load_company_domains", AsyncMock(return_value={"poseidon.vc": "Poseidon"})
    )
    monkeypatch.setattr(ingest_mod, "_load_person_names", AsyncMock(return_value={}))
    monkeypatch.setattr(ingest_mod, "get_cursor", AsyncMock(return_value=get_cursor))
    set_cursor_mock = set_cursor or AsyncMock()
    monkeypatch.setattr(ingest_mod, "set_cursor", set_cursor_mock)

    async def fake_insert(**kw):
        return {"status": "created", "pointer_id": kw["canonical_key"]}

    client = AsyncMock()
    client.insert_pointer = AsyncMock(side_effect=fake_insert)
    client.ingest_document = AsyncMock(return_value={"status": "created", "pointer_id": "doc-1"})
    app.state.client = client
    return client, fake_fetch, set_cursor_mock


@pytest.mark.asyncio
async def test_ingest_calendar_builds_event_graph(async_client, monkeypatch):
    client, _, _ = _wire(monkeypatch, events=[_event()])

    resp = await async_client.post("/api/v1/ingest/calendar", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["source_type"] == "calendar"

    ev_ck = f"event:{TENANT}:gcal:uid-1@google.com"
    gp = f"person::gp@kiboventures.com"
    lp = f"person::lp@poseidon.vc"
    company = f"company::{TENANT}::poseidon.vc"

    inserted = {(c.kwargs["type"], c.kwargs["canonical_key"]) for c in client.insert_pointer.call_args_list}
    assert ("event", ev_ck) in inserted
    assert ("person", gp) in inserted
    assert ("person", lp) in inserted
    assert ("company", company) in inserted
    # everything firm-wide
    assert all(c.kwargs["access_class"] == f"firm:{TENANT}" for c in client.insert_pointer.call_args_list)

    links = {(c.kwargs["source_id"], c.kwargs["relationship_type"], c.kwargs["target_id"])
             for c in client.link_pointers.call_args_list}
    # owner + attendee both relate via `attended` (same label, same direction)
    assert (gp, "attended", ev_ck) in links
    assert (lp, "attended", ev_ck) in links
    assert not any(rel == "attended_by" for _s, rel, _t in links)
    assert (lp, "affiliated_with", company) in links
    assert (ev_ck, "regarding", company) in links

    # description → firm-wide document linked to the event
    dkw = client.ingest_document.call_args.kwargs
    assert dkw["access_class"] == f"firm:{TENANT}"
    assert dkw["link"]["target_id"] == ev_ck
    assert dkw["link"]["relationship_type"] == "event_details"
    assert dkw["canonical_key_namespace"] == TENANT


@pytest.mark.asyncio
async def test_ingest_calendar_uses_dedicated_calendar_sa(async_client, monkeypatch):
    """When CALENDAR_SA_KEY_* is set, the fetch mints with that SA, not Gmail's."""
    cal_sa_b64 = base64.b64encode(b'{"client_email": "calendar-sa@x.iam"}').decode()
    monkeypatch.setattr(settings, "calendar_sa_key_b64", cal_sa_b64, raising=False)
    monkeypatch.setattr(settings, "calendar_sa_key_json", None, raising=False)
    _client, fake_fetch, _ = _wire(monkeypatch, events=[_event()])

    resp = await async_client.post("/api/v1/ingest/calendar", json={})
    assert resp.status_code == 200, resp.text
    assert fake_fetch.calls[0]["sa_info"] == {"client_email": "calendar-sa@x.iam"}


@pytest.mark.asyncio
async def test_ingest_calendar_falls_back_to_gmail_sa(async_client, monkeypatch):
    monkeypatch.setattr(settings, "calendar_sa_key_b64", None, raising=False)
    monkeypatch.setattr(settings, "calendar_sa_key_json", None, raising=False)
    _client, fake_fetch, _ = _wire(monkeypatch, events=[_event()])

    resp = await async_client.post("/api/v1/ingest/calendar", json={})
    assert resp.status_code == 200, resp.text
    assert fake_fetch.calls[0]["sa_info"] is None  # endpoint passes None → fetch uses firm SA


@pytest.mark.asyncio
async def test_ingest_calendar_no_description_skips_document(async_client, monkeypatch):
    client, _, _ = _wire(monkeypatch, events=[_event(description="")])

    resp = await async_client.post("/api/v1/ingest/calendar", json={})
    assert resp.status_code == 200, resp.text
    client.ingest_document.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_calendar_since_last_uses_and_advances_cursor(async_client, monkeypatch):
    set_cursor = AsyncMock()
    _client, fake_fetch, set_cursor = _wire(
        monkeypatch, events=[_event()],
        get_cursor="2026-06-20T00:00:00+00:00", set_cursor=set_cursor,
    )

    resp = await async_client.post("/api/v1/ingest/calendar", json={"since_last": True})
    assert resp.status_code == 200, resp.text

    # the stored cursor was passed to the fetch as updated_min
    assert fake_fetch.calls[0]["updated_min"] == "2026-06-20T00:00:00+00:00"
    # and the cursor was advanced for this mailbox
    cursor_key = f"google-calendar:{TENANT}:{OWNER}"
    assert set_cursor.await_args.args[1] == cursor_key
