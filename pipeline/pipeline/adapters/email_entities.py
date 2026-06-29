"""Classify an email address into the graph entities it implies.

Step 1 of the email-ingestion rebuild. Deterministic, no I/O, no LLM. Given an
address (and the domain context for the run) it decides whether the address is a
person, a company, both, or nothing:

  - human address          → person (+ company iff its domain qualifies)
  - role mailbox (info@…)   → the company itself, no person (iff domain qualifies)
  - free-mail domain        → person only, never a company
  - own firm domain         → colleague: person only, no company
  - noise (no-reply@…)      → skipped entirely

A domain *qualifies* as a company when it is known to the CRM, or we have
corresponded outbound to it (the caller supplies both sets). Company nodes are
keyed by domain elsewhere (`company::{tenant}::{domain}`) so a CRM-known domain
merges with its existing CRM company.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pipeline.adapters.gmail import _is_noise
from pipeline.config import settings

if TYPE_CHECKING:
    from pipeline.adapters.gmail import EmailMessage


@dataclass(frozen=True)
class PersonRef:
    email: str
    name: str | None


@dataclass(frozen=True)
class CompanyRef:
    domain: str
    label: str


@dataclass(frozen=True)
class Classified:
    person: PersonRef | None
    company: CompanyRef | None


def _csv(raw: str | None) -> set[str]:
    return {x.strip().lower() for x in (raw or "").split(",") if x.strip()}


def _free_mail() -> set[str]:
    return _csv(settings.gmail_free_mail_domains)


def _roles() -> set[str]:
    return _csv(settings.gmail_role_localparts)


def derive_company_label(domain: str) -> str:
    """A human-ish company name from a domain when the CRM has none.

    Uses the registrable label (second-to-last DNS label): 'newvendor.io' →
    'Newvendor', 'mail.notion.so' → 'Notion'. Good enough for display; the
    canonical key (the full domain) is what actually identifies the company.
    """
    parts = [p for p in domain.split(".") if p]
    if not parts:
        return domain
    core = parts[-2] if len(parts) >= 2 else parts[0]
    return core.title()


def classify_address(
    addr: str,
    name: str | None = None,
    *,
    crm_domains: set[str],
    correspondent_domains: set[str],
    own_domains: set[str],
    crm_names: dict[str, str] | None = None,
    free_mail_domains: set[str] | None = None,
    role_localparts: set[str] | None = None,
) -> Classified:
    crm_names = crm_names or {}
    free = free_mail_domains if free_mail_domains is not None else _free_mail()
    roles = role_localparts if role_localparts is not None else _roles()

    a = (addr or "").strip().lower()
    local, _, domain = a.partition("@")
    if not local or not domain:
        return Classified(None, None)
    if _is_noise(a):
        return Classified(None, None)

    nm = (name or "").strip() or None
    crm = {d.lower() for d in crm_domains}
    corr = {d.lower() for d in correspondent_domains}
    own = {d.lower() for d in own_domains}
    free = {d.lower() for d in free}

    qualifies = domain not in own and domain not in free and (domain in crm or domain in corr)
    company = (
        CompanyRef(domain, crm_names.get(domain) or derive_company_label(domain))
        if qualifies
        else None
    )

    if local in {r.lower() for r in roles}:
        # The mailbox represents the company, not a person. With no qualifying
        # company there is nothing to create (don't mint a fake person).
        return Classified(None, company)

    return Classified(PersonRef(a, nm), company)


# ── Batch extraction: messages → graph ops ──────────────────────────


@dataclass
class Entity:
    canonical_key: str
    type: str                          # person | company | event
    label: str
    occurred_at: str | None = None
    metadata: dict = field(default_factory=dict)
    # insert-pointer attribute rows: {"key","value","data_type","source"}.
    # Used by notes to store a person's email as an attribute, not the label.
    attributes: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Edge:
    source: str                        # canonical_key
    target: str                        # canonical_key
    rel: str
    why: str | None = None


@dataclass
class Extraction:
    entities: list[Entity]
    edges: list[Edge]
    # Inputs deterministically dropped during extraction, for the rejection log.
    # Populated by the Notes path (unnamed attendee / unresolved owner); Gmail
    # records its drops in the adapter (`EmailRejection`), not here.
    rejections: list[NoteRejection] = field(default_factory=list)


@dataclass(frozen=True)
class NoteRejection:
    """A meeting participant dropped during notes extraction (no name → no person).
    `ref` is the meeting's page_id; `dedup_key` ('{page_id}:{email}') keys the
    upsert into the rejection log."""

    tenant_id: str
    page_id: str
    title: str
    attendee: str                          # the dropped address (lowercased)
    reason: str                            # unnamed_attendee | unresolved_owner
    occurred_at: str | None = None


def _domain(email: str) -> str:
    return email.partition("@")[2]


def message_key(tenant: str, message_id: str) -> str:
    """Canonical key for an email message node. Keyed by Message-ID so the same
    email seen from two mailboxes (or re-fetched) dedups to one node."""
    msgkey = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:32]
    return f"message:{tenant}:gmail:{msgkey}"


def _looks_like_email(label: str) -> bool:
    """A placeholder label that is just the address (no display name)."""
    return "@" in label and not any(c.isspace() for c in label)


def correspondent_domains(messages: list[EmailMessage], *, own_domains: set[str]) -> set[str]:
    """Domains we sent outbound to — recipients of any message whose sender is at
    one of our own domains. These qualify as companies even when not in the CRM."""
    own = {d.lower() for d in own_domains}
    corr: set[str] = set()
    for m in messages:
        if _domain(m.sender[0].lower()) in own:  # outbound
            for addr, _ in (*m.to, *m.cc):
                d = _domain(addr.lower())
                if d and d not in own:
                    corr.add(d)
    return corr


def _short(addr: str, name: str | None) -> str:
    return name or (addr.split("@")[0] if addr else "?")


def _event_label(m: EmailMessage) -> str:
    """Subject-free label, e.g. 'Email: Ana -> Me' (subject is private)."""
    recips = m.to or m.cc
    sender_s = _short(*m.sender) if m.sender[0] else "?"
    recip_s = _short(*recips[0]) if recips else "?"
    return f"Email: {sender_s} -> {recip_s}"[:200]


def extract_graph(
    messages: list[EmailMessage],
    *,
    crm_domains: set[str],
    crm_names: dict[str, str],
    own_domains: set[str],
    free_mail_domains: set[str] | None = None,
    role_localparts: set[str] | None = None,
) -> Extraction:
    """Deterministic core of step-1 ingestion: one `message` per email, person/
    company entities (deduped), and edges: person -sent-> message, message
    -received-> person, person -affiliated_with-> company. (`about` is deferred —
    companies are reachable via a participant's affiliated_with.)"""
    corr = correspondent_domains(messages, own_domains=own_domains)
    own = {d.lower() for d in own_domains}

    entities: dict[str, Entity] = {}
    edges: list[Edge] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_entity(e: Entity) -> None:
        existing = entities.get(e.canonical_key)
        if existing is None:
            entities[e.canonical_key] = e
        elif e.type == "person" and _looks_like_email(existing.label) and not _looks_like_email(e.label):
            # A later message names a person first seen as a bare address — upgrade.
            existing.label = e.label

    def add_edge(source: str, rel: str, target: str, why: str | None = None) -> None:
        if not source or not target:
            return
        k = (source, rel, target)
        if k not in seen_edges:
            seen_edges.add(k)
            edges.append(Edge(source, target, rel, why))

    def classify_participant(tenant: str, addr: str, name: str | None) -> tuple[str | None, str | None]:
        """Classify an address, register its entities (+ the person's
        `affiliated_with` company edge), and return (person_ck, company_ck)."""
        c = classify_address(
            addr, name, crm_domains=crm_domains, correspondent_domains=corr,
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

    for m in messages:
        tenant = m.tenant_id
        direction = "out" if _domain(m.sender[0].lower()) in own else "in"
        msg_ck = message_key(tenant, m.message_id)
        add_entity(Entity(
            msg_ck, "communication", _event_label(m), occurred_at=m.occurred_at,
            metadata={"event_type": "email", "thread_id": m.thread_id,
                      "direction": direction, "mailbox": m.mailbox},
        ))

        # sender → `sent` (person, or company for a role mailbox)
        s_person, s_company = classify_participant(tenant, *m.sender)
        if s_person:
            add_edge(s_person, "sent", msg_ck, why="sent this email")
        elif s_company:
            add_edge(s_company, "sent", msg_ck, why="sent this email")

        # recipients (to + cc) → `received` (persons only)
        for addr, name in (*m.to, *m.cc):
            r_person, _r_company = classify_participant(tenant, addr, name)
            if r_person:
                add_edge(msg_ck, "received", r_person, why="recipient")

    return Extraction(list(entities.values()), edges)
