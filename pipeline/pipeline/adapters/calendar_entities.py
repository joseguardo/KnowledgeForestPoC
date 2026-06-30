"""Turn calendar events into the graph entities + edges they imply.

The calendar mirror of `email_entities` / `notes_entities`: deterministic, no I/O,
no LLM, reusing the same `classify_address` brain so calendar, email and notes
agree on what an address means (human → person (+ company iff its domain
qualifies), role mailbox → company-only, free-mail → person-only, own domain →
colleague, noise → dropped).

Per event it emits:
  - one `event` node, keyed `event:{tenant}:gcal:{iCalUID}` so the same meeting on
    every attendee's calendar collapses to one node;
  - `person -attended-> event` for the calendar owner AND every other human
    participant — one symmetric relationship, no owner/attendee distinction;
  - `person -affiliated_with-> company` for participants at a qualifying domain;
  - `event -regarding-> company` for those companies;
  - for a recurring meeting: each occurrence carries `is_recurring`/`series_id` in
    its metadata and links `event -instance_of-> <series node>` (a parent node
    keyed by Google's recurringEventId, shared by all occurrences). One-off events
    have `is_recurring=False` and no series node.

People are keyed by email so calendar attendance reconciles onto existing person/
company nodes. Calendars have no outbound correspondence signal, so a domain
qualifies as a company only via the CRM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pipeline.adapters.email_entities import (
    Edge,
    Entity,
    Extraction,
    _looks_like_email,
    classify_address,
)
from pipeline.adapters.notes_entities import name_from_email

if TYPE_CHECKING:
    from pipeline.adapters.calendar import CalendarEvent


def event_key(tenant: str, ical_uid: str) -> str:
    """Canonical key for a calendar event node, keyed by its iCalUID."""
    return f"event:{tenant}:gcal:{ical_uid}"


def series_key(tenant: str, recurring_event_id: str) -> str:
    """Canonical key for a recurring-meeting *series* node, keyed by Google's
    recurringEventId so every occurrence groups under one series."""
    return f"event:{tenant}:gcal-series:{recurring_event_id}"


def extract_graph(
    events: list[CalendarEvent],
    *,
    crm_domains: set[str],
    crm_names: dict[str, str],
    own_domains: set[str],
    name_by_email: dict[str, str] | None = None,
    free_mail_domains: set[str] | None = None,
    role_localparts: set[str] | None = None,
) -> Extraction:
    """Deterministic core of calendar ingestion (see module docstring)."""
    names = name_by_email or {}
    entities: dict[str, Entity] = {}
    edges: list[Edge] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_entity(e: Entity) -> None:
        existing = entities.get(e.canonical_key)
        if existing is None:
            entities[e.canonical_key] = e
        elif e.type == "person" and _looks_like_email(existing.label) and not _looks_like_email(e.label):
            # A later event names a person first seen as a bare address — upgrade.
            existing.label = e.label

    def add_edge(source: str, rel: str, target: str, why: str | None = None) -> None:
        if not source or not target:
            return
        k = (source, rel, target)
        if k not in seen_edges:
            seen_edges.add(k)
            edges.append(Edge(source, target, rel, why))

    def classify_participant(tenant: str, addr: str, name: str | None) -> tuple[str | None, str | None]:
        """Register the entities an address implies (+ the person's
        `affiliated_with` edge) and return (person_ck, company_ck)."""
        # Google usually omits attendee display names, so resolve like Notes does:
        # the provided name, else the graph's person directory, else a confident
        # email-local-part guess, else None (label falls back to the address).
        resolved = name or names.get((addr or "").strip().lower()) or name_from_email(addr)
        c = classify_address(
            addr, resolved, crm_domains=crm_domains, correspondent_domains=set(),
            own_domains=own_domains, crm_names=crm_names,
            free_mail_domains=free_mail_domains, role_localparts=role_localparts,
        )
        person_ck = company_ck = None
        if c.person:
            person_ck = f"person::{c.person.email}"  # global identity (cross-tenant)
            add_entity(Entity(person_ck, "person", c.person.name or c.person.email))
        if c.company:
            company_ck = f"company::{tenant}::{c.company.domain}"
            add_entity(Entity(company_ck, "company", c.company.label))
        if person_ck and company_ck:
            add_edge(person_ck, "affiliated_with", company_ck,
                     why=f"{c.person.email} is at {c.company.domain}")
        return person_ck, company_ck

    for ev in events:
        tenant = ev.tenant_id
        event_ck = event_key(tenant, ev.ical_uid)
        add_entity(Entity(
            event_ck, "communication", ev.title, occurred_at=ev.start,
            metadata={
                "event_type": "meeting",
                "location": ev.location,
                "end": ev.end,
                "organizer_email": ev.organizer[0] or None,
                "provider": "google-calendar",
                "calendar_email": ev.calendar_email,
                "is_recurring": bool(ev.recurring_event_id),
                "series_id": ev.recurring_event_id,
            },
        ))

        # Recurring occurrence → group it under a shared series node. Each
        # occurrence stays its own event (distinct iCalUID); the series is a
        # parent the whole recurring meeting hangs off (no attendance of its own).
        if ev.recurring_event_id:
            series_ck = series_key(tenant, ev.recurring_event_id)
            add_entity(Entity(
                series_ck, "communication", ev.title,
                metadata={
                    "event_type": "meeting_series",
                    "provider": "google-calendar",
                    "series_id": ev.recurring_event_id,
                },
            ))
            add_edge(event_ck, "instance_of", series_ck, why="occurrence of this recurring meeting")

        # Owner and every other participant relate to the event the same way:
        # `person -attended-> event` (symmetric — no owner/attendee distinction).
        owner_person, _ = classify_participant(tenant, ev.calendar_email, ev.owner_name)
        if owner_person:
            add_edge(owner_person, "attended", event_ck, why="attended this meeting")

        for addr, name in ev.attendees:
            person_ck, company_ck = classify_participant(tenant, addr, name)
            if person_ck:
                add_edge(person_ck, "attended", event_ck, why=f"{addr} attended this meeting")
            if company_ck:
                add_edge(event_ck, "regarding", company_ck, why=f"meeting with {company_ck.split('::')[-1]}")

    return Extraction(list(entities.values()), edges)
