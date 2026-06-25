from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from pipeline.config import settings

if TYPE_CHECKING:
    from pipeline.adapters.email_entities import NoteRejection
    from pipeline.adapters.gmail import EmailRejection

# Append/upsert the ingestion rejection log: inputs the pipeline deterministically
# dropped before the graph (Gmail noise, Notes unnamed attendees/owners). Reached
# via PostgREST with the service-role key (bypasses RLS) — an ops/debug table, so
# writes here are best-effort: a failure is logged, never fatal to ingestion.

log = logging.getLogger(__name__)


def _table_url() -> str:
    return f"{settings.supabase_url}/rest/v1/ingestion_rejections"


def _headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _email_row(r: EmailRejection) -> dict[str, Any]:
    return {
        "tenant_id": r.tenant_id,
        "source": "gmail",
        "reason": r.reason,
        "subject": r.subject or None,
        "sender": r.sender or None,
        "sender_name": r.sender_name,
        "mailbox": r.mailbox or None,
        "ref_id": r.message_id or None,
        "thread_id": r.thread_id or None,
        "dedup_key": r.message_id,
        "occurred_at": r.occurred_at,
    }


def _note_row(r: NoteRejection) -> dict[str, Any]:
    return {
        "tenant_id": r.tenant_id,
        "source": "notes",
        "reason": r.reason,
        "subject": r.title or None,
        "sender": r.attendee or None,
        "sender_name": None,
        "mailbox": None,
        "ref_id": r.page_id or None,
        "thread_id": None,
        "dedup_key": f"{r.page_id}:{r.attendee}",
        "occurred_at": r.occurred_at,
    }


async def log_rejections(
    http: httpx.AsyncClient,
    *,
    email: list[EmailRejection] | None = None,
    notes: list[NoteRejection] | None = None,
) -> int:
    """Upsert rejection rows for this run. Keyed by (tenant_id, source, dedup_key)
    so re-seeing the same drop (cursor overlap / re-backfill) updates rather than
    duplicates. No-op when the `log_ingestion_rejections` toggle is off or there
    is nothing to write. Best-effort: returns the number of rows sent, or 0 on
    error (logged, not raised)."""
    if not settings.log_ingestion_rejections:
        return 0
    rows = [_email_row(r) for r in (email or [])] + [_note_row(r) for r in (notes or [])]
    if not rows:
        return 0
    try:
        resp = await http.post(
            _table_url(),
            headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
            params={"on_conflict": "tenant_id,source,dedup_key"},
            json=rows,
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("ingestion_rejections write failed (%d rows): %s", len(rows), exc)
        return 0
    return len(rows)
