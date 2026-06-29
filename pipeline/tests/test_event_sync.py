from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline import event_sync


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
async def test_reconcile_attendees_deletes_only_absent_calendar_edges():
    # Two calendar-sourced attended edges exist; only pA is still invited.
    http = _http(get_rows=[
        {"id": "e1", "source_id": "pA"},
        {"id": "e2", "source_id": "pB"},
    ])
    stale = await event_sync.reconcile_attendees(
        http, event_id="ev1", desired_person_ids={"pA"}
    )
    assert stale == ["e2"]
    # Selected only calendar-sourced attended edges for this event.
    _, gkw = http.get.call_args
    params = list(gkw["params"])
    assert ("target_id", "eq.ev1") in params
    assert ("relationship_type", "eq.attended") in params
    assert ("payload->>source", "eq.calendar") in params
    # Deleted exactly the absent one (e2), by id.
    http.delete.assert_awaited_once()
    _, dkw = http.delete.call_args
    assert ("id", "eq.e2") in list(dkw["params"])


@pytest.mark.asyncio
async def test_reconcile_attendees_noop_when_all_present():
    http = _http(get_rows=[{"id": "e1", "source_id": "pA"}])
    stale = await event_sync.reconcile_attendees(
        http, event_id="ev1", desired_person_ids={"pA", "pB"}
    )
    assert stale == []
    http.delete.assert_not_called()


@pytest.mark.asyncio
async def test_overwrite_event_patches_time_title_metadata():
    http = _http()
    await event_sync.overwrite_event(
        http, pointer_id="ev1", occurred_at="2026-06-19T13:00:00+00:00",
        label="Renamed", metadata={"event_type": "meeting", "end": "x"},
    )
    http.patch.assert_awaited_once()
    _, kw = http.patch.call_args
    assert ("id", "eq.ev1") in list(kw["params"])
    assert kw["json"]["occurred_at"] == "2026-06-19T13:00:00+00:00"
    assert kw["json"]["label"] == "Renamed"
    assert kw["json"]["metadata"]["end"] == "x"


@pytest.mark.asyncio
async def test_soft_cancel_event_marks_and_drops_attendance():
    http = _http(get_rows=[{"id": "ev1", "metadata": {"event_type": "meeting"}}])
    found = await event_sync.soft_cancel_event(
        http, canonical_key="event:T1:gcal:abc"
    )
    assert found is True
    # Patched metadata: preserves existing keys, adds cancelled status + timestamp.
    _, pkw = http.patch.call_args
    meta = pkw["json"]["metadata"]
    assert meta["event_type"] == "meeting"
    assert meta["status"] == "cancelled"
    assert "cancelled_at" in meta
    # Dropped calendar-sourced attendance for this event.
    http.delete.assert_awaited_once()
    _, dkw = http.delete.call_args
    params = list(dkw["params"])
    assert ("target_id", "eq.ev1") in params
    assert ("payload->>source", "eq.calendar") in params


@pytest.mark.asyncio
async def test_soft_cancel_event_noop_when_never_ingested():
    http = _http(get_rows=[])
    found = await event_sync.soft_cancel_event(
        http, canonical_key="event:T1:gcal:missing"
    )
    assert found is False
    http.patch.assert_not_called()
    http.delete.assert_not_called()


def test_meeting_title_key_normalizes_case_space_punct():
    assert event_sync.meeting_title_key("Ext. Call — Poseidon") == \
        event_sync.meeting_title_key("ext call poseidon")


@pytest.mark.asyncio
async def test_find_calendar_event_matches_same_hour_and_title():
    # Two events in the hour; only the gcal one with a matching title is returned.
    http = _http(get_rows=[
        {"id": "series", "canonical_key": "event:T1:gcal-series:s", "label": "Sync"},
        {"id": "cal1", "canonical_key": "event:T1:gcal:uid", "label": "Sync with Poseidon"},
        {"id": "note1", "canonical_key": "event:T1:meetingnote:pg", "label": "Sync with Poseidon"},
    ])
    pid = await event_sync.find_calendar_event(
        http, tenant_id="T1",
        scheduled_at="2026-06-19T11:45:00+02:00", title="sync with poseidon",
    )
    assert pid == "cal1"
    # Queried the clock-hour window in UTC (09:00–10:00 for 11:45+02:00).
    _, gkw = http.get.call_args
    params = list(gkw["params"])
    assert ("type", "eq.event") in params
    assert ("acl", "cs.{T1}") in params
    assert any(k == "occurred_at" and v.startswith("gte.2026-06-19T09:00:00") for k, v in params)
    assert any(k == "occurred_at" and v.startswith("lte.2026-06-19T09:59:59") for k, v in params)


@pytest.mark.asyncio
async def test_find_calendar_event_day_window_for_date_only():
    # A date-only note matches a same-day calendar event even at a different hour.
    http = _http(get_rows=[
        {"id": "cal1", "canonical_key": "event:T1:gcal:uid", "label": "Sync with Poseidon"},
    ])
    pid = await event_sync.find_calendar_event(
        http, tenant_id="T1", scheduled_at="2026-06-19T00:00:00+00:00",
        title="Sync with Poseidon", day=True,
    )
    assert pid == "cal1"
    params = list(http.get.call_args.kwargs["params"])
    assert any(k == "occurred_at" and v.startswith("gte.2026-06-19T00:00:00") for k, v in params)
    assert any(k == "occurred_at" and v.startswith("lte.2026-06-19T23:59:59") for k, v in params)


@pytest.mark.asyncio
async def test_find_calendar_event_none_when_no_title_match():
    http = _http(get_rows=[
        {"id": "cal1", "canonical_key": "event:T1:gcal:uid", "label": "Different meeting"},
    ])
    pid = await event_sync.find_calendar_event(
        http, tenant_id="T1", scheduled_at="2026-06-19T11:00:00Z", title="Sync with Poseidon",
    )
    assert pid is None


@pytest.mark.asyncio
async def test_find_calendar_event_none_without_scheduled_at():
    http = _http(get_rows=[])
    pid = await event_sync.find_calendar_event(
        http, tenant_id="T1", scheduled_at=None, title="Sync",
    )
    assert pid is None
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_absorb_note_events_repoints_orphan_and_deletes_it():
    http = _http(get_rows=[
        {"id": "cal1", "canonical_key": "event:T1:gcal:uid", "label": "Sync"},        # self
        {"id": "series", "canonical_key": "event:T1:gcal-series:s", "label": "Sync"}, # calendar series
        {"id": "note1", "canonical_key": "event:T1:meetingnote:pg", "label": "Sync"}, # orphan → absorb
        {"id": "note2", "canonical_key": "event:T1:meeting:h", "label": "Other"},     # title mismatch
    ])
    absorbed = await event_sync.absorb_note_events(
        http, tenant_id="T1", calendar_event_id="cal1",
        scheduled_at="2026-06-19T11:00:00Z", title="Sync",
    )
    assert absorbed == ["note1"]
    patches = [(list(c.kwargs["params"]), c.kwargs["json"]) for c in http.patch.call_args_list]
    assert ([("source_id", "eq.note1")], {"source_id": "cal1"}) in patches
    assert ([("target_id", "eq.note1")], {"target_id": "cal1"}) in patches
    # The orphan note-event pointer was deleted.
    http.delete.assert_awaited_once()
    _, dkw = http.delete.call_args
    assert ("id", "eq.note1") in list(dkw["params"])
