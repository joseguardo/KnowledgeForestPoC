from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pipeline.adapters.notes import (
    NotesAdapter,
    NotesFetch,
    NotesFirm,
    _clean_title,
    _to_note,
    load_notes_firms,
    slugify,
)
from pipeline.config import settings
from pipeline.errors import ValidationError

TENANT = "baa52eca-4c88-4861-9d45-720e743febb4"
DSN = "postgresql://forest_notes_reader.ref:pw@host.pooler.supabase.com:5432/postgres"


def _firm(**kw) -> NotesFirm:
    return NotesFirm(tenant_id=TENANT, source_dsn=DSN, **kw)


# ── pure helpers ────────────────────────────────────────────────────


def test_clean_title_strips_trailing_iso():
    assert _clean_title("Ext. Call Poseidon 2026-06-19T11:00:00.000+02:00") == "Ext. Call Poseidon"
    assert _clean_title("CDD Entrevista Grupo Viamed") == "CDD Entrevista Grupo Viamed"
    assert _clean_title("") == "Meeting"
    assert _clean_title(None) == "Meeting"


def test_slugify():
    assert slugify("Guillermo Puebla") == "guillermo-puebla"
    assert slugify("  José  Ñ  ") == "jos"
    assert slugify(None) == "unknown"


# ── normalization (owner→email, attendees, confidential, body) ──────


def _row(**kw):
    base = {
        "page_id": "11111111-1111-1111-1111-111111111111",
        "title": "Ext. Call Poseidon 2026-06-19T11:00:00.000+02:00",
        "owner_name": "Guillermo Puebla",
        "attendee_emails": ["GPA@kiboventures.com", "x@y.com", "x@y.com", ""],
        "external_org": "Poseidon",
        "meeting_start": datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc),
        "last_edited_time": datetime(2026, 6, 19, 10, 41, tzinfo=timezone.utc),
        "confidential": "Shareable",
        "notion_summary": "### Action Items\n- [ ] Do the thing",
    }
    base.update(kw)
    return base


def test_to_note_resolves_owner_email_and_dedups_attendees():
    owner_map = {"guillermo puebla": "gpa@kiboventures.com"}
    note = _to_note(_firm(), _row(), owner_map)

    assert note.title == "Ext. Call Poseidon"
    assert note.owner_email == "gpa@kiboventures.com"
    # attendees lowercased, deduped, empties dropped
    assert note.attendees == ["gpa@kiboventures.com", "x@y.com"]
    # owner email is among the attendees → same person, keyed once downstream
    assert note.owner_email in note.attendees
    # external_org kept raw — resolution against the CRM happens downstream
    assert note.external_org == "Poseidon"
    assert note.confidential is False
    assert note.occurred_at == "2026-06-19T09:00:00+00:00"
    assert note.last_edited == "2026-06-19T10:41:00+00:00"
    assert "Action Items" in note.body


def test_to_note_confidential_and_empty_body():
    note = _to_note(_firm(), _row(confidential="Confidential", notion_summary=None), {})
    assert note.confidential is True
    assert note.body == ""
    assert note.owner_email is None  # unresolved → owner dropped downstream


# ── config parsing ──────────────────────────────────────────────────


def test_load_notes_firms_parses_and_filters(monkeypatch):
    cfg = [
        {"tenant_id": "T1", "source_dsn": DSN},
        {"tenant_id": "T2", "source_dsn": DSN, "table": "meeting_transcripts"},
    ]
    monkeypatch.setattr(settings, "notes_firms", json.dumps(cfg))
    firms = load_notes_firms()
    assert {f.tenant_id for f in firms} == {"T1", "T2"}
    only = load_notes_firms("T2")
    assert len(only) == 1 and only[0].tenant_id == "T2"


def test_load_notes_firms_dsn_fallback(monkeypatch):
    monkeypatch.setattr(settings, "notes_firms", None)
    monkeypatch.setattr(settings, "notes_source_dsn", DSN)
    monkeypatch.setattr(settings, "notes_default_tenant_id", TENANT)
    firms = load_notes_firms()
    assert len(firms) == 1 and firms[0].tenant_id == TENANT


def test_load_notes_firms_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "notes_firms", None)
    monkeypatch.setattr(settings, "notes_source_dsn", None)
    with pytest.raises(ValidationError):
        load_notes_firms()


def test_load_notes_firms_rejects_unsafe_identifier(monkeypatch):
    cfg = [{"tenant_id": "T1", "source_dsn": DSN, "table": "x; drop table y"}]
    monkeypatch.setattr(settings, "notes_firms", json.dumps(cfg))
    with pytest.raises(ValidationError):
        load_notes_firms()


# ── adapter fetch with a stubbed connection ─────────────────────────


class _FakeConn:
    """Stands in for an asyncpg connection: returns canned rows per query."""

    def __init__(self, meetings, team_rows):
        self._meetings = meetings
        self._team = team_rows
        self.closed = False

    async def fetch(self, sql, *args):
        if 'FROM "meeting_transcripts"' in sql:
            return self._meetings
        return self._team  # owner-map lookups

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_fetch_notes_maps_rows_resolves_owner_and_exposes_own_domains():
    conn = _FakeConn(
        meetings=[_row()],
        team_rows=[
            {"nm": "Guillermo Puebla", "em": "gpa@kiboventures.com"},
            {"nm": "Nadia Z", "em": "nadia@nzalpha.com"},
        ],
    )

    async def fake_connect(dsn):
        assert dsn == DSN
        return conn

    fetched = await NotesAdapter().fetch_notes(_firm(), connect=fake_connect)
    assert conn.closed is True
    assert isinstance(fetched, NotesFetch)
    assert len(fetched.notes) == 1
    assert fetched.notes[0].owner_email == "gpa@kiboventures.com"
    assert fetched.notes[0].title == "Ext. Call Poseidon"
    # own_domains derived from the firm's team-table emails (treats colleagues as
    # person-only downstream, never as companies).
    assert fetched.own_domains == {"kiboventures.com", "nzalpha.com"}
