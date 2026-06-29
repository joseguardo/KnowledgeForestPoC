"""Endpoint orchestration for /api/v1/ingest/notes.

Calendar is the source of truth: a note is only ingested if it matches an
already-ingested calendar meeting — it attaches its attendees and its content
documents to that calendar event and never creates a meeting of its own. A note
with no calendar match is dropped. The real `notes_entities.extract_graph` runs;
only I/O (source fetch, CRM load, the edge client, calendar lookup) is mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline.config import settings

TENANT = "T1"
DSN = "postgresql://u:p@h.pooler.supabase.com:5432/postgres"
CAL = "cal-ev-1"  # the matched calendar event's pointer id
GCAL_CK = f"event:{TENANT}:gcal:uid-1@google.com"


@pytest.mark.asyncio
async def test_load_person_names_keeps_real_names_drops_email_labels():
    """The cross-tenant person directory: global person::{email} → name. Bare-email
    labels and tenant-scoped id-fallbacks (person::{tenant}::id:…) are excluded."""
    from pipeline.api import ingest as ingest_mod

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"canonical_key": "person::lp@poseidon.vc", "label": "Laura Páez"},
                {"canonical_key": "person::bare@x.com", "label": "bare@x.com"},
                {"canonical_key": "person::T1::id:42", "label": "No Domain"},
                {"canonical_key": "person::z@z.com", "label": "Otra Persona"},
            ]

    http = AsyncMock()
    http.get = AsyncMock(return_value=_Resp())
    names = await ingest_mod._load_person_names(http, "T1")
    assert names == {"lp@poseidon.vc": "Laura Páez", "z@z.com": "Otra Persona"}


def _note(**kw):
    from pipeline.adapters.notes import MeetingNote

    base = dict(
        tenant_id=TENANT,
        page_id="pg-1",
        title="Ext. Call Poseidon",
        occurred_at="2026-06-19T09:00:00+00:00",
        last_edited="2026-06-19T10:41:00+00:00",
        owner_name="Guillermo Puebla",
        owner_email="gp@kiboventures.com",
        attendees=["gp@kiboventures.com", "lp@poseidon.vc"],
        external_org="poseidon-vc",
        confidential=False,
        documents=[("notion_summary", "### Notes\nAll good.")],
    )
    base.update(kw)
    return MeetingNote(**base)


def _mock_http(get_rows=None):
    """http for the calendar-lookup data layer. Returns the given calendar rows for
    every select (find_calendar_event matches by title); [] = no calendar event."""
    http = AsyncMock()
    for verb in ("get", "patch", "delete", "post"):
        resp = MagicMock()
        resp.json.return_value = []
        getattr(http, verb).return_value = resp
    if get_rows is not None:
        http.get.return_value.json.return_value = get_rows
    return http


def _cal_rows(label="Ext. Call Poseidon"):
    return [{"id": CAL, "canonical_key": GCAL_CK, "label": label}]


def _wire(monkeypatch, *, notes, user_ids, person_names=None, team_names=None,
          calendar_rows=None):
    from pipeline.adapters.notes import NotesAdapter, NotesFetch
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    app.state.http = _mock_http(get_rows=calendar_rows)
    monkeypatch.setattr(
        settings, "notes_firms", json.dumps([{"tenant_id": TENANT, "source_dsn": DSN}])
    )

    async def fake_fetch(self, firm, since=None, max_results=None):
        return NotesFetch(notes=notes, own_domains={"kiboventures.com"},
                          team_names=team_names or {})

    monkeypatch.setattr(NotesAdapter, "fetch_notes", fake_fetch)
    monkeypatch.setattr(ingest_mod, "_load_company_domains",
                        AsyncMock(return_value={"poseidon.vc": "Poseidon"}))
    monkeypatch.setattr(ingest_mod, "_load_person_names",
                        AsyncMock(return_value=person_names or {}))
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value=user_ids))
    monkeypatch.setattr(ingest_mod, "log_rejections", AsyncMock(return_value=0))

    async def fake_insert(**kw):
        return {"status": "created", "pointer_id": kw["canonical_key"]}

    client = AsyncMock()
    client.insert_pointer = AsyncMock(side_effect=fake_insert)
    client.ingest_document = AsyncMock(return_value={"status": "created", "pointer_id": "doc-1"})
    app.state.client = client
    return client


@pytest.mark.asyncio
async def test_ingest_notes_attaches_to_calendar_event(async_client, monkeypatch):
    """A matched note: no event node created, attendees/about/affiliation + the body
    document all target the calendar event, edges provenance-tagged 'notes'."""
    client = _wire(
        monkeypatch, notes=[_note()],
        user_ids={"gp@kiboventures.com": "uid-gp"},
        person_names={"lp@poseidon.vc": "Laura Páez"},
        calendar_rows=_cal_rows(),
    )
    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    # Notes never create an event node.
    assert "event" not in {c.kwargs["type"] for c in client.insert_pointer.call_args_list}
    # Persons are created (named; email as attribute, not the label).
    persons = {c.kwargs["canonical_key"]: c.kwargs
               for c in client.insert_pointer.call_args_list if c.kwargs["type"] == "person"}
    assert persons["person::gp@kiboventures.com"]["label"] == "Guillermo Puebla"
    assert persons["person::gp@kiboventures.com"]["attributes"] == [
        {"key": "email", "value": "gp@kiboventures.com", "data_type": "string", "source": "notes"}
    ]
    assert persons["person::lp@poseidon.vc"]["label"] == "Laura Páez"

    links = {(c.kwargs["source_id"], c.kwargs["relationship_type"], c.kwargs["target_id"])
             for c in client.link_pointers.call_args_list}
    assert ("person::gp@kiboventures.com", "attended", CAL) in links
    assert ("person::lp@poseidon.vc", "attended", CAL) in links
    assert ("person::lp@poseidon.vc", "affiliated_with", f"company::{TENANT}::poseidon.vc") in links
    assert (CAL, "about", f"company::{TENANT}::poseidon.vc") in links
    assert all(c.kwargs.get("payload") == {"source": "notes"}
               for c in client.link_pointers.call_args_list)

    # Body document → content_of the calendar event, firm-wide.
    dkw = client.ingest_document.call_args.kwargs
    assert dkw["link"] == {"target_id": CAL, "relationship_type": "content_of",
                           "why": "Meeting notion_summary"}
    assert dkw["access_class"] == f"firm:{TENANT}"


@pytest.mark.asyncio
async def test_ingest_notes_dropped_when_no_calendar_match(async_client, monkeypatch):
    """No calendar event for the note → the note is dropped entirely (calendar is
    the source of truth): no pointers, no documents."""
    client = _wire(monkeypatch, notes=[_note()], user_ids={},
                   person_names={"lp@poseidon.vc": "Laura Páez"}, calendar_rows=[])
    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text
    client.insert_pointer.assert_not_called()
    client.ingest_document.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_notes_two_content_fields_two_documents(async_client, monkeypatch):
    """`notes` and `notion_summary` become two separate content_of documents."""
    client = _wire(
        monkeypatch,
        notes=[_note(documents=[("notes", "raw transcript"), ("notion_summary", "summary")])],
        user_ids={}, person_names={"lp@poseidon.vc": "Laura Páez"},
        calendar_rows=_cal_rows(),
    )
    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    docs = client.ingest_document.call_args_list
    assert len(docs) == 2
    assert all(c.kwargs["link"]["target_id"] == CAL for c in docs)
    assert {c.kwargs["metadata"]["field"] for c in docs} == {"notes", "notion_summary"}
    assert {c.kwargs["content"] for c in docs} == {"raw transcript", "summary"}


@pytest.mark.asyncio
async def test_ingest_notes_day_window_match_for_date_only(async_client, monkeypatch):
    """A date-only note (midnight, no scheduled time) still matches a calendar event
    on the same day by title (the hour wouldn't match)."""
    note = _note(occurred_at="2026-06-19T00:00:00+00:00", is_datetime=False, scheduled_at=None)
    client = _wire(monkeypatch, notes=[note], user_ids={},
                   person_names={"lp@poseidon.vc": "Laura Páez"}, calendar_rows=_cal_rows())
    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text
    # attached (body document targets the calendar event), not dropped
    assert client.ingest_document.call_args.kwargs["link"]["target_id"] == CAL


@pytest.mark.asyncio
async def test_ingest_notes_confidential_docs_acl_is_participant_uids(async_client, monkeypatch):
    client = _wire(
        monkeypatch, notes=[_note(confidential=True)],
        user_ids={"gp@kiboventures.com": "uid-gp", "lp@poseidon.vc": "uid-lp"},
        calendar_rows=_cal_rows(),
    )
    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text
    dkw = client.ingest_document.call_args.kwargs
    assert set(dkw["principals"]) == {"uid-gp", "uid-lp"}
    assert dkw.get("access_class") is None


@pytest.mark.asyncio
async def test_ingest_notes_logs_dropped_attendee_as_rejection(async_client, monkeypatch):
    """Extraction still records unnamed attendees as rejections — for a matched note."""
    from pipeline.api import ingest as ingest_mod

    _wire(monkeypatch,
          notes=[_note(owner_email=None, attendees=["mystery@unknown.com"])],
          user_ids={}, person_names={}, calendar_rows=_cal_rows())
    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    ingest_mod.log_rejections.assert_awaited_once()
    rejs = ingest_mod.log_rejections.call_args.kwargs["notes"]
    assert [(r.reason, r.attendee) for r in rejs] == [("unnamed_attendee", "mystery@unknown.com")]
