from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form

from pipeline.access import (
    ensure_class,
    ensure_tenant_grant,
    ensure_user_grant,
    resolve_user_ids,
)
from pipeline.adapters.conversation import ConversationAdapter
from pipeline.adapters.document import DocumentAdapter
from pipeline.adapters.gmail import EmailThread, GmailAdapter, load_firms
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

        for mailbox in firm.mailboxes:
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
