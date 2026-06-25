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

import hashlib
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


# Generic / role local-part tokens that aren't personal names — a `sales.team@`
# or `info.madrid@` must not be parsed into a "person".
_GENERIC_LOCALPARTS = frozenset({
    "no", "reply", "noreply", "donotreply", "info", "sales", "support", "admin",
    "contact", "hello", "team", "marketing", "newsletter", "news", "accounts",
    "billing", "help", "office", "hr", "jobs", "careers", "press", "events",
    "booking", "bookings", "invite", "invites", "mail", "mailer", "daemon",
    "postmaster", "notifications", "notify", "alerts",
})
# A name token: ≥2 unicode letters, no digits/underscore (so initials and
# digit-bearing handles are rejected).
_NAME_TOKEN = re.compile(r"^[^\W\d_]{2,}$")


def name_from_email(addr: str | None) -> str | None:
    """Extract a human name from an email local-part *when confident*, else None.

    `pablo.campos@…` → "Pablo Campos"; `jose.carazo@…` → "Jose Carazo". Drops when
    unsure: a single mashed token (`claudiagarcia@…`), an initial (`j.carazo@…`),
    digits, or a generic/role word (`sales.team@…`). Conservative on purpose —
    the precedence is the team/CRM directory first, this heuristic second, then
    drop. The `+tag` suffix is ignored.
    """
    local = (addr or "").partition("@")[0].split("+", 1)[0].strip()
    tokens = [t for t in re.split(r"[._\-]+", local) if t]
    if len(tokens) < 2:
        return None
    if not all(_NAME_TOKEN.match(t) for t in tokens):
        return None
    if any(t.lower() in _GENERIC_LOCALPARTS for t in tokens):
        return None
    return " ".join(t.capitalize() for t in tokens)


def event_key(tenant: str, note: MeetingNote) -> str:
    """Canonical key for a meeting's event node. Keyed by the *meeting* (cleaned
    title + scheduled slot) when the slot is known, so two note-pages of one
    meeting collapse to one event while distinct occurrences (different slots)
    stay separate. Falls back to the per-page key when no slot is present."""
    if note.scheduled_at:
        h = hashlib.sha256(
            f"{(note.title or '').strip().lower()}|{note.scheduled_at}".encode("utf-8")
        ).hexdigest()[:32]
        return f"event:{tenant}:meeting:{h}"
    return f"event:{tenant}:meetingnote:{note.page_id}"


def extract_graph(
    notes: list[MeetingNote],
    *,
    crm_domains: set[str],
    crm_names: dict[str, str],
    name_to_domain: dict[str, str],
    own_domains: set[str],
    name_by_email: dict[str, str] | None = None,
    free_mail_domains: set[str] | None = None,
    role_localparts: set[str] | None = None,
) -> Extraction:
    """Deterministic core of notes ingestion (see module docstring)."""
    names = name_by_email or {}
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

    def classify_participant(
        tenant: str, addr: str, name: str | None, why: str,
    ) -> str | None:
        """Register the entities an address implies and return the company
        domain present (or None). A `person` is materialized only when we have a
        real `name` (label = name, email → attribute); without a name the person
        is dropped (no node, no `attended`, no `affiliated_with`). The company is
        still asserted from a qualifying domain regardless of naming — attendance
        is observed even when we can't name the attendee. Notes have no
        correspondence signal, so companies qualify via the CRM only."""
        c = classify_address(
            addr, name, crm_domains=crm_domains, correspondent_domains=set(),
            own_domains=own_domains, crm_names=crm_names,
            free_mail_domains=free_mail_domains, role_localparts=role_localparts,
        )
        company_ck = None
        if c.company:
            company_ck = f"company::{tenant}::{c.company.domain}"
            add_entity(Entity(company_ck, "company", c.company.label))
        if c.person and c.person.name:
            person_ck = f"person::{c.person.email}"  # global identity (cross-tenant)
            add_entity(Entity(
                person_ck, "person", c.person.name,
                attributes=[{"key": "email", "value": c.person.email,
                             "data_type": "string", "source": "notes"}],
            ))
            add_edge(person_ck, "attended", event_ck, why=why)
            if company_ck:
                add_edge(person_ck, "affiliated_with", company_ck,
                         why=f"{c.person.email} is at {c.company.domain}")
        return c.company.domain if c.company else None

    for note in notes:
        tenant = note.tenant_id
        event_ck = event_key(tenant, note)
        add_entity(Entity(
            event_ck, "event", note.title,
            occurred_at=note.scheduled_at or note.occurred_at or note.last_edited,
            metadata={"event_type": "meeting", "page_id": note.page_id},
        ))

        # Owner: resolved to an email upstream + named from the firm row. No
        # email → dropped (no name-slug node). Owner is a colleague → person.
        if note.owner_email and note.owner_name:
            classify_participant(tenant, note.owner_email, note.owner_name, "meeting owner")

        # Attendees: resolve each email to a name (firm team / CRM directory);
        # named → person + `attended`, unnamed → dropped. Track company domains
        # present so the `about` edge can require a member of that org in the room.
        company_domains_present: set[str] = set()
        for addr in note.attendees:
            resolved = (
                names.get(addr)
                or (note.owner_name if addr == note.owner_email else None)
                or name_from_email(addr)
            )
            domain = classify_participant(tenant, addr, resolved, "meeting attendee")
            if domain:
                company_domains_present.add(domain)

        # `about`: the meeting's named org, only when it resolves to a CRM
        # company AND a member of that company attended (same domain present).
        about_domain = resolve_company_domain(note.external_org, name_to_domain)
        if about_domain and about_domain in company_domains_present:
            company_ck = f"company::{tenant}::{about_domain}"
            label = crm_names.get(about_domain, about_domain)
            add_edge(event_ck, "about", company_ck, why=f"meeting about {label}")

    return Extraction(list(entities.values()), edges)
