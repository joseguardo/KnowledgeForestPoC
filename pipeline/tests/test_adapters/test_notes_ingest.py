"""Endpoint orchestration for /api/v1/ingest/notes (the reworked notes path).

Mirrors the Gmail per-message endpoint: the real `notes_entities.extract_graph`
runs; only I/O (source fetch, CRM domain load, access provisioning, the edge
client) is mocked. One meeting → an `event`, `attended`/`affiliated_with`/`about`
edges via insert_pointer + link_pointers, and a body document.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from pipeline.config import settings


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
                {"canonical_key": "person::T1::id:42", "label": "No Domain"},  # tenant-scoped fallback
                {"canonical_key": "person::z@z.com", "label": "Otra Persona"},  # any firm — global
            ]

    http = AsyncMock()
    http.get = AsyncMock(return_value=_Resp())

    names = await ingest_mod._load_person_names(http, "T1")
    assert names == {"lp@poseidon.vc": "Laura Páez", "z@z.com": "Otra Persona"}


TENANT = "T1"
DSN = "postgresql://u:p@h.pooler.supabase.com:5432/postgres"


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
        body="### Notes\nAll good.",
    )
    base.update(kw)
    return MeetingNote(**base)


def _wire(monkeypatch, *, notes, user_ids, person_names=None, team_names=None):
    """Patch the notes endpoint's I/O seams; return (client, ensure_class,
    ensure_user_grant)."""
    from pipeline.adapters.notes import NotesAdapter, NotesFetch
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "notes_firms", json.dumps([{"tenant_id": TENANT, "source_dsn": DSN}])
    )

    async def fake_fetch(self, firm, since=None, max_results=None):
        return NotesFetch(
            notes=notes, own_domains={"kiboventures.com"}, team_names=team_names or {}
        )

    monkeypatch.setattr(NotesAdapter, "fetch_notes", fake_fetch)
    monkeypatch.setattr(
        ingest_mod, "_load_company_domains", AsyncMock(return_value={"poseidon.vc": "Poseidon"})
    )
    # CRM/graph person directory (email → name); without a name an attendee is dropped.
    monkeypatch.setattr(
        ingest_mod, "_load_person_names", AsyncMock(return_value=person_names or {})
    )
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value=user_ids))
    # Rejection logging is a best-effort PostgREST write; stub it so the endpoint
    # doesn't hit the network, and so tests can assert what got logged.
    monkeypatch.setattr(ingest_mod, "log_rejections", AsyncMock(return_value=0))

    async def fake_insert(**kw):
        return {"status": "created", "pointer_id": kw["canonical_key"]}

    client = AsyncMock()
    client.insert_pointer = AsyncMock(side_effect=fake_insert)
    client.ingest_document = AsyncMock(return_value={"status": "created", "pointer_id": "doc-1"})
    app.state.client = client
    return client, None, None


@pytest.mark.asyncio
async def test_ingest_notes_builds_meeting_graph(async_client, monkeypatch):
    client, _ensure_class, _ = _wire(
        monkeypatch,
        notes=[_note()],
        user_ids={"gp@kiboventures.com": "uid-gp"},
        person_names={"lp@poseidon.vc": "Laura Páez"},
    )

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    inserted = {(c.kwargs["type"], c.kwargs["canonical_key"]) for c in client.insert_pointer.call_args_list}
    assert ("event", event_ck) in inserted
    assert ("person", f"person::gp@kiboventures.com") in inserted
    assert ("person", f"person::lp@poseidon.vc") in inserted
    assert ("company", f"company::{TENANT}::poseidon.vc") in inserted
    # everything firm-wide
    assert all(c.kwargs["access_class"] == f"firm:{TENANT}" for c in client.insert_pointer.call_args_list)

    # persons are labelled with names; email rides along as an attribute, not the label
    persons = {c.kwargs["canonical_key"]: c.kwargs
               for c in client.insert_pointer.call_args_list if c.kwargs["type"] == "person"}
    gp = persons[f"person::gp@kiboventures.com"]
    assert gp["label"] == "Guillermo Puebla"
    assert gp["attributes"] == [
        {"key": "email", "value": "gp@kiboventures.com", "data_type": "string", "source": "notes"}
    ]
    assert persons[f"person::lp@poseidon.vc"]["label"] == "Laura Páez"

    links = {(c.kwargs["source_id"], c.kwargs["relationship_type"], c.kwargs["target_id"])
             for c in client.link_pointers.call_args_list}
    assert (f"person::gp@kiboventures.com", "attended", event_ck) in links
    assert (f"person::lp@poseidon.vc", "attended", event_ck) in links
    assert (f"person::lp@poseidon.vc", "affiliated_with", f"company::{TENANT}::poseidon.vc") in links
    # external_org resolves AND a poseidon.vc member attended → about edge
    assert (event_ck, "about", f"company::{TENANT}::poseidon.vc") in links
    # no owner/hosted relationship — just attended
    assert not any(rel in ("hosted", "owner") for _s, rel, _t in links)

    # shareable body → firm class, linked meeting_notes to the event
    dkw = client.ingest_document.call_args.kwargs
    assert dkw["access_class"] == f"firm:{TENANT}"
    assert dkw["link"]["target_id"] == event_ck
    assert dkw["link"]["relationship_type"] == "meeting_notes"
    assert dkw["canonical_key_namespace"] == TENANT


@pytest.mark.asyncio
async def test_ingest_notes_collapses_two_note_pages_into_one_event(async_client, monkeypatch):
    slot = "2026-06-25T09:30:00+02:00"
    notes = [
        _note(page_id="pgA", title="Weekly", scheduled_at=slot, body="### Notes A"),
        _note(page_id="pgB", title="Weekly", scheduled_at=slot, body="### Notes B"),
    ]
    client, _, _ = _wire(monkeypatch, notes=notes, user_ids={})

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    events = {c.kwargs["canonical_key"] for c in client.insert_pointer.call_args_list
              if c.kwargs["type"] == "event"}
    assert len(events) == 1                                  # two pages → one meeting event
    event_ck = next(iter(events))
    assert ":meeting:" in event_ck                           # keyed by slot, not page_id

    # both note bodies ingested as separate documents, both linked to the one event
    doc_links = [c.kwargs["link"]["target_id"] for c in client.ingest_document.call_args_list]
    assert len(doc_links) == 2
    assert all(t == event_ck for t in doc_links)


@pytest.mark.asyncio
async def test_ingest_notes_confidential_body_acl_is_participant_uids(async_client, monkeypatch):
    client, _, _ = _wire(
        monkeypatch,
        notes=[_note(confidential=True)],
        user_ids={"gp@kiboventures.com": "uid-gp", "lp@poseidon.vc": "uid-lp"},
    )

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    # confidential → body visibility carried by principals (owner + attendee uids),
    # NOT a firm class; no access_class needed.
    dkw = client.ingest_document.call_args.kwargs
    assert set(dkw["principals"]) == {"uid-gp", "uid-lp"}
    assert dkw.get("access_class") is None


@pytest.mark.asyncio
async def test_ingest_notes_drops_unresolved_owner(async_client, monkeypatch):
    client, _, _ = _wire(
        monkeypatch,
        notes=[_note(owner_email=None, owner_name="Mystery Person", attendees=["lp@poseidon.vc"])],
        user_ids={},
        person_names={"lp@poseidon.vc": "Laura Páez"},
    )

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    persons = {ck for t, ck in {(c.kwargs["type"], c.kwargs["canonical_key"])
                                for c in client.insert_pointer.call_args_list} if t == "person"}
    # no name-slug fallback node; only the resolvable attendee is a person
    assert not any("::name:" in ck for ck in persons)
    assert persons == {f"person::lp@poseidon.vc"}


@pytest.mark.asyncio
async def test_ingest_notes_drops_attendee_with_no_resolvable_name(async_client, monkeypatch):
    # An attendee whose email resolves to no name (not in team/CRM directory) is
    # dropped — no person pointer, no email-labelled node.
    client, _, _ = _wire(
        monkeypatch,
        notes=[_note(owner_email=None, attendees=["mystery@unknown.com"])],
        user_ids={},
        person_names={},
    )

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    persons = [c for c in client.insert_pointer.call_args_list if c.kwargs["type"] == "person"]
    assert persons == []


@pytest.mark.asyncio
async def test_ingest_notes_logs_dropped_attendee_as_rejection(async_client, monkeypatch):
    from pipeline.api import ingest as ingest_mod

    _wire(
        monkeypatch,
        notes=[_note(owner_email=None, attendees=["mystery@unknown.com"])],
        user_ids={},
        person_names={},
    )

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    ingest_mod.log_rejections.assert_awaited_once()
    _, kwargs = ingest_mod.log_rejections.call_args
    rejs = kwargs["notes"]
    assert [(r.reason, r.attendee) for r in rejs] == [
        ("unnamed_attendee", "mystery@unknown.com"),
    ]
