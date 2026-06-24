from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form

from pipeline.access import (
    add_thread_members,
    ensure_class,
    ensure_tenant_grant,
    ensure_user_grant,
    resolve_pointer_id,
    resolve_user_ids,
)
from pipeline.adapters.affinidad import (
    AffinidadAdapter,
    CrmDeal,
    CrmEdge,
    CrmEntity,
    CrmEvent,
    CrmNote,
    event_key,
    load_affinidad_firms,
)
from pipeline.adapters.conversation import ConversationAdapter
from pipeline.adapters.document import DocumentAdapter
from pipeline.adapters.email_entities import extract_graph, message_key
from pipeline.adapters.gmail import (
    GmailAdapter,
    _truncate_utf16,
    _utf16_len,
    discover_mailboxes,
    load_firms,
)
from pipeline.adapters.notes import (
    MeetingNote,
    NotesAdapter,
    load_notes_firms,
)
from pipeline.adapters.notes_entities import (
    build_company_index,
    extract_graph as extract_notes_graph,
)
try:
    # NOTE(temporary shim): the notion connector source files are missing from
    # this working tree (only their stale .pyc remain) and were never committed,
    # so they can't be restored from git. Guarding the import keeps the rest of
    # the app (and the test suite) loadable; the /notion endpoints raise at call
    # time until the adapters are restored. Remove this guard once they're back.
    from pipeline.adapters.notion import NotionAdapter
    from pipeline.adapters.notion_export import NotionExportAdapter
except ModuleNotFoundError:
    NotionAdapter = None  # type: ignore[assignment,misc]
    NotionExportAdapter = None  # type: ignore[assignment,misc]
from pipeline.adapters.structured import StructuredAdapter
from pipeline.adapters.web import WebAdapter
from pipeline.client import EdgeFunctionClient
from pipeline.config import settings
from pipeline.connector_state import get_cursor, set_cursor
from pipeline.errors import (
    AdapterError,
    EdgeFunctionError,
    EdgeFunctionTimeout,
    ValidationError,
)
from pipeline.models import (
    AffinidadRequest,
    ConversationRequest,
    DocumentRequest,
    EdgeFunctionResult,
    GmailRequest,
    IngestError,
    IngestResponse,
    LinkSpec,
    NotesRequest,
    NotionRequest,
    StructuredRequest,
    WebRequest,
)
from pipeline.router import _error_from_exc, route

router = APIRouter()


@router.post("/structured", response_model=IngestResponse)
async def ingest_structured(body: StructuredRequest, request: Request) -> IngestResponse:
    start = time.monotonic()
    adapter = StructuredAdapter()
    items = adapter.process(body)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="structured",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/document", response_model=IngestResponse)
async def ingest_document(
    request: Request,
    file: Optional[UploadFile] = File(None),
    title: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    occurred_at: Optional[str] = Form(None),
    chunk_size: Optional[int] = Form(None),
    access_class: Optional[str] = Form(None),
    link_target_canonical_key: Optional[str] = Form(None),
    link_relationship_type: Optional[str] = Form(None),
) -> IngestResponse:
    start = time.monotonic()
    adapter = DocumentAdapter()

    link = None
    if link_target_canonical_key:
        link = LinkSpec(
            target_canonical_key=link_target_canonical_key,
            relationship_type=link_relationship_type,
        )

    if file and file.filename:
        if file.size is not None and file.size > settings.max_upload_bytes:
            raise ValidationError(
                f"Upload size {file.size:,} exceeds maximum {settings.max_upload_bytes:,} bytes"
            )
        raw_bytes = await file.read()
        if len(raw_bytes) > settings.max_upload_bytes:
            raise ValidationError(
                f"Upload size {len(raw_bytes):,} exceeds maximum {settings.max_upload_bytes:,} bytes"
            )
        items = adapter.process_file(
            filename=file.filename,
            data=raw_bytes,
            occurred_at=occurred_at,
            chunk_size=chunk_size,
            access_class=access_class,
            link=link,
        )
    else:
        body = DocumentRequest(
            title=title,
            content=content,
            occurred_at=occurred_at,
            chunk_size=chunk_size,
            access_class=access_class,
            link=link,
        )
        items = adapter.process_text(body)

    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="document",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/document/json", response_model=IngestResponse)
async def ingest_document_json(body: DocumentRequest, request: Request) -> IngestResponse:
    """JSON-only document ingestion (no file upload)."""
    start = time.monotonic()
    adapter = DocumentAdapter()
    items = adapter.process_text(body)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="document",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/conversation", response_model=IngestResponse)
async def ingest_conversation(body: ConversationRequest, request: Request) -> IngestResponse:
    start = time.monotonic()
    adapter = ConversationAdapter()
    items = adapter.process(body)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="conversation",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/web", response_model=IngestResponse)
async def ingest_web(body: WebRequest, request: Request) -> IngestResponse:
    start = time.monotonic()
    adapter = WebAdapter()
    items = await adapter.process(body, http=request.app.state.http)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="web",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


async def _load_company_domains(http, tenant_id: str) -> dict[str, str]:
    """Existing CRM company nodes for a tenant, as {domain: label}.

    Read from the graph over PostgREST (service-role key). Companies are keyed
    `company::{tenant}::{domain}`; the `id:` fallback keys (no domain) are
    skipped. Used so an email domain matching a known company merges with it and
    inherits its real name."""
    key = settings.supabase_service_role_key
    prefix = f"company::{tenant_id}::"
    resp = await http.get(
        f"{settings.supabase_url}/rest/v1/pointers",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        params={"type": "eq.company", "select": "canonical_key,label"},
        timeout=settings.web_scrape_timeout,
    )
    resp.raise_for_status()
    out: dict[str, str] = {}
    for row in resp.json():
        ck = row.get("canonical_key") or ""
        if not ck.startswith(prefix):
            continue
        domain = ck[len(prefix):].strip().lower()
        if domain and not domain.startswith("id:"):
            out[domain] = row.get("label") or domain
    return out


@router.post("/gmail", response_model=IngestResponse)
async def ingest_gmail(body: GmailRequest, request: Request) -> IngestResponse:
    """Multi-tenant Gmail ingestion. Per firm (tenant) × mailbox, fetch messages
    and build the graph: one `message` per email, person/company entities
    (CRM-reconciled; role mailboxes → company; free-mail → person-only; newsletters
    /automated/invites filtered), `sent`/`received`/`affiliated_with` edges, and a
    participant-private body (`email_body` class, gated by thread_membership).
    Recurrent when `since_last` (per-mailbox cursor)."""
    start = time.monotonic()
    http = request.app.state.http
    client: EdgeFunctionClient = request.app.state.client
    adapter = GmailAdapter()

    firms = load_firms(body.tenant_id)
    explicit_mailboxes = frozenset(m.lower() for f in load_firms() for m in f.mailboxes)

    user_ids = await resolve_user_ids(http)  # email → Supabase user id (for body access)

    results: list[EdgeFunctionResult] = []
    errors: list[IngestError] = []
    produced = 0

    for firm in firms:
        firm_class_key = f"firm:{firm.tenant_id}"
        firm_class_id = await ensure_class(
            http, firm_class_key, f"Firm {firm.tenant_id} shared knowledge"
        )
        await ensure_tenant_grant(http, firm_class_id, firm.tenant_id)

        crm_names = await _load_company_domains(http, firm.tenant_id)
        own_domains = {m.split("@", 1)[1].lower() for m in firm.mailboxes if "@" in m}
        if firm.domain:
            own_domains.add(firm.domain.lower())

        if body.subject:
            # Scope the run to a single mailbox (skips discovery). When the caller
            # also pins tenant_id they've explicitly targeted this firm, so trust
            # the subject (the firm's SA has DWD over its Workspace) even if the
            # mailbox isn't in the static list. Without tenant_id, only firms that
            # actually own the address act.
            want = body.subject.strip().lower()
            if body.tenant_id:
                mailboxes = [want]
            elif want in {m.lower() for m in firm.mailboxes} or (
                firm.domain is not None and want.endswith("@" + firm.domain.lower())
            ):
                mailboxes = [want]
            else:
                mailboxes = []
        else:
            mailboxes = firm.mailboxes or await discover_mailboxes(
                firm, http, exclude=explicit_mailboxes
            )

        # Phase A: collect all messages for the firm (so the correspondent set —
        # domains we've emailed — spans every mailbox), advancing cursors.
        messages = []
        cursor_marks: list[tuple[str, str]] = []
        for mailbox in mailboxes:
            if "@" in mailbox:
                own_domains.add(mailbox.split("@", 1)[1].lower())
            cursor_key = f"gmail:{firm.tenant_id}:{mailbox}"
            run_started = datetime.now(timezone.utc).isoformat()
            query = body.query
            if body.since_last:
                cursor = await get_cursor(http, cursor_key)
                query = (
                    f"newer_than:{settings.gmail_backfill_days}d"
                    if cursor is None
                    else f"after:{int(datetime.fromisoformat(cursor).timestamp())}"
                )
            elif not query:
                query = f"newer_than:{settings.gmail_backfill_days}d"
            try:
                msgs = await adapter.fetch_messages(
                    firm, mailbox, http, query=query, max_results=body.max_results
                )
            except (AdapterError, ValidationError) as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))
                continue
            messages.extend(msgs)
            cursor_marks.append((cursor_key, run_started))

        # Phase B: deterministic extraction, then write entities + edges.
        graph = extract_graph(
            messages,
            crm_domains=set(crm_names),
            crm_names=crm_names,
            own_domains=own_domains,
        )
        id_by_key: dict[str, str] = {}
        created_messages: set[str] = set()
        for ent in graph.entities:
            idx = len(results) + len(errors)
            try:
                resp = await client.insert_pointer(
                    label=ent.label,
                    type=ent.type,
                    canonical_key=ent.canonical_key,
                    metadata=ent.metadata or None,
                    occurred_at=ent.occurred_at,
                    access_class=firm_class_key,
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(idx, exc))
                continue
            pid = resp.get("pointer_id")
            if pid:
                id_by_key[ent.canonical_key] = pid
                produced += 1
                if ent.type == "message" and resp.get("status") in ("created", "pending_review"):
                    created_messages.add(ent.canonical_key)
                results.append(
                    EdgeFunctionResult(
                        index=idx, status=resp.get("status", "unknown"), pointer_id=pid
                    )
                )

        for edge in graph.edges:
            src = id_by_key.get(edge.source)
            tgt = id_by_key.get(edge.target)
            if not src or not tgt:
                continue
            try:
                await client.link_pointers(
                    source_id=src, target_id=tgt,
                    relationship_type=edge.rel, why=edge.why,
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))

        # Phase C: private bodies. One document per newly-created message (skip
        # `merged` — the second-mailbox copy / since_last overlap is already in),
        # gated to the thread's participants via thread_membership.
        msg_by_key = {}
        for m in messages:
            msg_by_key.setdefault(message_key(m.tenant_id, m.message_id), m)
        for key, m in msg_by_key.items():
            pid = id_by_key.get(key)
            if not pid or key not in created_messages:
                continue
            content = f"{m.subject}\n\n{m.body}".strip() if m.subject else m.body.strip()
            if not content:
                continue
            if _utf16_len(content) > settings.max_content_length:
                content = _truncate_utf16(content, settings.max_content_length)
            idx = len(results) + len(errors)
            try:
                member_uids = {
                    uid for uid in (
                        user_ids.get(a)
                        for a in {m.sender[0], *(a for a, _ in m.to), *(a for a, _ in m.cc)}
                    ) if uid
                }
                await add_thread_members(http, m.tenant_id, m.thread_id, member_uids)
                await client.ingest_document(
                    title=m.subject or "(no subject)",
                    content=content,
                    occurred_at=m.occurred_at,
                    metadata={
                        "tenant_id": m.tenant_id,
                        "thread_id": m.thread_id,
                        "mailbox": m.mailbox,
                        "gmail_message_id": m.message_id,
                    },
                    access_class="email_body",
                    canonical_key_namespace=m.tenant_id,
                    link={
                        "target_id": pid,
                        "relationship_type": "email_content",
                        "why": "Body of this email",
                    },
                )
            except (AdapterError, EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(idx, exc))

        if body.since_last:
            for cursor_key, mark in cursor_marks:
                await set_cursor(http, cursor_key, mark)

    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="gmail",
        items_produced=produced,
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/notes", response_model=IngestResponse)
async def ingest_notes(body: NotesRequest, request: Request) -> IngestResponse:
    """Multi-tenant meeting-notes ingestion. Per firm (tenant), read meeting rows
    from the source Supabase project and split each into a firm-wide who-met-whom
    graph (public-within-firm) and a body (notion_summary) that is firm-wide unless
    the row is Confidential (then private to owner + attendees). Recurrent when
    `since_last` (per-tenant `last_edited_time` cursor)."""
    start = time.monotonic()
    http = request.app.state.http
    client: EdgeFunctionClient = request.app.state.client
    adapter = NotesAdapter()

    firms = load_notes_firms(body.tenant_id)
    # email -> Supabase user id, for granting confidential bodies to participants.
    user_ids = await resolve_user_ids(http)

    results: list[EdgeFunctionResult] = []
    errors: list[IngestError] = []
    produced = 0

    for firm in firms:
        # Firm-wide class granted to the tenant (idempotent, one-time per firm).
        firm_class_key = f"firm:{firm.tenant_id}"
        firm_class_id = await ensure_class(
            http, firm_class_key, f"Firm {firm.tenant_id} shared knowledge"
        )
        await ensure_tenant_grant(http, firm_class_id, firm.tenant_id)

        cursor_key = f"notes:{firm.tenant_id}"
        since = await get_cursor(http, cursor_key) if body.since_last else None

        try:
            fetched = await adapter.fetch_notes(firm, since=since, max_results=body.max_results)
        except (AdapterError, ValidationError) as exc:
            errors.append(_error_from_exc(len(results) + len(errors), exc))
            continue
        notes = fetched.notes

        # CRM company domains/names, so attendee domains + free-text external_org
        # resolve onto the existing `company::{tenant}::{domain}` nodes.
        crm_names = await _load_company_domains(http, firm.tenant_id)
        graph = extract_notes_graph(
            notes,
            crm_domains=set(crm_names),
            crm_names=crm_names,
            name_to_domain=build_company_index(crm_names),
            own_domains=fetched.own_domains,
        )

        # Phase B: deterministic extraction → entities, then edges (mirror Gmail).
        id_by_key: dict[str, str] = {}
        for ent in graph.entities:
            idx = len(results) + len(errors)
            try:
                resp = await client.insert_pointer(
                    label=ent.label,
                    type=ent.type,
                    canonical_key=ent.canonical_key,
                    metadata=ent.metadata or None,
                    occurred_at=ent.occurred_at,
                    access_class=firm_class_key,
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(idx, exc))
                continue
            pid = resp.get("pointer_id")
            if pid:
                id_by_key[ent.canonical_key] = pid
                produced += 1
                results.append(
                    EdgeFunctionResult(index=idx, status=resp.get("status", "unknown"), pointer_id=pid)
                )

        for edge in graph.edges:
            src = id_by_key.get(edge.source)
            tgt = id_by_key.get(edge.target)
            if not src or not tgt:
                continue
            try:
                await client.link_pointers(
                    source_id=src, target_id=tgt,
                    relationship_type=edge.rel, why=edge.why,
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))

        # Phase C: bodies. One document per meeting with a summary, linked to its
        # event; firm-wide unless Confidential → private class + participant grants.
        max_edited = _max_iso(since, None)
        for note in notes:
            if note.body:
                idx = len(results) + len(errors)
                try:
                    await _ingest_note_body(http, client, note, firm_class_key, user_ids, id_by_key)
                except (AdapterError, EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                    errors.append(_error_from_exc(idx, exc))
            max_edited = _max_iso(max_edited, note.last_edited)

        if body.since_last and max_edited:
            await set_cursor(http, cursor_key, max_edited)

    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="notes",
        items_produced=produced,
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


def _max_iso(a: str | None, b: str | None) -> str | None:
    """Larger of two ISO timestamps, comparing as datetimes (offset-safe)."""
    candidates = []
    for v in (a, b):
        if not v:
            continue
        try:
            candidates.append((datetime.fromisoformat(v), v))
        except ValueError:
            continue
    if not candidates:
        return a or b
    return max(candidates, key=lambda t: t[0])[1]


async def _ingest_note_body(
    http,
    client: EdgeFunctionClient,
    note: MeetingNote,
    firm_class_key: str,
    user_ids: dict[str, str],
    id_by_key: dict[str, str],
) -> None:
    """Ingest a meeting's summary as a document linked to its event node.
    Firm-wide unless Confidential → a private class ensured BEFORE ingest (fail
    closed) and granted to the owner + attendees who have platform accounts."""
    tenant = note.tenant_id
    start = note.occurred_at or note.last_edited
    event_id = id_by_key.get(f"event:{tenant}:meetingnote:{note.page_id}")

    if note.confidential:
        body_class = f"meetingnote:{tenant}:{note.page_id}"
        private_id = await ensure_class(
            http, body_class, f"Confidential meeting note {note.page_id} (tenant {tenant})"
        )
        grant_emails = set(note.attendees)
        if note.owner_email:
            grant_emails.add(note.owner_email)
        for email_addr in grant_emails:
            uid = user_ids.get(email_addr)
            if uid:
                await ensure_user_grant(http, private_id, uid)
    else:
        body_class = firm_class_key

    link = (
        {
            "target_id": event_id,
            "relationship_type": "meeting_notes",
            "why": "Notes/summary of this meeting",
        }
        if event_id
        else None
    )
    await client.ingest_document(
        title=note.title,
        content=note.body,
        occurred_at=start,
        metadata={"page_id": note.page_id, "confidential": note.confidential},
        access_class=body_class,
        canonical_key_namespace=tenant,
        link=link,
    )


@router.post("/notion", response_model=IngestResponse)
async def ingest_notion(body: NotionRequest, request: Request) -> IngestResponse:
    if NotionAdapter is None:
        raise ValidationError("Notion connector unavailable: adapter source files are missing")
    start = time.monotonic()
    http = request.app.state.http
    effective = body
    run_started: str | None = None

    if body.since_last:
        run_started = datetime.now(timezone.utc).isoformat()
        cursor = await get_cursor(http, "notion")
        if cursor is None:
            # First scheduled run: start from now — record the cursor and ingest
            # nothing. Historical content comes from the workspace-export import.
            await set_cursor(http, "notion", run_started)
            elapsed = int((time.monotonic() - start) * 1000)
            return IngestResponse(
                source_type="notion", items_produced=0, duration_ms=elapsed
            )
        effective = body.model_copy(update={"edited_after": cursor})

    adapter = NotionAdapter()
    items = await adapter.process(effective, http=http)
    results, errors = await route(items, request.app.state.client)

    if run_started is not None:
        # Advance the cursor on completion; overlap is harmless (content-hash dedup).
        await set_cursor(http, "notion", run_started)

    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="notion",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/notion-export", response_model=IngestResponse)
async def ingest_notion_export(
    request: Request, file: UploadFile = File(...)
) -> IngestResponse:
    if NotionExportAdapter is None:
        raise ValidationError("Notion connector unavailable: adapter source files are missing")
    start = time.monotonic()
    items = await NotionExportAdapter().process(file)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="notion-export",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


# ── Affinidad (Kibo's in-house CRM) ─────────────────────────────────

_AFFINIDAD_OBJECTS = ["entities", "edges", "deals", "notes", "events"]
_INGEST_ERRORS = (AdapterError, EdgeFunctionError, EdgeFunctionTimeout, ValidationError)


def _attr_dicts(attrs) -> list[dict]:
    """(key, value, data_type) tuples → insert-pointer/ingest-batch attribute rows."""
    return [
        {"key": k, "value": v, "data_type": dt, "source": "affinidad"}
        for (k, v, dt) in attrs
    ]


async def _ingest_crm_entity(client: EdgeFunctionClient, ent: CrmEntity, firm_class_key: str) -> dict:
    """One company/person entity → a pointer (+ its attributes), firm-wide."""
    return await client.insert_pointer(
        label=ent.label,
        type=ent.kind,
        canonical_key=ent.canonical_key,
        metadata=ent.metadata,
        access_class=firm_class_key,
        attributes=_attr_dicts(ent.attributes) or None,
    )


async def _ingest_crm_edge(client: EdgeFunctionClient, edge: CrmEdge, resolve) -> dict | None:
    """One entity_edges row → a graph edge, once both endpoints resolve to pointers."""
    src = await resolve(edge.source_id)
    tgt = await resolve(edge.target_id)
    if not src or not tgt:
        return None
    return await client.link_pointers(
        source_id=src,
        target_id=tgt,
        relationship_type=edge.relation,
        why=f"{edge.relation} (from Affinidad CRM)",
        payload=edge.metadata or None,
    )


async def _apply_deal_attributes(
    client: EdgeFunctionClient,
    deal: CrmDeal,
    entity_by_id: dict[str, CrmEntity],
    firm_class_key: str,
) -> dict | None:
    """A list membership → per-list namespaced attributes upserted on the company
    pointer (re-inserting by canonical_key returns the existing pointer + upserts
    attributes_kv via its UNIQUE(pointer_id, key))."""
    ent = entity_by_id.get(deal.company_id)
    if ent is None or not deal.attributes:
        return None
    return await client.insert_pointer(
        label=ent.label,
        type="company",
        canonical_key=ent.canonical_key,
        access_class=firm_class_key,
        attributes=_attr_dicts(deal.attributes),
    )


async def _ingest_crm_note(
    http,
    client: EdgeFunctionClient,
    note: CrmNote,
    firm_class_key: str,
    user_ids: dict[str, str],
    resolve_link,
) -> dict:
    """One note → a document, firm-wide unless private (then a per-note class
    ensured + granted to the author BEFORE ingest), plus note_about edges to each
    linked entity that resolves to a pointer."""
    if note.private:
        body_class = f"affinidadnote:{note.tenant_id}:{note.note_id}"
        class_id = await ensure_class(
            http, body_class, f"Private CRM note {note.note_id} (tenant {note.tenant_id})"
        )
        if note.author_email:
            uid = user_ids.get(note.author_email)
            if uid:
                await ensure_user_grant(http, class_id, uid)
    else:
        body_class = firm_class_key

    doc = await client.ingest_document(
        title=note.label,
        content=note.body,
        occurred_at=note.occurred_at,
        metadata={
            "source": "affinidad",
            "note_id": note.note_id,
            "visibility": "private" if note.private else "org",
        },
        access_class=body_class,
        canonical_key_namespace=note.tenant_id,
    )
    doc_id = doc.get("pointer_id")
    if doc_id:
        for (entity_type, entity_id) in note.links:
            tgt = await resolve_link(entity_type, entity_id)
            if tgt:
                await client.link_pointers(
                    source_id=doc_id,
                    target_id=tgt,
                    relationship_type="note_about",
                    why="Note about this entity",
                )
    return doc


async def _ingest_crm_event(
    http,
    client: EdgeFunctionClient,
    ev: CrmEvent,
    firm_class_key: str,
    user_ids: dict[str, str],
    resolve,
    entity_by_id: dict[str, CrmEntity],
) -> dict:
    """One interaction → a firm-wide event pointer (the fact: who/when/type) +
    participant edges (preserving the source role), and — if there's body text —
    a participant-only document linked to the event (fail-closed: the per-event
    class is ensured + granted to participant users before the body is ingested)."""
    pointer = await client.insert_pointer(
        label=ev.label,
        type="event",
        canonical_key=event_key(ev.tenant_id, ev.event_id),
        metadata=ev.metadata,
        occurred_at=ev.occurred_at,
        access_class=firm_class_key,
    )
    event_id = pointer.get("pointer_id")

    for (entity_type, entity_id, role) in ev.participants:
        pid = await resolve(entity_id)
        if pid and event_id:
            await client.link_pointers(
                source_id=pid,
                target_id=event_id,
                relationship_type=role,
                why=f"{role} of this {ev.type}",
            )

    if ev.body:
        body_class = f"affinidadevent:{ev.tenant_id}:{ev.event_id}"
        class_id = await ensure_class(
            http, body_class,
            f"Participant-only {ev.type} body {ev.event_id} (tenant {ev.tenant_id})",
        )
        for (_etype, entity_id, _role) in ev.participants:
            ent = entity_by_id.get(entity_id)
            email = getattr(ent, "email", None) if ent else None
            uid = user_ids.get(email) if email else None
            if uid:
                await ensure_user_grant(http, class_id, uid)
        rel = "email_content" if ev.type == "email" else "meeting_notes"
        link = (
            {"target_id": event_id, "relationship_type": rel, "why": f"Body of this {ev.type}"}
            if event_id
            else None
        )
        # Email subjects are participant-only, so they live in the private body, not
        # the org-wide node label.
        content = f"{ev.subject}\n\n{ev.body}" if ev.subject else ev.body
        await client.ingest_document(
            title=ev.subject or ev.label,
            content=content,
            occurred_at=ev.occurred_at,
            metadata={"source": "affinidad", "event_id": ev.event_id, "event_type": ev.type},
            access_class=body_class,
            canonical_key_namespace=ev.tenant_id,
            link=link,
        )
    return pointer


@router.post("/affinidad", response_model=IngestResponse)
async def ingest_affinidad(body: AffinidadRequest, request: Request) -> IngestResponse:
    """One-time historical backfill of Kibo's in-house CRM ("Affinidad") into the
    graph. Per firm (tenant): companies/people → pointers, entity_edges → edges,
    list memberships → namespaced company attributes ("deals"), notes → documents
    (org or author-private), and interactions → event pointers + participant edges
    with a participant-only body document. Idempotent (canonical-key dedup). Order
    is entities → edges → deals → notes → events so endpoints exist before linking.
    `objects` restricts a run to specific types (staged backfill of large events)."""
    start = time.monotonic()
    http = request.app.state.http
    client: EdgeFunctionClient = request.app.state.client
    adapter = AffinidadAdapter()

    firms = load_affinidad_firms(body.tenant_id)
    user_ids = await resolve_user_ids(http)
    objects = set(body.objects or _AFFINIDAD_OBJECTS)

    results: list[EdgeFunctionResult] = []
    errors: list[IngestError] = []
    produced = 0

    def _ok(resp: dict | None) -> None:
        nonlocal produced
        produced += 1
        results.append(
            EdgeFunctionResult(
                index=len(results) + len(errors),
                status=(resp or {}).get("status", "unknown"),
                pointer_id=(resp or {}).get("pointer_id"),
                detail=resp,
            )
        )

    def _fail(exc: Exception) -> None:
        errors.append(_error_from_exc(len(results) + len(errors), exc))

    for firm in firms:
        firm_class_key = f"firm:{firm.tenant_id}"
        firm_class_id = await ensure_class(
            http, firm_class_key, f"Firm {firm.tenant_id} shared knowledge"
        )
        await ensure_tenant_grant(http, firm_class_id, firm.tenant_id)

        # Always load entities (cheap) to resolve edges/notes/events to pointers,
        # even when this run only ingests downstream objects.
        try:
            entities = await adapter.fetch_entities(firm)
        except _INGEST_ERRORS as exc:
            _fail(exc)
            continue
        entity_by_id = {e.entity_id: e for e in entities}
        ptr_by_entity: dict[str, str] = {}
        pid_cache: dict[str, str | None] = {}

        async def resolve(entity_id: str):
            if entity_id in ptr_by_entity:
                return ptr_by_entity[entity_id]
            if entity_id in pid_cache:
                return pid_cache[entity_id]
            ent = entity_by_id.get(entity_id)
            pid = await resolve_pointer_id(http, ent.canonical_key) if ent else None
            pid_cache[entity_id] = pid
            return pid

        async def resolve_link(entity_type: str, entity_id: str):
            if entity_type in ("company", "person"):
                return await resolve(entity_id)
            if entity_type == "event":
                key = f"evt:{entity_id}"
                if key not in pid_cache:
                    pid_cache[key] = await resolve_pointer_id(
                        http, event_key(firm.tenant_id, entity_id)
                    )
                return pid_cache[key]
            return None  # 'meeting' legacy-shim ids are covered via events

        sem = asyncio.Semaphore(settings.affinidad_concurrency)

        async def _run(items, worker) -> None:
            """Run `worker(item)` for every item with bounded concurrency, recording
            each result/error. Safe: canonical-key dedup is a transactional upsert."""
            async def guarded(item):
                async with sem:
                    try:
                        resp = await worker(item)
                        if resp is not None:
                            _ok(resp)
                    except _INGEST_ERRORS as exc:
                        _fail(exc)
            await asyncio.gather(*(guarded(i) for i in items))

        async def _do_entity(ent):
            resp = await _ingest_crm_entity(client, ent, firm_class_key)
            pid = resp.get("pointer_id")
            if pid:
                ptr_by_entity[ent.entity_id] = pid
            return resp

        if "entities" in objects:
            await _run(entities, _do_entity)

        if "edges" in objects:
            try:
                edges = await adapter.fetch_edges(firm)
            except _INGEST_ERRORS as exc:
                edges = []
                _fail(exc)
            await _run(edges, lambda edge: _ingest_crm_edge(client, edge, resolve))

        if "deals" in objects:
            try:
                deals = await adapter.fetch_deals(firm)
            except _INGEST_ERRORS as exc:
                deals = []
                _fail(exc)
            await _run(
                deals,
                lambda deal: _apply_deal_attributes(client, deal, entity_by_id, firm_class_key),
            )

        if "notes" in objects:
            try:
                notes = await adapter.fetch_notes(firm)
            except _INGEST_ERRORS as exc:
                notes = []
                _fail(exc)
            await _run(
                notes,
                lambda note: _ingest_crm_note(
                    http, client, note, firm_class_key, user_ids, resolve_link
                ),
            )

        if "events" in objects:
            try:
                events = await adapter.fetch_events(firm, max_results=body.max_results)
            except _INGEST_ERRORS as exc:
                events = []
                _fail(exc)
            await _run(
                events,
                lambda ev: _ingest_crm_event(
                    http, client, ev, firm_class_key, user_ids, resolve, entity_by_id
                ),
            )

    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="affinidad",
        items_produced=produced,
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )
