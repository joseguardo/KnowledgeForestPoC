from __future__ import annotations

import pytest

from pipeline.adapters.notes import MeetingNote
from pipeline.adapters.notes_entities import (
    build_company_index,
    extract_graph,
    normalize_company_name,
    resolve_company_domain,
)

TENANT = "baa52eca-4c88-4861-9d45-720e743febb4"


def _note(**kw) -> MeetingNote:
    base = dict(
        tenant_id=TENANT,
        page_id="pg-1",
        title="Ext. Call Poseidon",
        occurred_at="2026-06-19T09:00:00+00:00",
        last_edited="2026-06-19T10:41:00+00:00",
        owner_name="Guillermo Puebla",
        owner_email="gp@kiboventures.com",
        attendees=[],
        external_org=None,
        confidential=False,
        body="",
    )
    base.update(kw)
    return MeetingNote(**base)


# Company context the firm's CRM provides: a Poseidon company keyed by its domain,
# plus a colleague's own firm. own_domains marks the firm's people as colleagues.
CRM_NAMES = {"poseidon.vc": "Poseidon"}
OWN = {"kiboventures.com"}


def _graph(note: MeetingNote, *, crm_names=CRM_NAMES, own=OWN):
    return extract_graph(
        [note],
        crm_domains=set(crm_names),
        crm_names=crm_names,
        name_to_domain=build_company_index(crm_names),
        own_domains=own,
    )


def _ck(entities, type_):
    return {e.canonical_key for e in entities if e.type == type_}


def _edges(edges, rel):
    return {(e.source, e.target) for e in edges if e.rel == rel}


# ── company-name normalization (the dedup brain) ────────────────────


def test_normalize_collapses_spelling_variants():
    # The three free-text spellings the rework must unify onto one node.
    assert (
        normalize_company_name("Poseidon")
        == normalize_company_name("Poseidon Inc.")
        == normalize_company_name("poseidon-vc")
        == "poseidon"
    )


def test_normalize_blank_is_empty():
    assert normalize_company_name("") == ""
    assert normalize_company_name(None) == ""


def test_build_company_index_and_resolve():
    idx = build_company_index({"poseidon.vc": "Poseidon", "fossa.io": "Fossa Capital"})
    assert resolve_company_domain("poseidon-vc", idx) == "poseidon.vc"
    assert resolve_company_domain("Fossa", idx) == "fossa.io"
    assert resolve_company_domain("Unknown Co", idx) is None
    assert resolve_company_domain(None, idx) is None


# ── event node ──────────────────────────────────────────────────────


def test_event_node_keyed_by_page_id():
    g = _graph(_note())
    (event,) = [e for e in g.entities if e.type == "event"]
    assert event.canonical_key == f"event:{TENANT}:meetingnote:pg-1"
    assert event.label == "Ext. Call Poseidon"
    assert event.occurred_at == "2026-06-19T09:00:00+00:00"
    assert event.metadata["event_type"] == "meeting"


def test_event_occurred_at_falls_back_to_last_edited():
    g = _graph(_note(occurred_at=None))
    (event,) = [e for e in g.entities if e.type == "event"]
    assert event.occurred_at == "2026-06-19T10:41:00+00:00"


# ── owner ───────────────────────────────────────────────────────────


def test_resolved_owner_attends_as_person():
    g = _graph(_note(owner_email="gp@kiboventures.com"))
    owner_ck = f"person::{TENANT}::gp@kiboventures.com"
    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    assert owner_ck in _ck(g.entities, "person")
    assert (owner_ck, event_ck) in _edges(g.edges, "attended")
    # own-domain colleague: no company node, no affiliation
    assert _ck(g.entities, "company") == set()


def test_unresolved_owner_is_dropped_not_slugged():
    g = _graph(_note(owner_email=None, owner_name="Mystery Person"))
    # No person at all (no name:slug fallback), and nothing attended.
    assert _ck(g.entities, "person") == set()
    assert _edges(g.edges, "attended") == set()


# ── attendees via classify_address ──────────────────────────────────


def test_attendee_at_crm_domain_gets_company_and_affiliation():
    g = _graph(_note(owner_email=None, attendees=["lp@poseidon.vc"]))
    person_ck = f"person::{TENANT}::lp@poseidon.vc"
    company_ck = f"company::{TENANT}::poseidon.vc"
    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    assert person_ck in _ck(g.entities, "person")
    assert company_ck in _ck(g.entities, "company")
    assert (person_ck, event_ck) in _edges(g.edges, "attended")
    assert (person_ck, company_ck) in _edges(g.edges, "affiliated_with")


def test_free_mail_attendee_is_person_only():
    g = _graph(
        _note(owner_email=None, attendees=["someone@gmail.com"]),
        crm_names=CRM_NAMES,
    )
    assert f"person::{TENANT}::someone@gmail.com" in _ck(g.entities, "person")
    assert _ck(g.entities, "company") == set()


def test_role_mailbox_attendee_is_company_only_no_attended():
    g = _graph(_note(owner_email=None, attendees=["info@poseidon.vc"]))
    assert _ck(g.entities, "person") == set()
    assert f"company::{TENANT}::poseidon.vc" in _ck(g.entities, "company")
    # a role mailbox is not a meeting attendee
    assert _edges(g.edges, "attended") == set()


def test_noise_attendee_is_dropped():
    g = _graph(_note(owner_email=None, attendees=["no-reply@poseidon.vc"]))
    assert _ck(g.entities, "person") == set()


# ── the about edge (external_org), gated on an external member present ──


def test_about_edge_when_external_org_resolves_and_member_present():
    g = _graph(_note(external_org="poseidon-vc", attendees=["lp@poseidon.vc"]))
    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    company_ck = f"company::{TENANT}::poseidon.vc"
    assert (event_ck, company_ck) in _edges(g.edges, "about")


def test_no_about_edge_when_resolved_company_has_no_attendee():
    # external_org resolves, but nobody from that domain is in the room → no edge,
    # and no orphan company node.
    g = _graph(_note(external_org="Poseidon", attendees=["someone@gmail.com"]))
    assert _edges(g.edges, "about") == set()
    assert f"company::{TENANT}::poseidon.vc" not in _ck(g.entities, "company")


def test_no_about_edge_when_external_org_unresolvable():
    g = _graph(_note(external_org="Totally Unknown LLC", attendees=["lp@poseidon.vc"]))
    assert _edges(g.edges, "about") == set()
