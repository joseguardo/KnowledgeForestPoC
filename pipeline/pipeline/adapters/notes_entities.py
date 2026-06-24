"""Turn a batch of meeting notes into the graph entities + edges they imply.

The notes mirror of `email_entities`: deterministic, no I/O, no LLM. It reuses
the *same* classification brain (`classify_address`) so notes and email agree on
what an address means — human → person (+ company iff its domain qualifies),
role mailbox → company-only, free-mail → person-only, own domain → colleague,
noise → dropped.

Per meeting it emits:
  - one `event` (the meeting), keyed `event:{tenant}:meetingnote:{page_id}`;
  - `person -attended-> event` for the owner (when resolvable) and every human
    attendee — no separate "hosted"/owner relationship, just attendance;
  - `person -affiliated_with-> company` for attendees at a qualifying domain;
  - `event -about-> company` only when the meeting's free-text `external_org`
    resolves to a CRM company **and** someone from that company actually
    attended (a member at that domain). Both signals must agree, onto the one
    domain-keyed node — otherwise no `about` edge (and no orphan company).

A company domain *qualifies* the same way email does, except notes have no
"outbound correspondence" signal: a domain qualifies only if it is known to the
CRM (`crm_domains`). `external_org` free text ("Poseidon", "Poseidon Inc.",
"poseidon-vc") is normalized and resolved against the CRM company names so the
spellings collapse onto the single `company::{tenant}::{domain}` node.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pipeline.adapters.email_entities import (
    Edge,
    Entity,
    Extraction,
    classify_address,
)

if TYPE_CHECKING:
    from pipeline.adapters.notes import MeetingNote

# Legal/entity suffixes and VC-shop qualifiers stripped when normalizing a
# free-text org name, so "Poseidon", "Poseidon Inc." and "poseidon-vc" all map
# to the same key for CRM lookup. Conservative: only well-known trailing tokens.
_COMPANY_STOPWORDS = {
    "inc", "incorporated", "llc", "ltd", "limited", "gmbh", "ag", "sa", "sas",
    "bv", "nv", "co", "corp", "corporation", "plc", "oy", "ab", "srl", "spa",
    "vc", "ventures", "capital", "partners", "group", "holding", "holdings",
}


def normalize_company_name(name: str | None) -> str:
    """Punctuation-stripped, suffix-stripped, lowercased token key for matching a
    free-text org name against CRM company names. Empty string when blank."""
    tokens = re.findall(r"[a-z0-9]+", (name or "").lower())
    core = [t for t in tokens if t not in _COMPANY_STOPWORDS]
    return "".join(core or tokens)


def build_company_index(crm_names: dict[str, str]) -> dict[str, str]:
    """{normalized CRM company name: domain} for resolving `external_org`.

    `crm_names` is {domain: label} (from the graph's existing company nodes).
    Collisions keep the first domain seen; deterministic for the org sizes here.
    """
    index: dict[str, str] = {}
    for domain, label in crm_names.items():
        key = normalize_company_name(label)
        if key:
            index.setdefault(key, domain)
    return index


def resolve_company_domain(external_org: str | None, name_to_domain: dict[str, str]) -> str | None:
    """Resolve a free-text org name to a CRM company domain, or None."""
    key = normalize_company_name(external_org)
    return name_to_domain.get(key) if key else None


def extract_graph(
    notes: list[MeetingNote],
    *,
    crm_domains: set[str],
    crm_names: dict[str, str],
    name_to_domain: dict[str, str],
    own_domains: set[str],
    free_mail_domains: set[str] | None = None,
    role_localparts: set[str] | None = None,
) -> Extraction:
    """Deterministic core of notes ingestion (see module docstring)."""
    entities: dict[str, Entity] = {}
    edges: list[Edge] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_entity(e: Entity) -> None:
        existing = entities.get(e.canonical_key)
        if existing is None:
            entities[e.canonical_key] = e

    def add_edge(source: str, rel: str, target: str, why: str | None = None) -> None:
        if not source or not target:
            return
        k = (source, rel, target)
        if k not in seen_edges:
            seen_edges.add(k)
            edges.append(Edge(source, target, rel, why))

    def classify_participant(tenant: str, addr: str, name: str | None) -> tuple[str | None, str | None]:
        """Register the entities an address implies (+ its `affiliated_with`
        edge) and return (person_ck, company_ck). Notes have no correspondence
        signal, so companies qualify via the CRM only."""
        c = classify_address(
            addr, name, crm_domains=crm_domains, correspondent_domains=set(),
            own_domains=own_domains, crm_names=crm_names,
            free_mail_domains=free_mail_domains, role_localparts=role_localparts,
        )
        person_ck = company_ck = None
        if c.person:
            person_ck = f"person::{tenant}::{c.person.email}"
            add_entity(Entity(person_ck, "person", c.person.name or c.person.email))
        if c.company:
            company_ck = f"company::{tenant}::{c.company.domain}"
            add_entity(Entity(company_ck, "company", c.company.label))
        if person_ck and company_ck:
            add_edge(person_ck, "affiliated_with", company_ck,
                     why=f"{c.person.email} is at {c.company.domain}")
        return person_ck, company_ck

    for note in notes:
        tenant = note.tenant_id
        event_ck = f"event:{tenant}:meetingnote:{note.page_id}"
        add_entity(Entity(
            event_ck, "event", note.title,
            occurred_at=note.occurred_at or note.last_edited,
            metadata={"event_type": "meeting", "page_id": note.page_id},
        ))

        # Owner: resolved to an email upstream (firm directory). No email →
        # dropped entirely (no name-slug node). Owner is a colleague → person.
        if note.owner_email:
            o_person, _ = classify_participant(tenant, note.owner_email, note.owner_name)
            if o_person:
                add_edge(o_person, "attended", event_ck, why="meeting owner")

        # Attendees: each address classified; humans attend, role mailboxes
        # contribute only their company. Track which company domains are present
        # so the `about` edge can require a member of that org in the room.
        company_domains_present: set[str] = set()
        for addr in note.attendees:
            person_ck, company_ck = classify_participant(tenant, addr, None)
            if person_ck:
                add_edge(person_ck, "attended", event_ck, why="meeting attendee")
            if company_ck:
                company_domains_present.add(addr.partition("@")[2].lower())

        # `about`: the meeting's named org, only when it resolves to a CRM
        # company AND a member of that company attended (same domain present).
        about_domain = resolve_company_domain(note.external_org, name_to_domain)
        if about_domain and about_domain in company_domains_present:
            company_ck = f"company::{tenant}::{about_domain}"
            label = crm_names.get(about_domain, about_domain)
            add_edge(event_ck, "about", company_ck, why=f"meeting about {label}")

    return Extraction(list(entities.values()), edges)
