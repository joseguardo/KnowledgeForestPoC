from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from pipeline.adapters.document import _validate_content
from pipeline.config import settings
from pipeline.errors import AdapterError, ValidationError

# Reads Kibo's in-house CRM ("Affinidad") from the platform's Supabase Postgres
# over a direct connection using a dedicated least-privilege role. Affinidad is
# single-tenant (its tables carry no tenant_id), so a "firm" here is just the
# source DSN + the tenant id we attach on the memory-layer side. Each CRM object
# type is normalized into a small record the API layer maps onto the graph:
#   entities  -> company / person pointers (+ attributes)
#   edges     -> graph edges (works_at, …)
#   deals     -> per-list namespaced attributes on the company pointer
#   notes     -> documents (org-wide, or private to the author)
#   events    -> event pointers (org-wide fact) + participant edges; the body is
#                a separate participant-only document
# Orchestration (class/grant provisioning, pointer-id resolution, edge-function
# calls) lives in the API layer, mirroring the Gmail/Notes connectors.

# Connection seam: tests inject a fake connect() returning a stub connection.
ConnectFn = Callable[[str], Awaitable[Any]]

# Affinidad holds BOTH firms' pipelines in one CRM: companies are Kibo's
# dealflow, opportunities (dealflow + LP funnel) are Nzyme's. So an entity's
# tenant routes by kind — company/person default to the firm (Kibo), opportunity
# to Nzyme. (Mirrors mcp_server.tenant_map.NZYME_TENANT; kept local to avoid
# importing the MCP package here. Revisit if a company ever joins an Nzyme list.)
NZYME_TENANT = "baa52eca-4c88-4861-9d45-720e743febb4"


def _entity_tenant(firm: "AffinidadFirm", kind: str | None) -> str:
    return NZYME_TENANT if kind == "opportunity" else firm.tenant_id


# ── Per-firm connector config ───────────────────────────────────────


@dataclass
class AffinidadFirm:
    """One firm = one tenant whose CRM lives in a source Supabase project, reached
    via a least-privilege read-only role connection string (source_dsn)."""

    tenant_id: str
    source_dsn: str


def load_affinidad_firms(tenant_id: str | None = None) -> list[AffinidadFirm]:
    """Parse settings.affinidad_firms (JSON array). Optionally filter to one
    tenant. Falls back to a single firm from affinidad_source_dsn +
    affinidad_default_tenant_id (the normal single-tenant case)."""
    raw = (settings.affinidad_firms or "").strip()
    entries: list[dict[str, Any]]
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"AFFINIDAD_FIRMS is not valid JSON: {exc}")
        if not isinstance(parsed, list):
            raise ValidationError("AFFINIDAD_FIRMS must be a JSON array")
        entries = parsed
    elif settings.affinidad_source_dsn:
        entries = [
            {
                "tenant_id": settings.affinidad_default_tenant_id,
                "source_dsn": settings.affinidad_source_dsn,
            }
        ]
    else:
        raise ValidationError(
            "Affinidad connector not configured: set AFFINIDAD_FIRMS (JSON array of "
            "{tenant_id, source_dsn}) or AFFINIDAD_SOURCE_DSN + AFFINIDAD_DEFAULT_TENANT_ID"
        )

    firms: list[AffinidadFirm] = []
    for entry in entries:
        tid = str(entry.get("tenant_id") or "").strip()
        if tenant_id and tid != tenant_id:
            continue
        if not tid:
            raise ValidationError("AFFINIDAD_FIRMS entry missing tenant_id")
        dsn = str(entry.get("source_dsn") or "").strip()
        if not dsn:
            raise ValidationError(f"AFFINIDAD_FIRMS entry for {tid} has no source_dsn")
        firms.append(AffinidadFirm(tenant_id=tid, source_dsn=dsn))
    if tenant_id and not firms:
        raise ValidationError(f"AFFINIDAD_FIRMS has no firm for tenant_id {tenant_id!r}")
    return firms


# ── Normalized records ──────────────────────────────────────────────

# attributes are (key, value, data_type) tuples destined for attributes_kv.
Attr = tuple[str, Any, str]


@dataclass
class CrmEntity:
    tenant_id: str
    entity_id: str          # source entities.id (used to resolve edges/participants)
    kind: str               # 'company' | 'person'
    label: str
    canonical_key: str
    attributes: list[Attr]
    metadata: dict[str, Any]
    occurred_at: str | None  # always None — entities are nouns, not events
    email: str | None = None  # persons only: primary email, for granting private bodies


@dataclass
class CrmEdge:
    source_id: str          # source entities.id
    target_id: str          # source entities.id
    relation: str
    metadata: dict[str, Any]


@dataclass
class CrmDeal:
    entity_id: str          # source entities.id (company OR opportunity) in the list
    attributes: list[Attr]  # per-list namespaced (e.g. "Dealflow:Stage")


@dataclass
class CrmNote:
    tenant_id: str
    note_id: str
    label: str
    body: str
    author_email: str | None
    private: bool           # crm_notes.visibility == 'private'
    occurred_at: str | None
    links: list[tuple[str, str]]  # (entity_type, entity_id) — entity_type ∈ company|person|meeting|event


@dataclass
class CrmEvent:
    tenant_id: str
    event_id: str           # source events.id
    type: str               # email|meeting|call|message|other
    label: str              # org-visible node label (email subject is NOT used)
    subject: str | None     # carried for the private body only
    body: str               # flattened from events.body jsonb blocks
    occurred_at: str | None
    metadata: dict[str, Any]
    participants: list[tuple[str, str, str, str | None]]  # (entity_type, entity_id, role, response_status)


# ── Canonical-key helpers (shared scheme with Gmail/Notes connectors) ─


def company_key(tenant: str, domain: str | None, entity_id: str) -> str:
    d = (domain or "").strip().lower()
    return f"company::{tenant}::{d}" if d else f"company::{tenant}::id:{entity_id}"


def person_key(tenant: str, email: str | None, entity_id: str) -> str:
    e = (email or "").strip().lower()
    # Email-keyed persons are GLOBAL (cross-tenant shared identity); the no-email
    # id-fallback stays tenant-scoped (can't be matched across firms).
    return f"person::{e}" if e else f"person::{tenant}::id:{entity_id}"


def opportunity_key(tenant: str, entity_id: str) -> str:
    """Opportunities (dealflow/LP) have no domain/email — keyed by source id,
    tenant-scoped (they belong to one firm's pipeline)."""
    return f"opportunity::{tenant}::id:{entity_id}"


def communication_key(tenant: str, event_id: str) -> str:
    return f"communication::{tenant}::affinidad::{event_id}"


# Back-compat alias (older callers/tests referenced event_key).
event_key = communication_key


# ── Normalizers (pure) ──────────────────────────────────────────────


def emails_by_entity(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """{entity_id: [lowercased emails]} from entity_emails, primary first."""
    idx: dict[str, list[str]] = {}
    for r in rows:
        eid = str(r.get("entity_id") or "")
        em = (r.get("email") or "").strip().lower()
        if not eid or not em:
            continue
        bucket = idx.setdefault(eid, [])
        if r.get("is_primary"):
            bucket.insert(0, em)
        else:
            bucket.append(em)
    return idx


def _str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _as_obj(v: Any) -> Any:
    """asyncpg hands back jsonb/json as a JSON *string* unless a codec is set;
    normalize to the underlying dict/list (None on anything unparseable)."""
    if v is None or isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return None
    return v


def _to_entity(tenant: str, row: dict[str, Any], emails: dict[str, list[str]]) -> CrmEntity:
    kind = row.get("kind")
    eid = str(row["id"])
    meta: dict[str, Any] = {"source": "affinidad", "external_id": eid, "kind": kind}
    aff = _str(row.get("affinity_id"))
    if aff:
        meta["affinity_id"] = aff

    attrs: list[Attr] = []
    email: str | None = None
    owner = _str(row.get("owner_email"))
    if kind == "company":
        label = _str(row.get("name")) or "Unknown company"
        ck = company_key(tenant, row.get("domain"), eid)
        for key, col in (("Sector", "sector"), ("Status", "status"),
                         ("Location", "location"), ("Domain", "domain"),
                         ("Website", "website"), ("Description", "description")):
            v = _str(row.get(col))
            if v:
                attrs.append((key, v, "string"))
        if owner:
            attrs.append(("Owner", owner, "string"))
    elif kind == "opportunity":
        # Dealflow / LP opportunities — a distinct CRM noun, keyed by source id.
        label = _str(row.get("name")) or _str(row.get("full_name")) or "Unknown opportunity"
        ck = opportunity_key(tenant, eid)
        for key, col in (("Status", "status"), ("Sector", "sector"),
                         ("Location", "location"), ("Description", "description"),
                         ("Domain", "domain"), ("Website", "website")):
            v = _str(row.get(col))
            if v:
                attrs.append((key, v, "string"))
        if owner:
            attrs.append(("Owner", owner, "string"))
    else:  # person
        label = _str(row.get("full_name")) or _str(row.get("name")) or _str(row.get("email")) or "Unknown person"
        email = (row.get("email") or "").strip().lower() or None
        ck = person_key(tenant, row.get("email"), eid)
        for key, col in (("Title", "title"), ("Phone", "phone"), ("LinkedIn", "linkedin_url")):
            v = _str(row.get(col))
            if v:
                attrs.append((key, v, "string"))
        addrs = emails.get(eid)
        if addrs:
            meta["emails"] = addrs

    return CrmEntity(
        tenant_id=tenant, entity_id=eid, kind=kind, label=label,
        canonical_key=ck, attributes=attrs, metadata=meta, occurred_at=None, email=email,
    )


def _to_edge(row: dict[str, Any]) -> CrmEdge:
    md = _as_obj(row.get("metadata"))
    return CrmEdge(
        source_id=str(row["source_id"]),
        target_id=str(row["target_id"]),
        relation=str(row.get("relation") or "related"),
        metadata=md if isinstance(md, dict) else {},
    )


def _flatten_blocks(body: Any) -> str:
    """events.body is an ordered jsonb list of typed blocks; keep paragraph text."""
    if not body:
        return ""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return body.strip()
    parts: list[str] = []
    for block in body or []:
        if isinstance(block, dict) and block.get("type") == "paragraph":
            text = (block.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def _to_event(tenant: str, row: dict[str, Any], participants: list[tuple[str, str, str, str | None]]) -> CrmEvent:
    eid = str(row["id"])
    typ = str(row.get("type") or "other")
    occurred_at = _iso(row.get("occurred_at"))
    subject = _str(row.get("subject"))
    body = _flatten_blocks(row.get("body"))

    # Email subjects are participant-only, so they must not appear on the
    # org-wide event node; meeting/call titles are org-visible.
    if typ == "email":
        date_hint = (occurred_at or "")[:10]
        label = f"Email · {date_hint}" if date_hint else "Email"
    else:
        label = subject or typ.capitalize()

    meta: dict[str, Any] = {
        "source": "affinidad",
        "external_id": _str(row.get("external_id")),
        "event_type": typ,
        "direction": _str(row.get("direction")),
        "status": _str(row.get("status")),
        "thread_id": _str(row.get("thread_id")),
        "origin": _str(row.get("source")),
    }
    src_meta = _as_obj(row.get("metadata")) or {}
    if isinstance(src_meta, dict) and src_meta.get("participants_raw"):
        meta["participants_raw"] = src_meta["participants_raw"]
    meta = {k: v for k, v in meta.items() if v is not None}

    return CrmEvent(
        tenant_id=tenant, event_id=eid, type=typ, label=label, subject=subject,
        body=body, occurred_at=occurred_at, metadata=meta, participants=participants,
    )


def _to_note(tenant: str, row: dict[str, Any], links: list[tuple[str, str]]) -> CrmNote:
    nid = str(row["id"])
    body = str(row.get("body") or "").strip()
    occurred_at = _iso(row.get("created_at"))
    date_hint = (occurred_at or "")[:10]
    label = f"Content · {date_hint}" if date_hint else "Content"
    return CrmNote(
        tenant_id=tenant, note_id=nid, label=label, body=body,
        author_email=_str(row.get("author_email")),
        private=(str(row.get("visibility") or "org").strip().lower() == "private"),
        occurred_at=occurred_at, links=links,
    )


_FIELD_DATA_TYPE = {
    "number": "number",
    "currency": "number",
    "date": "string",
    "select": "string",
    "text": "string",
}


def _to_deal(
    *,
    entity_id: str,
    list_name: str,
    stage_name: str | None,
    owner_emails: list[str] | None,
    field_values: dict[str, Any] | None,
    field_defs: list[dict[str, Any]],
) -> CrmDeal:
    """A company's membership in one list → namespaced attributes on the company
    pointer: '<List>:Stage', '<List>:Owners', and one per configured field."""
    attrs: list[Attr] = []
    if stage_name:
        attrs.append((f"{list_name}:Stage", stage_name, "string"))
    if owner_emails:
        # "json" is the valid attribute_data_type enum value for an array; "array"
        # is rejected and would poison the whole per-pointer attribute upsert.
        attrs.append((f"{list_name}:Owners", list(owner_emails), "json"))
    values = field_values or {}
    for fd in field_defs:
        key = fd.get("key")
        label = fd.get("label") or key
        if not key or key not in values:
            continue
        val = values.get(key)
        if val is None or val == "":
            continue
        dt = _FIELD_DATA_TYPE.get(str(fd.get("type") or "text"), "string")
        attrs.append((f"{list_name}:{label}", val, dt))
    return CrmDeal(entity_id=str(entity_id), attributes=attrs)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ── Adapter ─────────────────────────────────────────────────────────


async def _default_connect(dsn: str) -> Any:
    import asyncpg  # lazy: keeps import cost off the hot path / optional installs

    conn = await asyncpg.connect(dsn)
    # asyncpg returns jsonb/json as text by default; decode to dict/list so the
    # normalizers see structured data (events.body/metadata, entity_edges.metadata,
    # crm_list_entries.fields). _as_obj() is the per-value fallback if this is absent.
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )
    return conn


async def _close(conn: Any) -> None:
    close = getattr(conn, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result


class AffinidadAdapter:
    """Fetches each CRM object type for one firm from its source Postgres and
    normalizes it. Owns the connection lifecycle so the API layer never touches
    the source DB directly."""

    async def fetch_entities(
        self, firm: AffinidadFirm, connect: ConnectFn = _default_connect
    ) -> list[CrmEntity]:
        conn = await self._connect(firm, connect)
        try:
            email_rows = [dict(r) for r in await conn.fetch(
                "SELECT entity_id, email, is_primary FROM entity_emails"
            )]
            rows = [dict(r) for r in await conn.fetch(
                "SELECT id, kind, name, full_name, domain, email, website, description, "
                "sector, status, location, phone, title, linkedin_url, owner_email, affinity_id "
                "FROM entities"
            )]
        except Exception as exc:
            raise AdapterError(f"Affinidad entities query failed: {exc}")
        finally:
            await _close(conn)
        emails = emails_by_entity(email_rows)
        return [_to_entity(_entity_tenant(firm, r.get("kind")), r, emails) for r in rows]

    async def fetch_edges(
        self, firm: AffinidadFirm, connect: ConnectFn = _default_connect
    ) -> list[CrmEdge]:
        conn = await self._connect(firm, connect)
        try:
            rows = [dict(r) for r in await conn.fetch(
                "SELECT source_id, target_id, relation, metadata FROM entity_edges"
            )]
        except Exception as exc:
            raise AdapterError(f"Affinidad edges query failed: {exc}")
        finally:
            await _close(conn)
        return [_to_edge(r) for r in rows]

    async def fetch_deals(
        self, firm: AffinidadFirm, connect: ConnectFn = _default_connect
    ) -> list[CrmDeal]:
        conn = await self._connect(firm, connect)
        try:
            field_rows = [dict(r) for r in await conn.fetch(
                "SELECT list_id, key, label, type, position FROM crm_list_fields ORDER BY position"
            )]
            entry_rows = [dict(r) for r in await conn.fetch(
                "SELECT e.company_id, l.name AS list_name, s.name AS stage_name, "
                "e.owner_emails, e.fields, e.list_id "
                "FROM crm_list_entries e "
                "JOIN crm_lists l ON l.id = e.list_id "
                "LEFT JOIN crm_list_stages s ON s.id = e.stage_id"
            )]
        except Exception as exc:
            raise AdapterError(f"Affinidad deals query failed: {exc}")
        finally:
            await _close(conn)

        defs_by_list: dict[str, list[dict[str, Any]]] = {}
        for fr in field_rows:
            defs_by_list.setdefault(str(fr["list_id"]), []).append(fr)

        deals: list[CrmDeal] = []
        for er in entry_rows:
            fields = er.get("fields")
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except (json.JSONDecodeError, ValueError):
                    fields = {}
            deals.append(_to_deal(
                entity_id=er["company_id"],  # source column name; holds company OR opportunity id
                list_name=str(er.get("list_name") or "List"),
                stage_name=_str(er.get("stage_name")),
                owner_emails=list(er.get("owner_emails") or []),
                field_values=fields or {},
                field_defs=defs_by_list.get(str(er.get("list_id")), []),
            ))
        return deals

    async def fetch_notes(
        self, firm: AffinidadFirm, connect: ConnectFn = _default_connect
    ) -> list[CrmNote]:
        conn = await self._connect(firm, connect)
        try:
            link_rows = [dict(r) for r in await conn.fetch(
                "SELECT note_id, entity_type, entity_id FROM crm_note_links"
            )]
            rows = [dict(r) for r in await conn.fetch(
                "SELECT id, body, author_email, visibility, created_at FROM crm_notes"
            )]
        except Exception as exc:
            raise AdapterError(f"Affinidad notes query failed: {exc}")
        finally:
            await _close(conn)

        links_by_note: dict[str, list[tuple[str, str]]] = {}
        for lr in link_rows:
            links_by_note.setdefault(str(lr["note_id"]), []).append(
                (str(lr["entity_type"]), str(lr["entity_id"]))
            )
        notes: list[CrmNote] = []
        for r in rows:
            note = _to_note(firm.tenant_id, r, links_by_note.get(str(r["id"]), []))
            if note.body:
                _validate_content(note.body)
            notes.append(note)
        return notes

    async def fetch_events(
        self,
        firm: AffinidadFirm,
        connect: ConnectFn = _default_connect,
        since: str | None = None,
        max_results: int | None = None,
    ) -> list[CrmEvent]:
        cap = max_results or settings.affinidad_max_results
        conn = await self._connect(firm, connect)
        try:
            part_rows = [dict(r) for r in await conn.fetch(
                "SELECT event_id, entity_type, entity_id, role, response_status FROM event_participants"
            )]
            # Scope: meetings only this round (the ~29.6k content-less emails are a
            # separate pass). type='meeting' filters them at the source.
            if since:
                try:
                    since_dt = datetime.fromisoformat(since)
                except ValueError as exc:
                    raise AdapterError(f"Invalid affinidad events cursor {since!r}: {exc}")
                rows = [dict(r) for r in await conn.fetch(
                    "SELECT id, type, occurred_at, direction, status, subject, body, "
                    "thread_id, source, external_id, metadata FROM events "
                    "WHERE type='meeting' AND updated_at > $1 ORDER BY occurred_at ASC NULLS LAST LIMIT $2",
                    since_dt, cap,
                )]
            else:
                rows = [dict(r) for r in await conn.fetch(
                    "SELECT id, type, occurred_at, direction, status, subject, body, "
                    "thread_id, source, external_id, metadata FROM events "
                    "WHERE type='meeting' ORDER BY occurred_at ASC NULLS LAST LIMIT $1",
                    cap,
                )]
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"Affinidad events query failed: {exc}")
        finally:
            await _close(conn)

        parts_by_event: dict[str, list[tuple[str, str, str, str | None]]] = {}
        for pr in part_rows:
            parts_by_event.setdefault(str(pr["event_id"]), []).append(
                (str(pr["entity_type"]), str(pr["entity_id"]),
                 str(pr.get("role") or "attendee"), _str(pr.get("response_status")))
            )
        return [_to_event(firm.tenant_id, r, parts_by_event.get(str(r["id"]), [])) for r in rows]

    async def _connect(self, firm: AffinidadFirm, connect: ConnectFn) -> Any:
        try:
            return await connect(firm.source_dsn)
        except Exception as exc:
            raise AdapterError(f"Affinidad source connection failed: {exc}")
