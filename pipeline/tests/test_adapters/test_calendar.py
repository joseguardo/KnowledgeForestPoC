"""Calendar adapter: parse Google Calendar `events.list` items into CalendarEvent
records and filter the noise (cancelled / all-day / declined / solo events).

`events_from_calendar` is pure (no network) — it mirrors `messages_from_thread`.
`fetch_events` adds the DWD token + paginated API calls (mocked here).
"""

from __future__ import annotations

import base64

from unittest.mock import AsyncMock

import pytest

from pipeline.adapters.calendar import CalendarEvent, events_from_calendar
from pipeline.config import settings

TENANT = "T1"
OWNER = "gp@kiboventures.com"


def _item(**kw) -> dict:
    base = dict(
        id="evt1",
        iCalUID="uid-1@google.com",
        status="confirmed",
        summary="Sync with Poseidon",
        location="Zoom",
        description="Agenda: the deal.",
        start={"dateTime": "2026-06-25T10:00:00Z"},
        end={"dateTime": "2026-06-25T11:00:00Z"},
        organizer={"email": OWNER, "displayName": "Guillermo Puebla"},
        attendees=[
            {"email": OWNER, "displayName": "Guillermo Puebla", "self": True,
             "organizer": True, "responseStatus": "accepted"},
            {"email": "lp@poseidon.vc", "displayName": "Laura Páez",
             "responseStatus": "accepted"},
        ],
    )
    base.update(kw)
    return base


def _events(*items: dict) -> list[CalendarEvent]:
    return events_from_calendar(list(items), tenant_id=TENANT, calendar_email=OWNER)


def test_parses_core_event_fields():
    ev = _events(_item())[0]
    assert ev.tenant_id == TENANT
    assert ev.calendar_email == OWNER
    assert ev.ical_uid == "uid-1@google.com"
    assert ev.event_id == "evt1"
    assert ev.title == "Sync with Poseidon"
    assert ev.start == "2026-06-25T10:00:00Z"
    assert ev.end == "2026-06-25T11:00:00Z"
    assert ev.location == "Zoom"
    assert ev.description == "Agenda: the deal."
    assert ev.organizer == (OWNER, "Guillermo Puebla")
    assert ev.owner_name == "Guillermo Puebla"
    # attendees excludes the owner; emails lowercased, names kept
    assert ev.attendees == [("lp@poseidon.vc", "Laura Páez")]


def test_attendee_emails_lowercased_and_owner_excluded():
    ev = _events(
        _item(attendees=[
            {"email": "GP@Kiboventures.com", "self": True, "responseStatus": "accepted"},
            {"email": "LP@Poseidon.VC", "displayName": "Laura", "responseStatus": "accepted"},
        ])
    )[0]
    assert ev.attendees == [("lp@poseidon.vc", "Laura")]


def test_skips_cancelled_event():
    assert _events(_item(status="cancelled")) == []


def test_skips_all_day_event():
    assert _events(_item(start={"date": "2026-06-25"}, end={"date": "2026-06-26"})) == []


def test_skips_when_owner_declined():
    declined = _item(attendees=[
        {"email": OWNER, "self": True, "responseStatus": "declined"},
        {"email": "lp@poseidon.vc", "displayName": "Laura", "responseStatus": "accepted"},
    ])
    assert _events(declined) == []


def test_skips_solo_event_with_no_other_attendees():
    assert _events(_item(attendees=[
        {"email": OWNER, "self": True, "responseStatus": "accepted"},
    ])) == []
    # also when attendees is absent entirely (personal block)
    assert _events(_item(attendees=None)) == []


def test_excludes_meeting_room_resources_from_attendees():
    ev = _events(_item(attendees=[
        {"email": OWNER, "self": True, "responseStatus": "accepted"},
        {"email": "lp@poseidon.vc", "displayName": "Laura", "responseStatus": "accepted"},
        {"email": "room-7@resource.calendar.google.com", "resource": True,
         "responseStatus": "accepted"},
    ]))[0]
    assert ev.attendees == [("lp@poseidon.vc", "Laura")]


def test_external_organizer_counts_as_a_participant():
    # Owner is the only listed attendee, but an external organizer makes it a real
    # 2-party meeting → kept, organizer included as a participant.
    ev = _events(_item(
        organizer={"email": "ceo@target.com", "displayName": "CEO"},
        attendees=[{"email": OWNER, "self": True, "responseStatus": "accepted"}],
    ))[0]
    assert ("ceo@target.com", "CEO") in ev.attendees


def test_missing_summary_gets_placeholder_title():
    ev = _events(_item(summary=None))[0]
    assert ev.title == "(no title)"


def test_captures_recurring_event_id():
    # one-off: no recurringEventId
    assert _events(_item())[0].recurring_event_id is None
    # recurring instance: recurringEventId carries the series id
    ev = _events(_item(recurringEventId="series-abc"))[0]
    assert ev.recurring_event_id == "series-abc"


@pytest.mark.asyncio
async def test_fetch_events_paginates_and_passes_window(monkeypatch):
    from pipeline.adapters import calendar as cal

    monkeypatch.setattr(cal, "_mint_token", AsyncMock(return_value="tok"))

    pages = [
        {"items": [_item(id="a", iCalUID="ua")], "nextPageToken": "p2"},
        {"items": [_item(id="b", iCalUID="ub")]},
    ]
    calls: list[dict] = []

    async def fake_get(http, url, headers, params):
        calls.append(params)
        return pages[len(calls) - 1]

    monkeypatch.setattr(cal, "_get", fake_get)

    firm = _firm()
    events = await cal.fetch_events(firm, OWNER, http=AsyncMock())

    assert {e.ical_uid for e in events} == {"ua", "ub"}
    # primary calendar, expanded recurrences, ordered, with a timeMin window
    assert calls[0]["singleEvents"] == "true"
    assert calls[0]["orderBy"] == "startTime"
    assert "timeMin" in calls[0]
    assert "updatedMin" not in calls[0]
    # second page carried the token
    assert calls[1]["pageToken"] == "p2"


@pytest.mark.asyncio
async def test_fetch_events_incremental_sends_updated_min(monkeypatch):
    from pipeline.adapters import calendar as cal

    monkeypatch.setattr(cal, "_mint_token", AsyncMock(return_value="tok"))
    seen: list[dict] = []

    async def fake_get(http, url, headers, params):
        seen.append(params)
        return {"items": []}

    monkeypatch.setattr(cal, "_get", fake_get)

    await cal.fetch_events(
        _firm(), OWNER, http=AsyncMock(), updated_min="2026-06-20T00:00:00+00:00"
    )
    assert seen[0]["updatedMin"] == "2026-06-20T00:00:00+00:00"


def _firm():
    from pipeline.adapters.gmail import GmailFirm

    return GmailFirm(
        tenant_id=TENANT,
        sa_info={"client_email": "gmail-sa@x.iam"},
        mailboxes=[OWNER],
        scopes="https://www.googleapis.com/auth/calendar.readonly",
    )


@pytest.mark.asyncio
async def test_fetch_events_mints_with_sa_info_override(monkeypatch):
    """A distinct calendar SA is used for the token when passed; otherwise the
    firm's (Gmail) SA."""
    from pipeline.adapters import calendar as cal

    mint = AsyncMock(return_value="tok")
    monkeypatch.setattr(cal, "_mint_token", mint)

    async def fake_get(http, url, headers, params):
        return {"items": []}
    monkeypatch.setattr(cal, "_get", fake_get)

    firm = _firm()
    cal_sa = {"client_email": "calendar-sa@x.iam"}
    await cal.fetch_events(firm, OWNER, http=AsyncMock(), sa_info=cal_sa)
    assert mint.await_args.args[0] == cal_sa

    mint.reset_mock()
    await cal.fetch_events(firm, OWNER, http=AsyncMock())
    assert mint.await_args.args[0] == firm.sa_info


def test_calendar_sa_info_prefers_b64_then_json_then_none(monkeypatch):
    from pipeline.adapters import calendar as cal

    monkeypatch.setattr(settings, "calendar_sa_key_b64", None, raising=False)
    monkeypatch.setattr(settings, "calendar_sa_key_json", None, raising=False)
    assert cal._calendar_sa_info() is None

    monkeypatch.setattr(
        settings, "calendar_sa_key_b64",
        base64.b64encode(b'{"client_email": "calendar-sa@x.iam"}').decode(),
        raising=False,
    )
    assert cal._calendar_sa_info() == {"client_email": "calendar-sa@x.iam"}
