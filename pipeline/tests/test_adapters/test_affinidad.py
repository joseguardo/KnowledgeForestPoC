from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pipeline.adapters.affinidad import (
    AffinidadAdapter,
    AffinidadFirm,
    CrmDeal,
    CrmEntity,
    CrmEvent,
    CrmNote,
    _flatten_blocks,
    _to_deal,
    _to_edge,
    _to_entity,
    _to_event,
    _to_note,
    company_key,
    emails_by_entity,
    event_key,
    load_affinidad_firms,
    person_key,
)
from pipeline.config import settings
from pipeline.errors import ValidationError

TENANT = "baa52eca-4c88-4861-9d45-720e743febb4"
DSN = "postgresql://forest_crm_reader.ref:pw@host.pooler.supabase.com:5432/postgres"


def _firm(**kw) -> AffinidadFirm:
    return AffinidadFirm(tenant_id=TENANT, source_dsn=DSN, **kw)


# ── canonical keys ──────────────────────────────────────────────────


def test_company_key_prefers_domain_else_id():
    assert company_key(TENANT, "Acme.COM", "uuid-1") == f"company::{TENANT}::acme.com"
    assert company_key(TENANT, None, "uuid-1") == f"company::{TENANT}::id:uuid-1"
    assert company_key(TENANT, "   ", "uuid-1") == f"company::{TENANT}::id:uuid-1"


def test_person_key_prefers_email_else_id():
    assert person_key(TENANT, "A@Kibo.com", "uuid-2") == f"person::{TENANT}::a@kibo.com"
    assert person_key(TENANT, None, "uuid-2") == f"person::{TENANT}::id:uuid-2"


def test_event_key_uses_source_event_id():
    assert event_key(TENANT, "evt-9") == f"event::{TENANT}::affinidad::evt-9"


# ── config parsing ──────────────────────────────────────────────────


def test_load_firms_parses_and_filters(monkeypatch):
    cfg = [
        {"tenant_id": "T1", "source_dsn": DSN},
        {"tenant_id": "T2", "source_dsn": DSN},
    ]
    monkeypatch.setattr(settings, "affinidad_firms", json.dumps(cfg))
    firms = load_affinidad_firms()
    assert {f.tenant_id for f in firms} == {"T1", "T2"}
    only = load_affinidad_firms("T2")
    assert len(only) == 1 and only[0].tenant_id == "T2"


def test_load_firms_dsn_fallback(monkeypatch):
    monkeypatch.setattr(settings, "affinidad_firms", None)
    monkeypatch.setattr(settings, "affinidad_source_dsn", DSN)
    monkeypatch.setattr(settings, "affinidad_default_tenant_id", TENANT)
    firms = load_affinidad_firms()
    assert len(firms) == 1 and firms[0].tenant_id == TENANT and firms[0].source_dsn == DSN


def test_load_firms_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(settings, "affinidad_firms", None)
    monkeypatch.setattr(settings, "affinidad_source_dsn", None)
    with pytest.raises(ValidationError):
        load_affinidad_firms()


# ── normalization ───────────────────────────────────────────────────


def test_emails_by_entity_groups_addresses():
    rows = [
        {"entity_id": "p1", "email": "Primary@Kibo.com", "is_primary": True},
        {"entity_id": "p1", "email": "alias@kibo.com", "is_primary": False},
        {"entity_id": "p2", "email": "other@x.com", "is_primary": True},
    ]
    idx = emails_by_entity(rows)
    assert set(idx["p1"]) == {"primary@kibo.com", "alias@kibo.com"}
    assert idx["p2"] == ["other@x.com"]


def test_to_entity_company_builds_key_and_attributes():
    row = {
        "id": "c1",
        "kind": "company",
        "name": "Acme Inc",
        "domain": "acme.com",
        "sector": "Fintech",
        "status": "Portfolio",
        "location": "Madrid",
        "affinity_id": "aff-1",
    }
    ent = _to_entity(TENANT, row, {})
    assert ent.kind == "company"
    assert ent.label == "Acme Inc"
    assert ent.canonical_key == f"company::{TENANT}::acme.com"
    attrs = {k: v for (k, v, _dt) in ent.attributes}
    assert attrs["Sector"] == "Fintech"
    assert attrs["Status"] == "Portfolio"
    assert attrs["Location"] == "Madrid"
    assert ent.metadata["affinity_id"] == "aff-1"
    assert ent.occurred_at is None


def test_to_entity_person_uses_primary_email_and_email_list():
    row = {"id": "p1", "kind": "person", "full_name": "Ana Ruiz", "email": "ana@kibo.com", "title": "Partner"}
    ent = _to_entity(TENANT, row, {"p1": ["ana@kibo.com", "ana2@kibo.com"]})
    assert ent.canonical_key == f"person::{TENANT}::ana@kibo.com"
    assert ent.label == "Ana Ruiz"
    attrs = {k: v for (k, v, _dt) in ent.attributes}
    assert attrs["Title"] == "Partner"
    assert ent.metadata["emails"] == ["ana@kibo.com", "ana2@kibo.com"]
    assert ent.email == "ana@kibo.com"  # primary email, for granting private bodies


def test_to_edge_handles_jsonb_string_metadata():
    # asyncpg returns jsonb as a JSON string unless a codec is registered.
    edge = _to_edge(
        {"source_id": "a", "target_id": "b", "relation": "works_at", "metadata": '{"role":"Partner"}'}
    )
    assert edge.metadata == {"role": "Partner"}


def test_to_event_handles_jsonb_string_body_and_metadata():
    ev = _to_event(
        TENANT,
        {"id": "m1", "type": "meeting", "occurred_at": "2026-05-01T00:00:00+00:00", "subject": "X",
         "body": '[{"type":"paragraph","text":"hi"}]', "source": "crm", "external_id": "e",
         "metadata": '{"participants_raw":[{"email":"x@y.com"}]}'},
        [],
    )
    assert ev.body == "hi"
    assert ev.metadata.get("participants_raw") == [{"email": "x@y.com"}]


def test_flatten_blocks_joins_paragraph_text():
    blocks = [
        {"type": "paragraph", "text": "First line."},
        {"type": "image", "src": "http://x/y.png"},
        {"type": "paragraph", "text": "Second line."},
    ]
    assert _flatten_blocks(blocks) == "First line.\n\nSecond line."
    assert _flatten_blocks([]) == ""
    assert _flatten_blocks(None) == ""


def test_to_event_meeting_keeps_title_email_hides_subject():
    occurred = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    meeting = {
        "id": "m1", "type": "meeting", "occurred_at": occurred, "subject": "Board sync",
        "body": [{"type": "paragraph", "text": "Notes here"}], "source": "crm",
        "external_id": "crm_meeting:abc", "metadata": {},
    }
    ev = _to_event(TENANT, meeting, [("person", "p1", "attendee")])
    assert ev.label == "Board sync"           # meeting title is org-visible
    assert ev.body == "Notes here"
    assert ev.participants == [("person", "p1", "attendee")]
    assert ev.occurred_at == "2026-05-01T09:00:00+00:00"

    email = {
        "id": "e1", "type": "email", "occurred_at": occurred, "subject": "Secret terms",
        "body": [{"type": "paragraph", "text": "Confidential body"}], "source": "gmail",
        "external_id": "<msg-1>", "metadata": {},
    }
    ev2 = _to_event(TENANT, email, [("person", "p2", "from")])
    assert "Secret terms" not in ev2.label     # email subject must not leak onto the org-wide node
    assert ev2.subject == "Secret terms"        # but is carried for the private body
    assert ev2.body == "Confidential body"


def test_to_note_visibility_and_links():
    row = {"id": "n1", "body": "Great team", "author_email": "ana@kibo.com",
           "visibility": "private", "created_at": "2026-05-02T00:00:00+00:00"}
    note = _to_note(TENANT, row, [("company", "c1"), ("person", "p1")])
    assert note.private is True
    assert note.author_email == "ana@kibo.com"
    assert note.links == [("company", "c1"), ("person", "p1")]
    assert note.body == "Great team"

    org = _to_note(TENANT, {**row, "visibility": "org"}, [])
    assert org.private is False


def test_to_deal_namespaces_attributes_per_list():
    field_defs = [
        {"key": "priority", "label": "Priority", "type": "select"},
        {"key": "deal_size", "label": "Deal size", "type": "currency"},
    ]
    deal = _to_deal(
        company_id="c1",
        list_name="Dealflow",
        stage_name="Diligence",
        owner_emails=["ana@kibo.com"],
        field_values={"priority": "high", "deal_size": 5000000},
        field_defs=field_defs,
    )
    assert deal.company_id == "c1"
    attrs = {k: (v, dt) for (k, v, dt) in deal.attributes}
    assert attrs["Dealflow:Stage"] == ("Diligence", "string")
    # owners is a JSON array — must use the valid enum value "json", not "array"
    assert attrs["Dealflow:Owners"] == (["ana@kibo.com"], "json")
    assert attrs["Dealflow:Priority"] == ("high", "string")
    assert attrs["Dealflow:Deal size"] == (5000000, "number")


# ── adapter fetch with a stubbed connection ─────────────────────────


class _FakeConn:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.closed = False

    async def fetch(self, sql, *args):
        if "FROM entities" in sql:
            return self._tables.get("entities", [])
        if "FROM entity_emails" in sql:
            return self._tables.get("entity_emails", [])
        return []

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_fetch_entities_normalizes_and_closes():
    conn = _FakeConn({
        "entities": [
            {"id": "c1", "kind": "company", "name": "Acme", "domain": "acme.com"},
            {"id": "p1", "kind": "person", "full_name": "Ana", "email": "ana@kibo.com"},
        ],
        "entity_emails": [{"entity_id": "p1", "email": "ana@kibo.com", "is_primary": True}],
    })

    async def fake_connect(dsn):
        assert dsn == DSN
        return conn

    ents = await AffinidadAdapter().fetch_entities(_firm(), connect=fake_connect)
    assert conn.closed is True
    keys = {e.canonical_key for e in ents}
    assert f"company::{TENANT}::acme.com" in keys
    assert f"person::{TENANT}::ana@kibo.com" in keys


# ── orchestration: graph writes + access-class tiering ──────────────

from unittest.mock import AsyncMock  # noqa: E402

from pipeline.adapters.affinidad import CrmEdge  # noqa: E402
from pipeline.api import ingest as ingest_mod  # noqa: E402
from pipeline.client import EdgeFunctionClient  # noqa: E402


def _aclient() -> EdgeFunctionClient:
    c = AsyncMock(spec=EdgeFunctionClient)
    c.insert_pointer.return_value = {"status": "created", "pointer_id": "ptr-1"}
    c.ingest_document.return_value = {"status": "created", "pointer_id": "doc-1"}
    c.link_pointers.return_value = {"status": "linked"}
    return c


def _patch_access(monkeypatch):
    ensure_class = AsyncMock(return_value="class-id-1")
    ensure_user_grant = AsyncMock()
    monkeypatch.setattr(ingest_mod, "ensure_class", ensure_class)
    monkeypatch.setattr(ingest_mod, "ensure_user_grant", ensure_user_grant)
    return ensure_class, ensure_user_grant


@pytest.mark.asyncio
async def test_ingest_crm_entity_company_attributes_and_class():
    client = _aclient()
    ent = _to_entity(
        TENANT, {"id": "c1", "kind": "company", "name": "Acme", "domain": "acme.com", "sector": "Fintech"}, {}
    )
    resp = await ingest_mod._ingest_crm_entity(client, ent, f"firm:{TENANT}")
    kw = client.insert_pointer.call_args.kwargs
    assert kw["type"] == "company"
    assert kw["canonical_key"] == f"company::{TENANT}::acme.com"
    assert kw["access_class"] == f"firm:{TENANT}"
    triples = {(a["key"], a["value"], a["data_type"]) for a in kw["attributes"]}
    assert ("Sector", "Fintech", "string") in triples
    assert resp["pointer_id"] == "ptr-1"


@pytest.mark.asyncio
async def test_ingest_crm_edge_links_resolved_endpoints():
    client = _aclient()

    async def resolve(eid):
        return {"p1": "ptr-p1", "c1": "ptr-c1"}.get(eid)

    await ingest_mod._ingest_crm_edge(client, CrmEdge("p1", "c1", "works_at", {"role": "Partner"}), resolve)
    kw = client.link_pointers.call_args.kwargs
    assert kw["source_id"] == "ptr-p1"
    assert kw["target_id"] == "ptr-c1"
    assert kw["relationship_type"] == "works_at"


@pytest.mark.asyncio
async def test_ingest_crm_edge_skips_when_endpoint_unresolved():
    client = _aclient()

    async def resolve(eid):
        return None

    await ingest_mod._ingest_crm_edge(client, CrmEdge("x", "y", "works_at", {}), resolve)
    client.link_pointers.assert_not_called()


@pytest.mark.asyncio
async def test_apply_deal_attributes_upserts_on_company_pointer():
    client = _aclient()
    ent = _to_entity(TENANT, {"id": "c1", "kind": "company", "name": "Acme", "domain": "acme.com"}, {})
    deal = _to_deal(
        company_id="c1", list_name="Dealflow", stage_name="Diligence",
        owner_emails=["a@k.com"], field_values={}, field_defs=[],
    )
    await ingest_mod._apply_deal_attributes(client, deal, {"c1": ent}, f"firm:{TENANT}")
    kw = client.insert_pointer.call_args.kwargs
    assert kw["type"] == "company"
    assert kw["canonical_key"] == f"company::{TENANT}::acme.com"
    keys = {a["key"] for a in kw["attributes"]}
    assert "Dealflow:Stage" in keys and "Dealflow:Owners" in keys


@pytest.mark.asyncio
async def test_ingest_crm_note_org_is_firm_wide_and_links(monkeypatch):
    ensure_class, _ = _patch_access(monkeypatch)
    client = _aclient()

    async def resolve_link(entity_type, entity_id):
        return {"c1": "ptr-c1"}.get(entity_id)

    note = _to_note(
        TENANT,
        {"id": "n1", "body": "Great", "author_email": "a@k.com", "visibility": "org",
         "created_at": "2026-05-01T00:00:00+00:00"},
        [("company", "c1")],
    )
    await ingest_mod._ingest_crm_note(AsyncMock(), client, note, f"firm:{TENANT}", {}, resolve_link)
    doc_kw = client.ingest_document.call_args.kwargs
    assert doc_kw["access_class"] == f"firm:{TENANT}"
    ensure_class.assert_not_called()
    lk = client.link_pointers.call_args.kwargs
    assert lk["source_id"] == "doc-1" and lk["target_id"] == "ptr-c1"
    assert lk["relationship_type"] == "note_about"


@pytest.mark.asyncio
async def test_ingest_crm_note_private_grants_author(monkeypatch):
    ensure_class, ensure_user_grant = _patch_access(monkeypatch)
    client = _aclient()

    async def resolve_link(entity_type, entity_id):
        return None

    note = _to_note(
        TENANT,
        {"id": "n1", "body": "secret", "author_email": "a@k.com", "visibility": "private",
         "created_at": "2026-05-01T00:00:00+00:00"},
        [],
    )
    await ingest_mod._ingest_crm_note(
        AsyncMock(), client, note, f"firm:{TENANT}", {"a@k.com": "uid-a"}, resolve_link
    )
    ensure_class.assert_awaited_once()
    assert ensure_class.call_args.args[1] == f"affinidadnote:{TENANT}:n1"
    doc_kw = client.ingest_document.call_args.kwargs
    assert doc_kw["access_class"] == f"affinidadnote:{TENANT}:n1"
    ensure_user_grant.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_crm_event_node_firm_wide_body_private_with_grants(monkeypatch):
    ensure_class, ensure_user_grant = _patch_access(monkeypatch)
    client = _aclient()
    p = _to_entity(TENANT, {"id": "p1", "kind": "person", "full_name": "Ana", "email": "ana@kibo.com"}, {})

    async def resolve(eid):
        return {"p1": "ptr-p1"}.get(eid)

    ev = _to_event(
        TENANT,
        {"id": "m1", "type": "meeting", "occurred_at": "2026-05-01T09:00:00+00:00", "subject": "Board",
         "body": [{"type": "paragraph", "text": "notes"}], "source": "crm", "external_id": "crm_meeting:x",
         "metadata": {}},
        [("person", "p1", "attendee")],
    )
    await ingest_mod._ingest_crm_event(
        AsyncMock(), client, ev, f"firm:{TENANT}", {"ana@kibo.com": "uid-a"}, resolve, {"p1": p}
    )
    ev_kw = client.insert_pointer.call_args.kwargs
    assert ev_kw["type"] == "event"
    assert ev_kw["canonical_key"] == event_key(TENANT, "m1")
    assert ev_kw["access_class"] == f"firm:{TENANT}"
    roles = {c.kwargs["relationship_type"] for c in client.link_pointers.call_args_list}
    assert "attendee" in roles
    assert ensure_class.call_args.args[1] == f"affinidadevent:{TENANT}:m1"
    doc_kw = client.ingest_document.call_args.kwargs
    assert doc_kw["access_class"] == f"affinidadevent:{TENANT}:m1"
    assert doc_kw["link"]["target_id"] == "ptr-1"  # body linked to the event node
    ensure_user_grant.assert_awaited()  # internal participant granted


@pytest.mark.asyncio
async def test_ingest_crm_event_no_body_skips_document(monkeypatch):
    _patch_access(monkeypatch)
    client = _aclient()

    async def resolve(eid):
        return None

    ev = _to_event(
        TENANT,
        {"id": "e9", "type": "email", "occurred_at": "2026-05-01T00:00:00+00:00", "subject": None,
         "body": [], "source": "gmail", "external_id": "<m>", "metadata": {}},
        [],
    )
    await ingest_mod._ingest_crm_event(AsyncMock(), client, ev, f"firm:{TENANT}", {}, resolve, {})
    client.insert_pointer.assert_awaited_once()  # event node only
    client.ingest_document.assert_not_called()
