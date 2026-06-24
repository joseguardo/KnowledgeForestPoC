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


def _wire(monkeypatch, *, notes, user_ids):
    """Patch the notes endpoint's I/O seams; return (client, ensure_class,
    ensure_user_grant)."""
    from pipeline.adapters.notes import NotesAdapter, NotesFetch
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "notes_firms", json.dumps([{"tenant_id": TENANT, "source_dsn": DSN}])
    )

    async def fake_fetch(self, firm, since=None, max_results=None):
        return NotesFetch(notes=notes, own_domains={"kiboventures.com"})

    monkeypatch.setattr(NotesAdapter, "fetch_notes", fake_fetch)
    monkeypatch.setattr(
        ingest_mod, "_load_company_domains", AsyncMock(return_value={"poseidon.vc": "Poseidon"})
    )
    ensure_class = AsyncMock(return_value="class-id")
    ensure_user_grant = AsyncMock()
    monkeypatch.setattr(ingest_mod, "ensure_class", ensure_class)
    monkeypatch.setattr(ingest_mod, "ensure_tenant_grant", AsyncMock())
    monkeypatch.setattr(ingest_mod, "ensure_user_grant", ensure_user_grant)
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value=user_ids))

    async def fake_insert(**kw):
        return {"status": "created", "pointer_id": kw["canonical_key"]}

    client = AsyncMock()
    client.insert_pointer = AsyncMock(side_effect=fake_insert)
    client.ingest_document = AsyncMock(return_value={"status": "created", "pointer_id": "doc-1"})
    app.state.client = client
    return client, ensure_class, ensure_user_grant


@pytest.mark.asyncio
async def test_ingest_notes_builds_meeting_graph(async_client, monkeypatch):
    client, _ensure_class, _ = _wire(
        monkeypatch, notes=[_note()], user_ids={"gp@kiboventures.com": "uid-gp"}
    )

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    inserted = {(c.kwargs["type"], c.kwargs["canonical_key"]) for c in client.insert_pointer.call_args_list}
    assert ("event", event_ck) in inserted
    assert ("person", f"person::{TENANT}::gp@kiboventures.com") in inserted
    assert ("person", f"person::{TENANT}::lp@poseidon.vc") in inserted
    assert ("company", f"company::{TENANT}::poseidon.vc") in inserted
    # everything firm-wide
    assert all(c.kwargs["access_class"] == f"firm:{TENANT}" for c in client.insert_pointer.call_args_list)

    links = {(c.kwargs["source_id"], c.kwargs["relationship_type"], c.kwargs["target_id"])
             for c in client.link_pointers.call_args_list}
    assert (f"person::{TENANT}::gp@kiboventures.com", "attended", event_ck) in links
    assert (f"person::{TENANT}::lp@poseidon.vc", "attended", event_ck) in links
    assert (f"person::{TENANT}::lp@poseidon.vc", "affiliated_with", f"company::{TENANT}::poseidon.vc") in links
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
async def test_ingest_notes_confidential_body_private_with_grants(async_client, monkeypatch):
    client, ensure_class, ensure_user_grant = _wire(
        monkeypatch,
        notes=[_note(confidential=True)],
        user_ids={"gp@kiboventures.com": "uid-gp", "lp@poseidon.vc": "uid-lp"},
    )

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    body_class = f"meetingnote:{TENANT}:pg-1"
    # private class ensured for the body (alongside the firm class)
    assert body_class in {c.args[1] for c in ensure_class.call_args_list}
    dkw = client.ingest_document.call_args.kwargs
    assert dkw["access_class"] == body_class
    # owner + the attendee with an account are granted (2)
    assert ensure_user_grant.await_count == 2


@pytest.mark.asyncio
async def test_ingest_notes_drops_unresolved_owner(async_client, monkeypatch):
    client, _, _ = _wire(
        monkeypatch,
        notes=[_note(owner_email=None, owner_name="Mystery Person", attendees=["lp@poseidon.vc"])],
        user_ids={},
    )

    resp = await async_client.post("/api/v1/ingest/notes", json={})
    assert resp.status_code == 200, resp.text

    persons = {ck for t, ck in {(c.kwargs["type"], c.kwargs["canonical_key"])
                                for c in client.insert_pointer.call_args_list} if t == "person"}
    # no name-slug fallback node; only the resolvable attendee is a person
    assert not any("::name:" in ck for ck in persons)
    assert persons == {f"person::{TENANT}::lp@poseidon.vc"}
