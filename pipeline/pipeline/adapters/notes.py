from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from pipeline.adapters.document import _validate_content
from pipeline.config import settings
from pipeline.errors import AdapterError, ValidationError

# Reads meeting notes from a *source* Supabase project (the Notion "Meeting Notes"
# mirror, table `meeting_transcripts`) over a direct Postgres connection using a
# dedicated least-privilege role. Each meeting is normalized into a MeetingNote
# for the same public-graph + (optionally) private-body split as the Gmail
# connector: a firm-wide who-met-whom graph (owner + attendees + company + event)
# and a body (notion_summary) that is firm-wide unless the row is Confidential.
# Orchestration of class/grant provisioning + ingestion lives in the API layer.

# Safe SQL identifiers only — table/column names come from config, never values.
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Trailing ISO-8601 datetime that Notion appends to many meeting titles, e.g.
# "Ext. Call Poseidon 2026-06-19T11:00:00.000+02:00".
_RE_TRAILING_ISO = re.compile(
    r"\s+\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s*$"
)

_DEFAULT_TABLE = "meeting_transcripts"
_DEFAULT_CONTENT_FIELDS = ["notion_summary"]
_DEFAULT_CONFIDENTIAL_FIELD = "confidential"
_DEFAULT_OWNER_MAP_TABLES = [
    {"table": "ReportingNz_team_members", "name_col": "name", "email_col": "email"},
    {"table": "nzyme_team", "name_col": "full_name", "email_col": "email"},
]

# Connection seam: tests inject a fake connect() returning a stub connection.
ConnectFn = Callable[[str], Awaitable[Any]]


# ── Per-firm connector config ───────────────────────────────────────


@dataclass
class NotesFirm:
    """One firm = one tenant whose meeting notes live in a source Supabase project,
    reached via a least-privilege read-only role connection string (source_dsn)."""

    tenant_id: str
    source_dsn: str
    table: str = _DEFAULT_TABLE
    content_fields: list[str] = field(default_factory=lambda: list(_DEFAULT_CONTENT_FIELDS))
    confidential_field: str = _DEFAULT_CONFIDENTIAL_FIELD
    owner_map_tables: list[dict[str, str]] = field(
        default_factory=lambda: [dict(t) for t in _DEFAULT_OWNER_MAP_TABLES]
    )


@dataclass
class MeetingNote:
    """One meeting, normalized for the firm-wide graph + (maybe private) body."""

    tenant_id: str
    page_id: str
    title: str
    occurred_at: str | None
    last_edited: str | None  # ISO; drives the incremental cursor
    owner_name: str | None
    owner_email: str | None
    attendees: list[str]  # attendee emails (lowercased, deduped)
    external_org: str | None  # raw free-text org the meeting is "about"; resolved downstream
    confidential: bool
    body: str  # joined content_fields; "" when none present
    scheduled_at: str | None = None  # meeting's scheduled slot, parsed from the raw title


@dataclass
class NotesFetch:
    """Result of a firm's fetch: the meetings plus the firm's own email domains
    (derived from its team directory) so attendees at those domains classify as
    colleagues — person-only, never a company."""

    notes: list[MeetingNote]
    own_domains: set[str]
    team_names: dict[str, str]  # email → name (firm team directory), for person labels


def load_notes_firms(tenant_id: str | None = None) -> list[NotesFirm]:
    """Parse settings.notes_firms (JSON array). Optionally filter to one tenant.
    Falls back to a single firm from notes_source_dsn + notes_default_tenant_id."""
    raw = (settings.notes_firms or "").strip()
    entries: list[dict[str, Any]]
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"NOTES_FIRMS is not valid JSON: {exc}")
        if not isinstance(parsed, list):
            raise ValidationError("NOTES_FIRMS must be a JSON array")
        entries = parsed
    elif settings.notes_source_dsn:
        entries = [
            {
                "tenant_id": settings.notes_default_tenant_id,
                "source_dsn": settings.notes_source_dsn,
            }
        ]
    else:
        raise ValidationError(
            "Notes connector not configured: set NOTES_FIRMS (JSON array of "
            "{tenant_id, source_dsn}) or NOTES_SOURCE_DSN + NOTES_DEFAULT_TENANT_ID"
        )

    firms: list[NotesFirm] = []
    for entry in entries:
        tid = str(entry.get("tenant_id") or "").strip()
        if tenant_id and tid != tenant_id:
            continue
        if not tid:
            raise ValidationError("NOTES_FIRMS entry missing tenant_id")
        dsn = str(entry.get("source_dsn") or "").strip()
        if not dsn:
            raise ValidationError(f"NOTES_FIRMS entry for {tid} has no source_dsn")
        table = (entry.get("table") or _DEFAULT_TABLE).strip()
        _check_ident(table, "table")
        content_fields = entry.get("content_fields") or list(_DEFAULT_CONTENT_FIELDS)
        for f in content_fields:
            _check_ident(f, "content_fields entry")
        conf_field = (entry.get("confidential_field") or _DEFAULT_CONFIDENTIAL_FIELD).strip()
        _check_ident(conf_field, "confidential_field")
        owner_tables = entry.get("owner_map_tables") or [
            dict(t) for t in _DEFAULT_OWNER_MAP_TABLES
        ]
        for t in owner_tables:
            _check_ident(t["table"], "owner_map_tables table")
            _check_ident(t["name_col"], "owner_map_tables name_col")
            _check_ident(t["email_col"], "owner_map_tables email_col")
        firms.append(
            NotesFirm(
                tenant_id=tid,
                source_dsn=dsn,
                table=table,
                content_fields=list(content_fields),
                confidential_field=conf_field,
                owner_map_tables=owner_tables,
            )
        )
    if tenant_id and not firms:
        raise ValidationError(f"NOTES_FIRMS has no firm for tenant_id {tenant_id!r}")
    return firms


def _check_ident(name: str, what: str) -> None:
    if not _IDENT.match(name or ""):
        raise ValidationError(f"Unsafe SQL identifier for {what}: {name!r}")


# ── Adapter ─────────────────────────────────────────────────────────


async def _default_connect(dsn: str) -> Any:
    import asyncpg  # lazy: keeps import cost off the hot path / optional installs

    return await asyncpg.connect(dsn)


class NotesAdapter:
    """Fetches meeting notes for one firm from its source Postgres and normalizes
    each into a MeetingNote (firm-wide graph + body). Owns the connection lifecycle
    so the API layer never touches the source DB directly."""

    async def fetch_notes(
        self,
        firm: NotesFirm,
        since: str | None = None,
        max_results: int | None = None,
        connect: ConnectFn = _default_connect,
    ) -> NotesFetch:
        cap = max_results or settings.notes_max_results
        try:
            conn = await connect(firm.source_dsn)
        except Exception as exc:  # asyncpg + DNS/auth errors
            raise AdapterError(f"Notes source connection failed: {exc}")
        try:
            owner_map, team_names = await _fetch_owner_email_map(conn, firm)
            rows = await _fetch_rows(conn, firm, since, cap)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"Notes source query failed: {exc}")
        finally:
            close = getattr(conn, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

        own_domains = {
            em.split("@", 1)[1] for em in owner_map.values() if "@" in em
        }
        notes = [_to_note(firm, dict(r), owner_map) for r in rows]
        return NotesFetch(notes=notes, own_domains=own_domains, team_names=team_names)


async def _fetch_owner_email_map(conn: Any, firm: NotesFirm) -> tuple[dict[str, str], dict[str, str]]:
    """Read the firm's team directory once, returning two views:
      - owner_map  {lower(name): lower(email)} — resolves a meeting's owner
        (a name) to an email, so the same person is keyed by email, not split.
      - team_names {lower(email): name} — the inverse, original-case name, so an
        internal colleague who attends gets a real-name person label."""
    owner_map: dict[str, str] = {}
    team_names: dict[str, str] = {}
    for t in firm.owner_map_tables:
        sql = (
            f'SELECT "{t["name_col"]}" AS nm, "{t["email_col"]}" AS em '
            f'FROM "{t["table"]}" WHERE "{t["email_col"]}" IS NOT NULL'
        )
        for r in await conn.fetch(sql):
            nm_raw = (r["nm"] or "").strip()
            em = (r["em"] or "").strip().lower()
            if nm_raw and em:
                owner_map.setdefault(nm_raw.lower(), em)
                team_names.setdefault(em, nm_raw)
    return owner_map, team_names


async def _fetch_rows(conn: Any, firm: NotesFirm, since: str | None, cap: int) -> list[Any]:
    cols = [
        "page_id",
        "title",
        "owner_name",
        "attendee_emails",
        "external_org",
        "meeting_start",
        "last_edited_time",
        f'"{firm.confidential_field}" AS confidential',
    ]
    cols += [f'"{f}"' for f in firm.content_fields]
    select = ", ".join(c if c.startswith('"') or " AS " in c else f'"{c}"' for c in cols)
    base = f'SELECT {select} FROM "{firm.table}"'
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise AdapterError(f"Invalid notes cursor {since!r}: {exc}")
        sql = base + " WHERE last_edited_time > $1 ORDER BY last_edited_time ASC LIMIT $2"
        return await conn.fetch(sql, since_dt, cap)
    sql = base + " ORDER BY last_edited_time ASC NULLS LAST LIMIT $1"
    return await conn.fetch(sql, cap)


def _to_note(firm: NotesFirm, row: dict[str, Any], owner_map: dict[str, str]) -> MeetingNote:
    owner_name = (row.get("owner_name") or "").strip() or None
    owner_email = owner_map.get(owner_name.lower()) if owner_name else None

    attendees: list[str] = []
    seen: set[str] = set()
    for a in row.get("attendee_emails") or []:
        e = (a or "").strip().lower()
        if e and e not in seen:
            seen.add(e)
            attendees.append(e)

    external_org = (row.get("external_org") or "").strip() or None
    confidential = (row.get("confidential") or "").strip().lower() == "confidential"

    parts = [
        str(row[f]).strip()
        for f in firm.content_fields
        if row.get(f) is not None and str(row[f]).strip()
    ]
    body = "\n\n".join(parts)
    if body:
        _validate_content(body)

    return MeetingNote(
        tenant_id=firm.tenant_id,
        page_id=str(row["page_id"]),
        title=_clean_title(row.get("title")),
        scheduled_at=_scheduled_from_title(row.get("title")),
        occurred_at=_iso(row.get("meeting_start")),
        last_edited=_iso(row.get("last_edited_time")),
        owner_name=owner_name,
        owner_email=owner_email,
        attendees=attendees,
        external_org=external_org,
        confidential=confidential,
        body=body,
    )


def slugify(value: str | None) -> str:
    """Lowercased, hyphenated slug for canonical-key fallbacks (e.g. owner name)."""
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-") or "unknown"


def _clean_title(title: str | None) -> str:
    if not title:
        return "Meeting"
    return _RE_TRAILING_ISO.sub("", str(title).strip()).strip() or "Meeting"


def _scheduled_from_title(title: str | None) -> str | None:
    """The meeting's scheduled slot = the trailing ISO datetime Notion appends to
    the title (the same value across both note-pages of one meeting). Returns a
    normalized ISO string, or None when the title carries no such timestamp."""
    if not title:
        return None
    m = _RE_TRAILING_ISO.search(str(title))
    if not m:
        return None
    raw = m.group(0).strip()
    try:
        return datetime.fromisoformat(raw).isoformat()
    except ValueError:
        return raw or None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
