"""Calendar entity extraction: events → graph entities + edges.

Mirrors the email/notes extractors and reuses the same `classify_address` brain.
Per event: an `event` node (deduped by iCalUID), the owner `attended`, every other
attendee `attended_by`, external attendees `affiliated_with` their company, and the
event `regarding` those companies.
"""

from __future__ import annotations

from pipeline.adapters.calendar import CalendarEvent
from pipeline.adapters.calendar_entities import event_key, extract_graph

TENANT = "T1"
OWN = {"kiboventures.com"}
CRM = {"poseidon.vc": "Poseidon"}


def _event(**kw) -> CalendarEvent:
    base = dict(
        tenant_id=TENANT,
        calendar_email="gp@kiboventures.com",
        owner_name="Guillermo Puebla",
        ical_uid="uid-1@google.com",
        event_id="evt1",
        title="Sync with Poseidon",
        start="2026-06-25T10:00:00Z",
        end="2026-06-25T11:00:00Z",
        location="Zoom",
        description="Agenda.",
        organizer=("gp@kiboventures.com", "Guillermo Puebla"),
        attendees=[("lp@poseidon.vc", "Laura Páez")],
    )
    base.update(kw)
    return CalendarEvent(**base)


def _graph(*events):
    return extract_graph(
        list(events), crm_domains=set(CRM), crm_names=CRM, own_domains=OWN
    )


def test_builds_event_node_with_metadata():
    g = _graph(_event())
    ents = {e.canonical_key: e for e in g.entities}
    ev_ck = f"event:{TENANT}:gcal:uid-1@google.com"
    assert ev_ck == event_key(TENANT, "uid-1@google.com")
    ev = ents[ev_ck]
    assert ev.type == "event"
    assert ev.label == "Sync with Poseidon"
    assert ev.occurred_at == "2026-06-25T10:00:00Z"
    assert ev.metadata["event_type"] == "meeting"
    assert ev.metadata["location"] == "Zoom"
    assert ev.metadata["end"] == "2026-06-25T11:00:00Z"
    assert ev.metadata["organizer_email"] == "gp@kiboventures.com"
    assert ev.metadata["provider"] == "google-calendar"
    assert ev.metadata["calendar_email"] == "gp@kiboventures.com"


def test_attendance_edges_and_entities():
    g = _graph(_event())
    ev_ck = f"event:{TENANT}:gcal:uid-1@google.com"
    gp = f"person::gp@kiboventures.com"
    lp = f"person::lp@poseidon.vc"
    company = f"company::{TENANT}::poseidon.vc"

    keys = {e.canonical_key for e in g.entities}
    assert {ev_ck, gp, lp, company} <= keys
    # owner is a colleague (own domain) → no company node for kiboventures.com
    assert f"company::{TENANT}::kiboventures.com" not in keys

    edges = {(e.source, e.rel, e.target) for e in g.edges}
    # owner and attendee share the same relation/direction — both `attended`
    assert (gp, "attended", ev_ck) in edges
    assert (lp, "attended", ev_ck) in edges
    assert not any(rel == "attended_by" for _s, rel, _t in edges)
    assert (lp, "affiliated_with", company) in edges
    assert (ev_ck, "regarding", company) in edges


def test_person_label_is_name_with_email_fallback():
    g = _graph(_event(attendees=[("anon@poseidon.vc", None)]))
    persons = {e.canonical_key: e.label for e in g.entities if e.type == "person"}
    assert persons[f"person::gp@kiboventures.com"] == "Guillermo Puebla"
    # no display name → label falls back to the address
    assert persons[f"person::anon@poseidon.vc"] == "anon@poseidon.vc"


def test_same_event_on_two_calendars_dedups_by_ical_uid():
    # Same meeting, fetched from gp's and lp's calendars (owner differs, attendees
    # mirrored). One event node; both owners end up attending it.
    from_gp = _event(calendar_email="gp@kiboventures.com", owner_name="Guillermo Puebla",
                     attendees=[("lp@poseidon.vc", "Laura Páez")])
    from_lp = _event(calendar_email="lp@poseidon.vc", owner_name="Laura Páez",
                     organizer=("gp@kiboventures.com", "Guillermo Puebla"),
                     attendees=[("gp@kiboventures.com", "Guillermo Puebla")])
    g = _graph(from_gp, from_lp)

    events = [e for e in g.entities if e.type == "event"]
    assert len(events) == 1

    ev_ck = f"event:{TENANT}:gcal:uid-1@google.com"
    gp = f"person::gp@kiboventures.com"
    lp = f"person::lp@poseidon.vc"
    edges = {(e.source, e.rel, e.target) for e in g.edges}
    assert (gp, "attended", ev_ck) in edges
    assert (lp, "attended", ev_ck) in edges
