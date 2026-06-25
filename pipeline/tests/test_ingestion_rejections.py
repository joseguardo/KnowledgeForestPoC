from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline.adapters.email_entities import NoteRejection
from pipeline.adapters.gmail import EmailRejection
from pipeline.config import settings
from pipeline.ingestion_rejections import _email_row, _note_row, log_rejections


def _email_rej(**kw) -> EmailRejection:
    base = dict(
        tenant_id="T1", mailbox="me@acme.com", message_id="<m@x>", thread_id="TH",
        subject="Big Sale", sender="info@x.com", sender_name="Brand",
        occurred_at="2026-06-01T10:00:00+00:00", reason="role_mailbox_sender",
    )
    base.update(kw)
    return EmailRejection(**base)


def _note_rej(**kw) -> NoteRejection:
    base = dict(
        tenant_id="T1", page_id="pg-1", title="Sync", attendee="x@y.com",
        reason="unnamed_attendee", occurred_at="2026-06-01T10:00:00+00:00",
    )
    base.update(kw)
    return NoteRejection(**base)


def test_email_row_shape_and_dedup_key():
    row = _email_row(_email_rej())
    assert row["source"] == "gmail"
    assert row["dedup_key"] == "<m@x>"        # gmail = message_id
    assert row["ref_id"] == "<m@x>"
    assert row["subject"] == "Big Sale"
    assert row["sender"] == "info@x.com"
    assert row["mailbox"] == "me@acme.com"


def test_note_row_shape_and_dedup_key():
    row = _note_row(_note_rej())
    assert row["source"] == "notes"
    assert row["dedup_key"] == "pg-1:x@y.com"  # notes = page_id:email
    assert row["ref_id"] == "pg-1"
    assert row["subject"] == "Sync"
    assert row["sender"] == "x@y.com"
    assert row["mailbox"] is None and row["thread_id"] is None


def _http_ok() -> AsyncMock:
    """An async http client whose POST returns a response with a *sync*
    raise_for_status (matching httpx), avoiding stray-coroutine warnings."""
    http = AsyncMock()
    http.post.return_value = MagicMock()  # resp; raise_for_status is sync
    return http


@pytest.mark.asyncio
async def test_log_rejections_upserts_both_sources():
    http = _http_ok()
    n = await log_rejections(http, email=[_email_rej()], notes=[_note_rej()])
    assert n == 2
    http.post.assert_awaited_once()
    _, kwargs = http.post.call_args
    # Upsert on the composite unique key.
    assert kwargs["params"]["on_conflict"] == "tenant_id,source,dedup_key"
    assert kwargs["headers"]["Prefer"] == "resolution=merge-duplicates"
    assert {r["source"] for r in kwargs["json"]} == {"gmail", "notes"}


@pytest.mark.asyncio
async def test_log_rejections_noop_when_empty():
    http = AsyncMock()
    assert await log_rejections(http, email=[], notes=[]) == 0
    http.post.assert_not_called()


@pytest.mark.asyncio
async def test_log_rejections_respects_toggle(monkeypatch):
    monkeypatch.setattr(settings, "log_ingestion_rejections", False)
    http = AsyncMock()
    assert await log_rejections(http, email=[_email_rej()]) == 0
    http.post.assert_not_called()


@pytest.mark.asyncio
async def test_log_rejections_swallows_http_errors(monkeypatch):
    import httpx

    http = AsyncMock()
    http.post.side_effect = httpx.ConnectError("boom")
    # Must not raise — rejection logging is best-effort, never fatal to ingestion.
    assert await log_rejections(http, email=[_email_rej()]) == 0
