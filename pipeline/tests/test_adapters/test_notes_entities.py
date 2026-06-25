from __future__ import annotations

import pytest

from pipeline.adapters.notes import MeetingNote
from pipeline.adapters.notes_entities import (
    build_company_index,
    event_key,
    extract_graph,
    name_from_email,
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
# email → name directory (CRM person nodes + firm team table). A person is only
# materialized when their email resolves to a name here (or is the owner).
NAMES = {"lp@poseidon.vc": "Laura Páez", "someone@gmail.com": "Sam One"}


def _graph(note: MeetingNote, *, crm_names=CRM_NAMES, own=OWN, names=NAMES):
    return extract_graph(
        [note],
        crm_domains=set(crm_names),
        crm_names=crm_names,
        name_to_domain=build_company_index(crm_names),
        own_domains=own,
        name_by_email=names,
    )


def _person(entities, ck):
    return next(e for e in entities if e.type == "person" and e.canonical_key == ck)


def _email_attr(entity):
    return next((a for a in entity.attributes if a["key"] == "email"), None)


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


# ── name extraction from the email local-part ──────────────────────


def test_name_from_email_extracts_confident_names():
    assert name_from_email("pablo.campos@oliverwyman.com") == "Pablo Campos"
    assert name_from_email("jose.carazo@bluenomics.es") == "Jose Carazo"
    assert name_from_email("agustin.gomezmoreno@bluenomics.es") == "Agustin Gomezmoreno"
    assert name_from_email("ana.maria.lopez@x.com") == "Ana Maria Lopez"
    assert name_from_email("maria-jose.garcia@x.com") == "Maria Jose Garcia"
    # accents preserved + title-cased
    assert name_from_email("josé.garcía@x.com") == "José García"
    # +tag is stripped before parsing
    assert name_from_email("pablo.campos+invite@x.com") == "Pablo Campos"


def test_name_from_email_drops_when_unsure():
    assert name_from_email("claudiagarcia@adimpulsa.es") is None  # single mashed token
    assert name_from_email("pablo@x.com") is None                 # first name only
    assert name_from_email("j.carazo@x.com") is None              # initial (token < 2)
    assert name_from_email("user123.smith@x.com") is None         # digits in a token
    assert name_from_email("sales.team@x.com") is None            # generic/role words
    assert name_from_email("info.madrid@x.com") is None           # role word present
    assert name_from_email("") is None


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


# ── meeting identity / collapsing duplicate note-pages ──────────────


def test_event_key_dedups_same_meeting_across_note_pages():
    a = _note(page_id="pgA", title="Weekly", scheduled_at="2026-06-25T09:30:00+02:00")
    b = _note(page_id="pgB", title="Weekly", scheduled_at="2026-06-25T09:30:00+02:00")
    assert event_key(TENANT, a) == event_key(TENANT, b)        # same meeting → one key
    c = _note(page_id="pgC", title="Weekly", scheduled_at="2026-07-02T09:30:00+02:00")
    assert event_key(TENANT, a) != event_key(TENANT, c)        # next occurrence → distinct


def test_event_key_falls_back_to_page_id_without_slot():
    assert event_key(TENANT, _note(page_id="pg-1", scheduled_at=None)) == \
        f"event:{TENANT}:meetingnote:pg-1"


def test_two_note_pages_of_one_meeting_make_one_event_with_unioned_attendees():
    slot = "2026-06-25T09:30:00+02:00"
    a = _note(page_id="pgA", title="Weekly", scheduled_at=slot,
              owner_email="gp@kiboventures.com", owner_name="Guille Puebla",
              attendees=["lp@poseidon.vc"])
    b = _note(page_id="pgB", title="Weekly", scheduled_at=slot,
              owner_email="sk@kiboventures.com", owner_name="Sakhee K",
              attendees=["lp@poseidon.vc"])
    g = extract_graph(
        [a, b], crm_domains=set(CRM_NAMES), crm_names=CRM_NAMES,
        name_to_domain=build_company_index(CRM_NAMES), own_domains=OWN,
        name_by_email={"lp@poseidon.vc": "Laura Páez"},
    )
    events = [e for e in g.entities if e.type == "event"]
    assert len(events) == 1                                     # collapsed to one meeting
    ev = events[0].canonical_key
    attended = {e.source for e in g.edges if e.rel == "attended" and e.target == ev}
    assert attended == {
        f"person::gp@kiboventures.com",              # both note-takers/owners
        f"person::sk@kiboventures.com",
        f"person::lp@poseidon.vc",                   # + the shared attendee
    }


# ── owner ───────────────────────────────────────────────────────────


def test_resolved_owner_attends_as_named_person_with_email_attribute():
    g = _graph(_note(owner_email="gp@kiboventures.com", owner_name="Guillermo Puebla"))
    owner_ck = f"person::gp@kiboventures.com"
    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    owner = _person(g.entities, owner_ck)
    # label is the NAME, not the email; email lives as an attribute
    assert owner.label == "Guillermo Puebla"
    assert _email_attr(owner) == {
        "key": "email", "value": "gp@kiboventures.com",
        "data_type": "string", "source": "notes",
    }
    assert (owner_ck, event_ck) in _edges(g.edges, "attended")
    # own-domain colleague: no company node, no affiliation
    assert _ck(g.entities, "company") == set()


def test_unresolved_owner_is_dropped_not_slugged():
    g = _graph(_note(owner_email=None, owner_name="Mystery Person"))
    # No person at all (no name:slug fallback), and nothing attended.
    assert _ck(g.entities, "person") == set()
    assert _edges(g.edges, "attended") == set()


# ── attendees: named → person+email attr; unnamed → dropped ─────────


def test_named_attendee_at_crm_domain_gets_company_and_affiliation():
    g = _graph(_note(owner_email=None, attendees=["lp@poseidon.vc"]))
    person_ck = f"person::lp@poseidon.vc"
    company_ck = f"company::{TENANT}::poseidon.vc"
    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    person = _person(g.entities, person_ck)
    assert person.label == "Laura Páez"  # name, never the email
    assert _email_attr(person)["value"] == "lp@poseidon.vc"
    assert company_ck in _ck(g.entities, "company")
    assert (person_ck, event_ck) in _edges(g.edges, "attended")
    assert (person_ck, company_ck) in _edges(g.edges, "affiliated_with")


def test_unnamed_attendee_is_dropped_but_company_and_about_remain():
    # lp@poseidon.vc is NOT in the name directory → no person, no attended,
    # no affiliation. But the company (CRM-known) and the about edge still hold:
    # someone from that org was demonstrably in the room.
    g = _graph(
        _note(owner_email=None, external_org="poseidon-vc", attendees=["lp@poseidon.vc"]),
        names={},
    )
    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    company_ck = f"company::{TENANT}::poseidon.vc"
    assert _ck(g.entities, "person") == set()
    assert _edges(g.edges, "attended") == set()
    assert _edges(g.edges, "affiliated_with") == set()
    assert company_ck in _ck(g.entities, "company")
    assert (event_ck, "about", company_ck) in {(e.source, e.rel, e.target) for e in g.edges}


def test_attendee_name_derived_from_email_when_not_in_directory():
    # Not in the directory, but the local-part is confidently a name → person
    # with the derived label + email attribute + attended (no company: the domain
    # isn't CRM-known).
    g = _graph(_note(owner_email=None, attendees=["pablo.campos@oliverwyman.com"]), names={})
    person_ck = f"person::pablo.campos@oliverwyman.com"
    event_ck = f"event:{TENANT}:meetingnote:pg-1"
    person = _person(g.entities, person_ck)
    assert person.label == "Pablo Campos"
    assert _email_attr(person)["value"] == "pablo.campos@oliverwyman.com"
    assert (person_ck, event_ck) in _edges(g.edges, "attended")


def test_attendee_dropped_when_email_not_a_confident_name():
    g = _graph(_note(owner_email=None, attendees=["claudiagarcia@adimpulsa.es"]), names={})
    assert _ck(g.entities, "person") == set()
    assert _edges(g.edges, "attended") == set()


# ── dropped participants are recorded as rejections (debug log) ─────


def test_unnamed_attendee_recorded_as_rejection():
    g = _graph(
        _note(owner_email=None, attendees=["claudiagarcia@adimpulsa.es"]),
        names={},
    )
    assert len(g.rejections) == 1
    r = g.rejections[0]
    assert r.reason == "unnamed_attendee"
    assert r.attendee == "claudiagarcia@adimpulsa.es"
    assert r.page_id == "pg-1"
    assert r.title == "Ext. Call Poseidon"
    assert r.tenant_id == TENANT


def test_unresolved_owner_recorded_as_rejection():
    g = _graph(_note(owner_email="ghost@kiboventures.com", owner_name=None))
    assert [(r.reason, r.attendee) for r in g.rejections] == [
        ("unresolved_owner", "ghost@kiboventures.com"),
    ]


def test_named_participants_produce_no_rejections():
    g = _graph(_note(attendees=["lp@poseidon.vc"]))  # owner + attendee both named
    assert g.rejections == []


def test_role_mailbox_attendee_is_not_a_rejection():
    # info@ resolves to a company, not a dropped person → no rejection noise.
    g = _graph(_note(owner_email=None, attendees=["info@poseidon.vc"]), names={})
    assert g.rejections == []


def test_no_person_is_ever_labelled_with_an_email():
    g = _graph(_note(owner_email="gp@kiboventures.com", attendees=["lp@poseidon.vc", "x@nope.com"]))
    for e in g.entities:
        if e.type == "person":
            assert not ("@" in e.label and " " not in e.label), e.label


def test_named_free_mail_attendee_is_person_only():
    g = _graph(_note(owner_email=None, attendees=["someone@gmail.com"]))
    person = _person(g.entities, f"person::someone@gmail.com")
    assert person.label == "Sam One"
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
