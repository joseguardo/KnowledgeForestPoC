from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form

from pipeline.access import (
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
from pipeline.adapters.gmail import (
    EmailThread,
    GmailAdapter,
    discover_mailboxes,
    load_firms,
)
from pipeline.adapters.notes import (
    MeetingNote,
    NotesAdapter,
    load_notes_firms,
    slugify,
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


@router.post("/gmail", response_model=IngestResponse)
async def ingest_gmail(body: GmailRequest, request: Request) -> IngestResponse:
    """Multi-tenant Gmail ingestion. Per firm (tenant) × mailbox, fetch threads and
    split each into a firm-wide communication graph (public-within-firm) and a
    participant-private body. Recurrent when `since_last` (per-mailbox cursor)."""
    start = time.monotonic()
    http = request.app.state.http
    client: EdgeFunctionClient = request.app.state.client
    adapter = GmailAdapter()

    firms = load_firms(body.tenant_id)
    # Carve-out for domain auto-discovery: every mailbox any firm claims
    # explicitly, across the WHOLE config (not just this run's tenant filter) —
    # so discovering one tenant's domain never swallows another tenant's
    # explicitly-listed mailboxes that share the same Workspace.
    explicit_mailboxes = frozenset(
        m.lower() for f in load_firms() for m in f.mailboxes
    )
    # email -> Supabase user id, for granting per-thread private classes.
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

        mailboxes = firm.mailboxes or await discover_mailboxes(
            firm, http, exclude=explicit_mailboxes
        )
        for mailbox in mailboxes:
            cursor_key = f"gmail:{firm.tenant_id}:{mailbox}"
            run_started = datetime.now(timezone.utc).isoformat()
            query = body.query
            if body.since_last:
                cursor = await get_cursor(http, cursor_key)
                if cursor is None:
                    query = f"newer_than:{settings.gmail_backfill_days}d"
                else:
                    epoch = int(datetime.fromisoformat(cursor).timestamp())
                    query = f"after:{epoch}"
            elif not query:
                # Manual pull with no query → bound it to the lookback window so we
                # never accidentally ingest (and embed) years of mail.
                query = f"newer_than:{settings.gmail_backfill_days}d"

            threads = await adapter.fetch_threads(
                firm, mailbox, http, query=query, max_results=body.max_results
            )
            for thread in threads:
                idx = len(results) + len(errors)
                try:
                    resp = await _ingest_thread(
                        http, client, thread, firm_class_key, user_ids
                    )
                    produced += 1
                    results.append(
                        EdgeFunctionResult(
                            index=idx,
                            status=resp["email"].get("status", "unknown"),
                            pointer_id=resp.get("event_id"),
                            detail=resp,
                        )
                    )
                except (
                    AdapterError,
                    EdgeFunctionError,
                    EdgeFunctionTimeout,
                    ValidationError,
                ) as exc:
                    errors.append(_error_from_exc(idx, exc))

            if body.since_last:
                await set_cursor(http, cursor_key, run_started)

    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="gmail",
        items_produced=produced,
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


async def _ingest_thread(
    http,
    client: EdgeFunctionClient,
    thread: EmailThread,
    firm_class_key: str,
    user_ids: dict[str, str],
) -> dict:
    """One thread → public communication graph + private body. Fail closed: the
    private class is ensured (raises on failure) BEFORE the body is ingested, so
    a missing class can never let the body fall back to the public class."""
    tenant = thread.tenant_id

    # 1. Private per-thread class + participant grants (fail closed).
    private_key = f"gmailthread:{tenant}:{thread.thread_hash}"
    private_class_id = await ensure_class(
        http, private_key, f"Email thread {thread.thread_hash} (tenant {tenant})"
    )
    for email_addr in {p.email for p in thread.participants}:
        uid = user_ids.get(email_addr)
        if uid:
            await ensure_user_grant(http, private_class_id, uid)

    # 2. Public-within-firm communication graph (entities + event + edges).
    participants_payload = [
        {
            "canonical_key": f"person::{tenant}::{p.email}",
            "label": p.name or p.email,
            "role": p.role,
        }
        for p in thread.participants
    ]
    event_payload = {
        "label": thread.event_label,
        "canonical_key": f"event:{tenant}:gmailthread:{thread.thread_hash}",
        "occurred_at": thread.occurred_at,
        "metadata": thread.metadata,
    }
    email_resp = await client.ingest_email(
        tenant_id=tenant,
        participants=participants_payload,
        event=event_payload,
        access_class=firm_class_key,
        source="gmail",
    )
    event_id = email_resp.get("pointer_id")

    # 3. Private body, linked to the public event.
    link = (
        {
            "target_id": event_id,
            "relationship_type": "email_content",
            "why": "Private body of this email thread",
        }
        if event_id
        else None
    )
    doc_resp = await client.ingest_document(
        title=thread.event_label,
        content=thread.body,
        occurred_at=thread.occurred_at,
        metadata={
            "gmail_thread_id": thread.gmail_thread_id,
            "mailbox": thread.mailbox,
        },
        access_class=private_key,
        canonical_key_namespace=tenant,
        link=link,
    )
    return {"email": email_resp, "doc": doc_resp, "event_id": event_id}


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
            notes = await adapter.fetch_notes(firm, since=since, max_results=body.max_results)
        except (AdapterError, ValidationError) as exc:
            errors.append(_error_from_exc(len(results) + len(errors), exc))
            continue

        max_edited = _max_iso(since, None)
        for note in notes:
            idx = len(results) + len(errors)
            try:
                resp = await _ingest_meeting(
                    http, client, note, firm_class_key, user_ids
                )
                produced += 1
                results.append(
                    EdgeFunctionResult(
                        index=idx,
                        status=resp.get("status", "unknown"),
                        pointer_id=resp.get("event_id"),
                        detail=resp,
                    )
                )
            except (
                AdapterError,
                EdgeFunctionError,
                EdgeFunctionTimeout,
                ValidationError,
            ) as exc:
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


async def _ingest_meeting(
    http,
    client: EdgeFunctionClient,
    note: MeetingNote,
    firm_class_key: str,
    user_ids: dict[str, str],
) -> dict:
    """One meeting → firm-wide graph (via ingest-calendar) + body (via
    ingest-document). Confidential bodies get a private class ensured BEFORE
    ingest (fail closed) and granted to owner + attendees with accounts."""
    tenant = note.tenant_id

    start = note.occurred_at or note.last_edited
    if not start:
        raise AdapterError(f"Meeting {note.page_id} has no usable date (start/last_edited)")

    # 1. Firm-wide who-met-whom graph (owner + attendees + company + event).
    owner_key = (
        f"person::{tenant}::{note.owner_email}"
        if note.owner_email
        else f"person::{tenant}::name:{slugify(note.owner_name)}"
    )
    owner = {
        "label": note.owner_name or note.owner_email or "Unknown",
        "canonical_key": owner_key,
        "type": "person",
    }
    attendees_payload = [
        {"label": e, "canonical_key": f"person::{tenant}::{e}", "type": "person"}
        for e in note.attendees
    ]
    event: dict = {
        "title": note.title,
        "start": start,
        "canonical_key": f"event:{tenant}:meetingnote:{note.page_id}",
        "event_type": "meeting",
        "attendees": attendees_payload,
    }
    # Company isolation relies on the firm access class (the dedup class-mismatch
    # guard keeps each firm's company node separate); ingest-calendar's company
    # field is label-only, so it carries no tenant in its canonical key.
    if note.company:
        event["company"] = note.company

    cal_resp = await client.ingest_calendar(
        owner=owner,
        events=[event],
        access_class=firm_class_key,
        source="notes",
    )
    cal_results = cal_resp.get("results") or []
    first = cal_results[0] if cal_results else {}
    event_id = first.get("pointer_id")
    status = first.get("status", "unknown")

    doc_resp = None
    if note.body:
        # 2. Body access class: firm-wide, unless Confidential → private + grants.
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
        doc_resp = await client.ingest_document(
            title=note.title,
            content=note.body,
            occurred_at=start,
            metadata={"page_id": note.page_id, "confidential": note.confidential},
            access_class=body_class,
            canonical_key_namespace=tenant,
            link=link,
        )

    return {"calendar": cal_resp, "doc": doc_resp, "event_id": event_id, "status": status}


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
