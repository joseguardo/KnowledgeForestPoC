from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form

from pipeline.access import (
    resolve_pointer_id,
    resolve_user_ids,
)
from pipeline.adapters.affinidad import (
    AffinidadAdapter,
    AffinidadFirm,
    CrmDeal,
    CrmEdge,
    CrmEntity,
    CrmEvent,
    CrmNote,
    communication_key,
    event_key,
    list_tenant,
    load_affinidad_firms,
)
from pipeline.mcp_server.tenant_map import resolve_tenants
from pipeline.adapters.calendar import (
    _calendar_sa_info,
    fetch_events as fetch_calendar_events,
)
from pipeline.adapters.calendar_entities import (
    event_key as calendar_event_key,
    extract_graph as extract_calendar_graph,
)
from pipeline import event_sync
from pipeline import crm_sync
from pipeline.adapters.conversation import ConversationAdapter
from pipeline.adapters.document import DocumentAdapter
from pipeline.adapters.email_entities import _looks_like_email, extract_graph, message_key
from pipeline.adapters.gmail import (
    EmailRejection,
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
    event_key as notes_event_key,
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
from pipeline.ingestion_rejections import log_rejections
from pipeline.errors import (
    AdapterError,
    EdgeFunctionError,
    EdgeFunctionTimeout,
    ValidationError,
)
from pipeline.models import (
    AffinidadRequest,
    CalendarRequest,
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


async def _load_person_names(http, tenant_id: str) -> dict[str, str]:
    """Named person nodes as {email: name} — the cross-tenant person directory.

    Persons are now keyed globally `person::{email}` (the tenant_id arg is kept
    for signature stability but no longer filters). Read over PostgREST
    (service-role key); the tenant-scoped `id:` fallback keys (`person::{tenant}::
    id:…`, which contain a second `::`) and nodes still labelled with a bare email
    are excluded. Used to label an attendee with a real name; no name → dropped."""
    key = settings.supabase_service_role_key
    prefix = "person::"
    resp = await http.get(
        f"{settings.supabase_url}/rest/v1/pointers",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        params={"type": "eq.person", "select": "canonical_key,label"},
        timeout=settings.web_scrape_timeout,
    )
    resp.raise_for_status()
    out: dict[str, str] = {}
    for row in resp.json():
        ck = row.get("canonical_key") or ""
        if not ck.startswith(prefix):
            continue
        email = ck[len(prefix):].strip().lower()
        # Skip tenant-scoped id-fallbacks (person::{tenant}::id:…) — not global emails.
        if "::" in email or not email or email.startswith("id:"):
            continue
        label = (row.get("label") or "").strip()
        if label and not _looks_like_email(label):
            out[email] = label
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
        # firm:{tenant} → acl=[tenant] at the write boundary; no class/grant rows.

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
        email_rejections: list[EmailRejection] = []
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
            messages.extend(msgs.messages)
            email_rejections.extend(msgs.rejections)
            cursor_marks.append((cursor_key, run_started))

        # Record why messages were dropped by the noise heuristics (debug log).
        await log_rejections(http, email=email_rejections)

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
                    attributes=ent.attributes or None,
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(idx, exc))
                continue
            pid = resp.get("pointer_id")
            if pid:
                id_by_key[ent.canonical_key] = pid
                produced += 1
                if ent.type == "communication" and resp.get("status") in ("created", "pending_review"):
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
                    principals=[firm.tenant_id],  # tenant-scope the comm-graph edge
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))

        # Phase C: private bodies + attachments. Per newly-created message (skip
        # `merged` — the second-mailbox copy / since_last overlap is already in).
        # Visibility (acl) = the thread participants who have accounts.
        msg_by_key = {}
        for m in messages:
            msg_by_key.setdefault(message_key(m.tenant_id, m.message_id), m)
        for key, m in msg_by_key.items():
            pid = id_by_key.get(key)
            if not pid or key not in created_messages:
                continue
            # Always include the mailbox owner (m.mailbox): the body came from their
            # mailbox, so they're a participant even when not on the visible header
            # (e.g. they were BCC'd, or it's an external↔external thread in their box).
            member_uids = sorted({
                uid for uid in (
                    user_ids.get(a)
                    for a in {m.mailbox, m.sender[0], *(a for a, _ in m.to), *(a for a, _ in m.cc)}
                ) if uid
            })

            # Body: one document linked to the message (skip if empty).
            content = f"{m.subject}\n\n{m.body}".strip() if m.subject else m.body.strip()
            if content:
                if _utf16_len(content) > settings.max_content_length:
                    content = _truncate_utf16(content, settings.max_content_length)
                idx = len(results) + len(errors)
                try:
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
                        principals=member_uids,
                        canonical_key_namespace=m.tenant_id,
                        link={
                            "target_id": pid,
                            "relationship_type": "content_of",
                            "why": "Body of this email",
                        },
                    )
                except (AdapterError, EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                    errors.append(_error_from_exc(idx, exc))

            # Attachments: each real document → its own node (same acl), linked to
            # the email. Content-hash dedup means the same file on two emails is one
            # node with two `attachment` edges. A bad attachment is logged, not fatal.
            for att in m.attachments:
                idx = len(results) + len(errors)
                try:
                    item = DocumentAdapter().process_file(att.filename, att.data)[0]
                    att_content = item.content or ""
                    if _utf16_len(att_content) > settings.max_content_length:
                        att_content = _truncate_utf16(att_content, settings.max_content_length)
                    await client.ingest_document(
                        title=att.filename,
                        content=att_content,
                        occurred_at=m.occurred_at,
                        metadata={
                            "tenant_id": m.tenant_id,
                            "thread_id": m.thread_id,
                            "mailbox": m.mailbox,
                            "gmail_message_id": m.message_id,
                            "attachment_filename": att.filename,
                            "content_type": att.content_type,
                        },
                        principals=member_uids,
                        canonical_key_namespace=m.tenant_id,
                        link={
                            "target_id": pid,
                            "relationship_type": "attachment",
                            "why": "Attached to this email",
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


@router.post("/calendar", response_model=IngestResponse)
async def ingest_calendar(body: CalendarRequest, request: Request) -> IngestResponse:
    """Multi-tenant Google Calendar ingestion. Reuses the Gmail service account +
    GMAIL_FIRMS config: per firm × mailbox, read the mailbox's `primary` calendar
    and build the graph: one firm-wide `event` per meeting (deduped across
    attendees by iCalUID), person/company entities (CRM-reconciled),
    `attended`/`attended_by`/`affiliated_with`/`regarding` edges, and a firm-wide
    description document. No per-user privacy — everyone in the firm sees every
    calendar. Recurrent when `since_last` (per-mailbox `updatedMin` cursor)."""
    start = time.monotonic()
    http = request.app.state.http
    client: EdgeFunctionClient = request.app.state.client

    firms = load_firms(body.tenant_id)
    explicit_mailboxes = frozenset(m.lower() for f in load_firms() for m in f.mailboxes)
    # Calendar runs on its own SA (calendar.readonly DWD authorized there), the
    # firm/mailbox config stays shared. None → fall back to the firm's Gmail SA.
    calendar_sa = _calendar_sa_info()

    results: list[EdgeFunctionResult] = []
    errors: list[IngestError] = []
    produced = 0

    for firm in firms:
        firm_class_key = f"firm:{firm.tenant_id}"
        # firm:{tenant} → acl=[tenant] at the write boundary; no class/grant rows.

        crm_names = await _load_company_domains(http, firm.tenant_id)
        # email → name directory (existing named person nodes), so calendar
        # attendees resolve to real names even when Google omits displayName.
        name_by_email = await _load_person_names(http, firm.tenant_id)
        own_domains = {m.split("@", 1)[1].lower() for m in firm.mailboxes if "@" in m}
        if firm.domain:
            own_domains.add(firm.domain.lower())

        # Mailbox selection mirrors Gmail (subject scoping + shared-Workspace
        # carve-out): an explicit subject is trusted when tenant_id pins the firm,
        # else only the firm that owns the address acts; no subject → the firm's
        # mailbox list, or domain auto-discovery (excluding addresses another firm
        # claimed explicitly).
        if body.subject:
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

        # Phase A: collect all events for the firm, advancing per-mailbox cursors.
        events = []
        cancelled_ical_uids: list[str] = []
        cursor_marks: list[tuple[str, str]] = []
        for mailbox in mailboxes:
            if "@" in mailbox:
                own_domains.add(mailbox.split("@", 1)[1].lower())
            cursor_key = f"google-calendar:{firm.tenant_id}:{mailbox}"
            run_started = datetime.now(timezone.utc).isoformat()
            updated_min = None
            if body.since_last:
                updated_min = await get_cursor(http, cursor_key)
            try:
                fetched = await fetch_calendar_events(
                    firm, mailbox, http, updated_min=updated_min,
                    max_results=body.max_results, sa_info=calendar_sa,
                )
            except (AdapterError, ValidationError) as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))
                continue
            events.extend(fetched.events)
            cancelled_ical_uids.extend(fetched.cancelled_ical_uids)
            cursor_marks.append((cursor_key, run_started))

        # Phase B: deterministic extraction, then write entities + edges.
        graph = extract_calendar_graph(
            events,
            crm_domains=set(crm_names),
            crm_names=crm_names,
            own_domains=own_domains,
            name_by_email=name_by_email,
        )
        id_by_key: dict[str, str] = {}
        # Event nodes that already existed (insert-pointer is first-write-wins):
        # calendar is the source of truth, so these get their time/title/metadata
        # refreshed and their attendee set reconciled below.
        merged_event_keys: set[str] = set()
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
                    attributes=ent.attributes or None,
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(idx, exc))
                continue
            pid = resp.get("pointer_id")
            if pid:
                id_by_key[ent.canonical_key] = pid
                produced += 1
                status = resp.get("status", "unknown")
                results.append(EdgeFunctionResult(index=idx, status=status, pointer_id=pid))
                if ent.type == "communication" and status == "merged":
                    merged_event_keys.add(ent.canonical_key)
                    try:
                        await event_sync.overwrite_event(
                            http, pointer_id=pid, occurred_at=ent.occurred_at,
                            label=ent.label, metadata=ent.metadata or None,
                        )
                    except AdapterError as exc:
                        errors.append(_error_from_exc(len(results) + len(errors), exc))

        # Desired attendee set per event, to prune stale calendar-sourced edges.
        attendees_by_event: dict[str, set[str]] = {}
        for edge in graph.edges:
            if edge.rel == "attended":
                attendees_by_event.setdefault(edge.target, set()).add(edge.source)

        for edge in graph.edges:
            src = id_by_key.get(edge.source)
            tgt = id_by_key.get(edge.target)
            if not src or not tgt:
                continue
            try:
                await client.link_pointers(
                    source_id=src, target_id=tgt,
                    relationship_type=edge.rel, why=edge.why,
                    payload={"source": "calendar"},
                    principals=[firm.tenant_id],  # tenant-scope the comm-graph edge
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))

        # Reconcile attendees on re-ingested events: drop calendar-sourced
        # `attended` edges for people no longer invited (note-sourced edges are
        # left untouched). New attendees were added by the link upsert above.
        # Skipped in backfill mode (one DB round-trip per merged event).
        for ev_key in [] if settings.calendar_skip_reconcile else merged_event_keys:
            ev_pid = id_by_key.get(ev_key)
            if not ev_pid:
                continue
            desired = {
                id_by_key[p] for p in attendees_by_event.get(ev_key, set())
                if p in id_by_key
            }
            try:
                await event_sync.reconcile_attendees(
                    http, event_id=ev_pid, desired_person_ids=desired
                )
            except AdapterError as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))

        # Soft-mark meetings cancelled (or declined) since the last run: keep the
        # node, flag it cancelled, drop its calendar attendance. No-op if we never
        # ingested it.
        for ical_uid in cancelled_ical_uids:
            try:
                await event_sync.soft_cancel_event(
                    http, canonical_key=calendar_event_key(ical_uid)
                )
            except AdapterError as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))

        # Phase C: descriptions. One firm-wide document per event with body text
        # (deduped by iCalUID across calendars), linked to its event node. Each runs
        # an embedding, so this is the slow phase — `calendar_skip_documents` skips
        # it for fast/resilient backfills (event nodes + edges are what matter for
        # downstream matching; descriptions can be backfilled separately).
        ev_by_key: dict[str, object] = {}
        for ev in [] if settings.calendar_skip_documents else events:
            if ev.description:
                ev_by_key.setdefault(calendar_event_key(ev.ical_uid), ev)
        for key, ev in ev_by_key.items():
            pid = id_by_key.get(key)
            if not pid:
                continue
            idx = len(results) + len(errors)
            try:
                await client.ingest_document(
                    title=ev.title,
                    content=ev.description,
                    occurred_at=ev.start,
                    metadata={
                        "tenant_id": ev.tenant_id,
                        "provider": "google-calendar",
                        "ical_uid": ev.ical_uid,
                    },
                    access_class=firm_class_key,
                    canonical_key_namespace=ev.tenant_id,
                    link={
                        "target_id": pid,
                        "relationship_type": "content_of",
                        "why": "Description of this calendar event",
                    },
                )
            except (AdapterError, EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(idx, exc))

        if body.since_last:
            for cursor_key, mark in cursor_marks:
                await set_cursor(http, cursor_key, mark)

    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="calendar",
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
        # firm:{tenant} → acl=[tenant] at the write boundary; no class/grant rows.

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
        # email → name directory: the firm's team table (internal colleagues) plus
        # named CRM/graph person nodes. An attendee with no name here is dropped.
        name_by_email = {
            **await _load_person_names(http, firm.tenant_id),
            **fetched.team_names,
        }
        # Calendar is the source of truth: match each note to an already-ingested
        # calendar meeting and attach to it — notes never create a meeting. A timed
        # note matches the UTC clock-hour; a date-only note matches the UTC day;
        # both require a normalized-title match. Unmatched notes are dropped
        # (calendar is ingested first, so a real meeting is already present).
        attach_to: dict[str, str] = {}
        matched: list[MeetingNote] = []
        for note in notes:
            if note.is_datetime and note.occurred_at:
                when, day = note.occurred_at, False           # real datetime → hour
            elif note.scheduled_at:
                when, day = note.scheduled_at, False          # trailing ISO in title → hour
            else:
                when, day = note.occurred_at, True            # date-only → day + title
            cal_pid = await event_sync.find_calendar_event(
                http, tenant_id=firm.tenant_id, scheduled_at=when, title=note.title, day=day,
            )
            if cal_pid:
                attach_to[notes_event_key(firm.tenant_id, note)] = cal_pid
                matched.append(note)

        # Deterministic extraction over the matched notes only (mirror Gmail).
        graph = extract_notes_graph(
            matched,
            crm_domains=set(crm_names),
            crm_names=crm_names,
            name_to_domain=build_company_index(crm_names),
            own_domains=fetched.own_domains,
            name_by_email=name_by_email,
        )
        # Record attendees/owners dropped for lacking a name (debug log).
        await log_rejections(http, notes=graph.rejections)

        # Phase B: write entities, then edges. Event entities are never created by
        # notes — they resolve to the matched calendar meeting.
        id_by_key: dict[str, str] = {}
        for ent in graph.entities:
            if ent.type == "event":
                pid = attach_to.get(ent.canonical_key)
                if pid:
                    id_by_key[ent.canonical_key] = pid
                continue
            idx = len(results) + len(errors)
            try:
                resp = await client.insert_pointer(
                    label=ent.label,
                    type=ent.type,
                    canonical_key=ent.canonical_key,
                    metadata=ent.metadata or None,
                    occurred_at=ent.occurred_at,
                    access_class=firm_class_key,
                    attributes=ent.attributes or None,
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
                    payload={"source": "notes"},
                    principals=[firm.tenant_id],  # tenant-scope the comm-graph edge
                )
            except (EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(len(results) + len(errors), exc))

        # Phase C: each matched note's content fields (notes, notion_summary) become
        # SEPARATE documents linked to the calendar event; firm-wide unless
        # Confidential → private class + participant grants.
        for note in matched:
            idx = len(results) + len(errors)
            try:
                await _ingest_note_documents(http, client, note, firm_class_key, user_ids, id_by_key)
            except (AdapterError, EdgeFunctionError, EdgeFunctionTimeout, ValidationError) as exc:
                errors.append(_error_from_exc(idx, exc))

        # Advance the cursor past ALL fetched notes (dropped/unmatched included) so
        # they aren't reprocessed — calendar runs first, so an unmatched note means
        # there is genuinely no meeting for it.
        if body.since_last:
            max_edited = _max_iso(since, None)
            for note in notes:
                max_edited = _max_iso(max_edited, note.last_edited)
            if max_edited:
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


async def _ingest_note_documents(
    http,
    client: EdgeFunctionClient,
    note: MeetingNote,
    firm_class_key: str,
    user_ids: dict[str, str],
    id_by_key: dict[str, str],
) -> None:
    """Ingest each of a meeting's content fields (e.g. `notes`, `notion_summary`)
    as its OWN document linked `content_of` to the calendar event. Firm-wide
    (acl = [tenant]) unless Confidential → acl = the owner + attendees who have
    platform accounts (their uids), so only they can read it."""
    tenant = note.tenant_id
    start = note.occurred_at or note.last_edited
    event_id = id_by_key.get(notes_event_key(tenant, note))
    if not event_id:
        return  # matched notes always resolve to a calendar event; defensive

    body_access_class: str | None = None
    principals: list[str] | None = None
    if note.confidential:
        grant_emails = set(note.attendees)
        if note.owner_email:
            grant_emails.add(note.owner_email)
        principals = [uid for uid in (user_ids.get(e) for e in grant_emails) if uid]
    else:
        body_access_class = firm_class_key  # firm:{tenant} → acl [tenant]

    for field_name, content in note.documents:
        await client.ingest_document(
            title=note.title,
            content=content,
            occurred_at=start,
            metadata={"page_id": note.page_id, "confidential": note.confidential,
                      "field": field_name},
            access_class=body_access_class,
            principals=principals,
            canonical_key_namespace=tenant,
            link={
                "target_id": event_id,
                "relationship_type": "content_of",
                "why": f"Meeting {field_name}",
            },
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
        {"key": k, "value": v, "data_type": dt, "source": "afinidad"}
        for (k, v, dt) in attrs
    ]


async def _ingest_crm_entity(
    client: EdgeFunctionClient, ent: CrmEntity, *,
    access_class: str | None = None, principals: list[str] | None = None,
) -> dict:
    """One entity → a pointer (+ attributes). Company/opportunity carry a firm
    `access_class` (→ acl=[tenant]); a (global) person carries explicit
    `principals` (the union of firms that reference it)."""
    return await client.insert_pointer(
        label=ent.label,
        type=ent.kind,
        canonical_key=ent.canonical_key,
        metadata=ent.metadata,
        access_class=access_class,
        principals=principals,
        attributes=_attr_dicts(ent.attributes) or None,
    )


async def _ingest_crm_edge(
    client: EdgeFunctionClient, edge: CrmEdge, resolve, principals: list[str] | None = None,
) -> dict | None:
    """One entity_edges row → a graph edge, once both endpoints resolve to pointers.
    `principals` = the firms that may see the edge (union of its endpoints' firms)."""
    src = await resolve(edge.source_id)
    tgt = await resolve(edge.target_id)
    if not src or not tgt:
        return None
    return await client.link_pointers(
        source_id=src,
        target_id=tgt,
        relationship_type=edge.relation,
        why=f"{edge.relation} (from Afinidad CRM)",
        payload=edge.metadata or None,
        principals=principals,
    )


async def _apply_deal_attributes(
    client: EdgeFunctionClient,
    deal: CrmDeal,
    entity_by_id: dict[str, CrmEntity],
    principals: list[str],
) -> dict | None:
    """A list membership → per-list namespaced attributes upserted on the company
    *or opportunity* pointer (re-inserting by canonical_key returns the existing
    pointer + upserts attributes_kv). `principals` = the entity's firm acl
    (involvement-derived for companies, Nzyme for opportunities) so the attribute
    rows inherit the same visibility as the pointer."""
    ent = entity_by_id.get(deal.entity_id)
    if ent is None or not deal.attributes:
        return None
    return await client.insert_pointer(
        label=ent.label,
        type=ent.kind,
        canonical_key=ent.canonical_key,
        principals=principals,
        attributes=_attr_dicts(deal.attributes),
    )


def derive_company_firms(
    entities: list[CrmEntity], edges: list[CrmEdge], deals: list[CrmDeal], firm: AffinidadFirm,
) -> dict[str, set[str]]:
    """Per-company firm set (acl), involvement-derived instead of fixed to Kibo by
    kind. A company belongs to a firm when it is in that firm's dealflow list, an
    opportunity of that firm references it (entity_edges, e.g. `contains`), or one
    of that firm's people is affiliated with it. Empty set ⇒ caller defaults to the
    firm (Kibo). Uses people's own list membership (`resolve_tenants`), never their
    derived acl, so it does not depend on person-acl (no cycle)."""
    entity_by_id = {e.entity_id: e for e in entities}
    company_firms: dict[str, set[str]] = {e.entity_id: set() for e in entities if e.kind == "company"}
    for d in deals:
        if d.entity_id in company_firms:
            company_firms[d.entity_id].add(list_tenant(firm, d.list_name))
    for edge in edges:
        s = entity_by_id.get(edge.source_id)
        t = entity_by_id.get(edge.target_id)
        if not s or not t:
            continue
        for me, other in ((s, t), (t, s)):
            if me.kind != "company" or me.entity_id not in company_firms:
                continue
            if other.kind == "opportunity":
                company_firms[me.entity_id].update(other.acl_firms or [other.tenant_id])
            elif other.kind == "person":
                company_firms[me.entity_id].update(resolve_tenants(other.email or ""))
    return company_firms


async def _ingest_crm_note(
    http,
    client: EdgeFunctionClient,
    note: CrmNote,
    firm_class_key: str,
    user_ids: dict[str, str],
    resolve_link,
) -> dict:
    """One note → a document, firm-wide unless private (then a per-note class
    ensured + granted to the author BEFORE ingest), plus content_of edges to each
    linked entity that resolves to a pointer."""
    body_access_class: str | None = None
    principals: list[str] | None = None
    if note.private:
        # acl = the author (if they have an account), else nobody (fail-closed).
        uid = user_ids.get(note.author_email) if note.author_email else None
        principals = [uid] if uid else []
    else:
        body_access_class = firm_class_key

    doc = await client.ingest_document(
        title=note.label,
        content=note.body,
        occurred_at=note.occurred_at,
        metadata={
            "source": "afinidad",
            "note_id": note.note_id,
            "visibility": "private" if note.private else "org",
        },
        access_class=body_access_class,
        principals=principals,
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
                    relationship_type="content_of",
                    why="Note about this entity",
                )
    return doc


async def _ingest_crm_event(
    http,
    client: EdgeFunctionClient,
    ev: CrmEvent,
    firm_tenants: set[str],
    user_ids: dict[str, str],
    resolve,
    entity_by_id: dict[str, CrmEntity],
    default_tenant: str,
) -> dict:
    """One meeting → a `communication` node (the fact: who/when), `attended` edges
    from each participant (role + RSVP on the edge payload), and — if there's body
    text — a participant-only document. `firm_tenants` = the firms whose people
    attended; the node's acl is that set, keyed under a deterministic primary."""
    tenant_acl = sorted(firm_tenants) or [default_tenant]
    primary = default_tenant if default_tenant in firm_tenants else tenant_acl[0]
    pointer = await client.insert_pointer(
        label=ev.label,
        type="communication",
        canonical_key=communication_key(primary, ev.event_id),
        metadata=ev.metadata,
        occurred_at=ev.occurred_at,
        principals=tenant_acl,
    )
    comm_id = pointer.get("pointer_id")

    for (entity_type, entity_id, role, response_status) in ev.participants:
        pid = await resolve(entity_id)
        if pid and comm_id:
            payload = {"role": role}
            if response_status:
                payload["response_status"] = response_status
            await client.link_pointers(
                source_id=pid,
                target_id=comm_id,
                relationship_type="attended",
                why=f"attended this {ev.type}",
                payload=payload,
                principals=tenant_acl,
            )

    if ev.body:
        # acl = the participants who have accounts (fail-closed if none).
        body_principals = []
        for (_etype, entity_id, _role, _resp) in ev.participants:
            ent = entity_by_id.get(entity_id)
            email = getattr(ent, "email", None) if ent else None
            uid = user_ids.get(email) if email else None
            if uid:
                body_principals.append(uid)
        link = (
            {"target_id": comm_id, "relationship_type": "content_of",
             "why": f"Body of this {ev.type}"}
            if comm_id else None
        )
        content = f"{ev.subject}\n\n{ev.body}" if ev.subject else ev.body
        await client.ingest_document(
            title=ev.subject or ev.label,
            content=content,
            occurred_at=ev.occurred_at,
            metadata={"source": "afinidad", "event_id": ev.event_id, "event_type": ev.type},
            principals=body_principals,
            canonical_key_namespace=primary,
            link=link,
        )
    return pointer


@router.post("/affinidad", response_model=IngestResponse)
async def ingest_affinidad(body: AffinidadRequest, request: Request) -> IngestResponse:
    """One-time historical backfill of Kibo's in-house CRM ("Affinidad") into the
    graph. Per firm (tenant): companies/people → pointers, entity_edges → edges,
    list memberships → namespaced company attributes ("deals"), notes → documents
    (org or author-private), and CRM-only interactions → communication pointers +
    participant edges with a participant-only body document. **Meetings and emails
    are NOT ingested** (Calendar owns meetings, Gmail owns emails) — `fetch_events`
    filters `type NOT IN ('meeting','email')` so the CRM connector only pulls
    call/message/other interactions and never duplicates calendar/gmail comms.
    Idempotent (canonical-key dedup). Order is entities → edges → deals → notes →
    events so endpoints exist before linking. `objects` restricts a run to specific
    types."""
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
        # firm:{tenant} → acl=[tenant] at the write boundary; no class/grant rows.

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
            if entity_type in ("event", "meeting"):
                # The note links to a meeting → its communication node (keyed under
                # the Kibo-preferred primary tenant, which matches most meetings).
                key = f"comm:{entity_id}"
                if key not in pid_cache:
                    pid_cache[key] = await resolve_pointer_id(
                        http, communication_key(firm.tenant_id, entity_id)
                    )
                return pid_cache[key]
            return None

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

        # Edges + meetings up front: needed to union each (global) person's acl
        # from the firms of the companies/opportunities they're tied to and the
        # meetings they attend.
        try:
            edges = await adapter.fetch_edges(firm)
        except _INGEST_ERRORS as exc:
            edges = []
            _fail(exc)
        try:
            events = await adapter.fetch_events(firm, max_results=body.max_results)
        except _INGEST_ERRORS as exc:
            events = []
            _fail(exc)
        # Deals (list memberships) are needed up front too: a company's firm(s) are
        # derived from its dealflow-list membership, not just its kind.
        try:
            deals = await adapter.fetch_deals(firm)
        except _INGEST_ERRORS as exc:
            deals = []
            _fail(exc)

        def _meeting_firms(ev: CrmEvent) -> set[str]:
            fs: set[str] = set()
            for (_et, pid, _role, _resp) in ev.participants:
                ent = entity_by_id.get(pid)
                for t in resolve_tenants(getattr(ent, "email", None) or ""):
                    fs.add(t)
            return fs or {firm.tenant_id}
        ev_firms = {ev.event_id: _meeting_firms(ev) for ev in events}

        # Per-company firm set (acl): involvement-derived (see derive_company_firms),
        # computed before persons and independent of person-acl (no cycle).
        company_firms = derive_company_firms(entities, edges, deals, firm)

        def _company_acl(eid: str) -> list[str]:
            return sorted(company_firms.get(eid) or {firm.tenant_id})

        # Per-person tenant set (acl): own firm (if internal) ∪ firms of the
        # companies/opportunities they're edged to ∪ firms of meetings they attend.
        person_tenants: dict[str, set[str]] = {}
        def _add_pt(eid: str, tenants) -> None:
            if tenants:
                person_tenants.setdefault(eid, set()).update(tenants)
        def _affiliated_firms(ent: CrmEntity) -> list[str]:
            if ent.kind == "company":
                return _company_acl(ent.entity_id)
            if ent.kind == "opportunity":
                return ent.acl_firms or [ent.tenant_id]
            return [ent.tenant_id]
        for e in entities:
            if e.kind == "person":
                person_tenants.setdefault(e.entity_id, set())
                _add_pt(e.entity_id, resolve_tenants(e.email or ""))
        for edge in edges:
            s = entity_by_id.get(edge.source_id)
            t = entity_by_id.get(edge.target_id)
            if s and t:
                if s.kind == "person" and t.kind in ("company", "opportunity"):
                    _add_pt(s.entity_id, _affiliated_firms(t))
                if t.kind == "person" and s.kind in ("company", "opportunity"):
                    _add_pt(t.entity_id, _affiliated_firms(s))
        for ev in events:
            for (_et, pid, _role, _resp) in ev.participants:
                ent = entity_by_id.get(pid)
                if ent and ent.kind == "person":
                    _add_pt(pid, ev_firms[ev.event_id])

        def _person_acl(eid: str) -> list[str]:
            return sorted(person_tenants.get(eid) or {firm.tenant_id})

        def _edge_principals(edge: CrmEdge) -> list[str]:
            out: set[str] = set()
            for eid in (edge.source_id, edge.target_id):
                ent = entity_by_id.get(eid)
                if not ent:
                    continue
                if ent.kind == "person":
                    out.update(_person_acl(eid))
                elif ent.kind == "company":
                    out.update(_company_acl(eid))
                elif ent.kind == "opportunity":
                    out.update(ent.acl_firms or [ent.tenant_id])
                else:
                    out.add(ent.tenant_id)
            return sorted(out or {firm.tenant_id})

        def _entity_principals(ent: CrmEntity) -> list[str]:
            # company → involvement-derived; opportunity → its list-derived firm(s).
            if ent.kind == "company":
                return _company_acl(ent.entity_id)
            if ent.kind == "opportunity":
                return ent.acl_firms or [ent.tenant_id]
            return [ent.tenant_id]

        async def _do_company_opp(ent):
            resp = await _ingest_crm_entity(client, ent, principals=_entity_principals(ent))
            pid = resp.get("pointer_id")
            if pid:
                ptr_by_entity[ent.entity_id] = pid
            return resp

        async def _do_person(ent):
            resp = await _ingest_crm_entity(client, ent, principals=_person_acl(ent.entity_id))
            pid = resp.get("pointer_id")
            if pid:
                ptr_by_entity[ent.entity_id] = pid
            return resp

        if "entities" in objects:
            await _run([e for e in entities if e.kind in ("company", "opportunity")], _do_company_opp)
            await _run([e for e in entities if e.kind == "person"], _do_person)

        if "edges" in objects:
            await _run(edges, lambda edge: _ingest_crm_edge(client, edge, resolve, _edge_principals(edge)))

        if "deals" in objects:
            def _deal_principals(deal: CrmDeal) -> list[str]:
                ent = entity_by_id.get(deal.entity_id)
                return _entity_principals(ent) if ent else [firm.tenant_id]
            await _run(
                deals,
                lambda deal: _apply_deal_attributes(
                    client, deal, entity_by_id, _deal_principals(deal)
                ),
            )
            # Exit-capture: stage *changes* historize automatically (they arrive as
            # attribute upserts), but a list *exit* leaves an orphaned attribute and
            # fires no DELETE. Close those intervals here. Only entities resolved from
            # this run's source are candidates, so a partial run never fabricates an exit.
            managed: dict[str, set[str]] = {}
            for ent in entities:
                if ent.kind not in ("company", "opportunity"):
                    continue
                pid = await resolve(ent.entity_id)
                if pid:
                    managed.setdefault(pid, set())
            for deal in deals:
                pid = await resolve(deal.entity_id)
                if not pid or pid not in managed:
                    continue
                for (k, _v, _dt) in deal.attributes:
                    if k.endswith(":Stage"):
                        managed[pid].add(k)
            try:
                await crm_sync.reconcile_list_memberships(
                    http, tenant_id=firm.tenant_id, managed_keys_by_pointer=managed
                )
            except _INGEST_ERRORS as exc:
                _fail(exc)

        if "notes" in objects:
            try:
                notes = await adapter.fetch_notes(firm)
            except _INGEST_ERRORS as exc:
                notes = []
                _fail(exc)
            await _run(
                notes,
                lambda note: _ingest_crm_note(
                    http, client, note, f"firm:{firm.tenant_id}", user_ids, resolve_link
                ),
            )

        if "events" in objects:
            await _run(
                events,
                lambda ev: _ingest_crm_event(
                    http, client, ev, ev_firms[ev.event_id], user_ids,
                    resolve, entity_by_id, firm.tenant_id,
                ),
            )

    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="afinidad",
        items_produced=produced,
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )
