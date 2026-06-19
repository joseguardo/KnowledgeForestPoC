import base64
import json
from email.message import EmailMessage
from unittest.mock import AsyncMock

import httpx
import pytest

from pipeline.adapters import gmail as gmail_mod
from pipeline.adapters.gmail import (
    GmailAdapter,
    _clean_subject,
    _decode_sa_key,
    _event_label,
    _is_noise,
    _parse_message,
    _thread_root_id,
    load_firms,
)
from pipeline.config import settings
from pipeline.errors import ValidationError


def _raw(sender, to, subject, date, body, msgid, references=None, cc=None) -> str:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = date
    msg["Message-ID"] = msgid
    if references:
        msg["References"] = references
    if cc:
        msg["Cc"] = cc
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _sa_b64() -> str:
    return base64.b64encode(json.dumps({"type": "service_account"}).encode()).decode()


# ── pure helpers ────────────────────────────────────────────────────


def test_clean_subject_strips_reply_prefixes():
    assert _clean_subject("Re: Re: Deal terms") == "Deal terms"
    assert _clean_subject("Fwd: Intro") == "Intro"
    assert _clean_subject(None) == ""


def test_is_noise():
    assert _is_noise("noreply@stripe.com")
    assert _is_noise("no-reply@x.com")
    assert _is_noise("mailer-daemon@x.com")
    assert _is_noise("notifications@github.com")
    assert not _is_noise("alice@x.com")
    assert not _is_noise("bob.smith@firm.com")


def test_parse_message_reads_threading_headers():
    raw = _raw(
        "Alice <alice@x.com>", "Bob <bob@y.com>", "Hello",
        "Mon, 1 Jun 2026 10:00:00 +0000", "Body.", "<m2@y.com>",
        references="<root@x.com> <m1@x.com>",
    )
    parsed = _parse_message(base64.urlsafe_b64decode(raw))
    assert parsed["from"] == "Alice <alice@x.com>"
    assert parsed["message_id"] == "<m2@y.com>"
    assert parsed["references"] == ["<root@x.com>", "<m1@x.com>"]


def test_thread_root_id_prefers_references_root():
    msgs = [
        {"references": [], "message_id": "<root@x.com>"},
        {"references": ["<root@x.com>"], "message_id": "<reply@y.com>"},
    ]
    assert _thread_root_id(msgs) == "<root@x.com>"


def test_thread_root_id_falls_back_to_own_id():
    msgs = [{"references": [], "message_id": "<only@x.com>"}]
    assert _thread_root_id(msgs) == "<only@x.com>"


def test_event_label_excludes_noise_and_subject():
    by_role = {
        "from": [("alice@x.com", "Alice")],
        "to": [("bob@y.com", "Bob"), ("noreply@stripe.com", "")],
        "cc": [],
    }
    label = _event_label(by_role)
    assert label == "Email: Alice -> Bob"
    assert "noreply" not in label


# ── firm config ─────────────────────────────────────────────────────


def test_decode_sa_key_rejects_bad_base64():
    with pytest.raises(ValidationError, match="not valid base64"):
        _decode_sa_key("not-valid!!")


def test_load_firms_parses_and_filters(monkeypatch):
    cfg = [
        {"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": ["a@one.com"]},
        {"tenant_id": "T2", "sa_key_b64": _sa_b64(), "mailboxes": ["b@two.com", "c@two.com"]},
    ]
    monkeypatch.setattr(settings, "gmail_firms", json.dumps(cfg))
    firms = load_firms()
    assert {f.tenant_id for f in firms} == {"T1", "T2"}
    only = load_firms("T2")
    assert len(only) == 1 and only[0].mailboxes == ["b@two.com", "c@two.com"]


def test_load_firms_falls_back_to_global_b64(monkeypatch):
    """One shared SA: an entry without sa_key_b64 uses settings.gmail_sa_key_b64."""
    monkeypatch.setattr(settings, "gmail_sa_key_b64", _sa_b64())
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "mailboxes": ["a@one.com"]}]),
    )
    firms = load_firms()
    assert firms[0].sa_info == {"type": "service_account"}


def test_load_firms_falls_back_to_global_json(monkeypatch):
    """The shared SA can also come from GMAIL_SA_KEY_JSON (raw JSON)."""
    monkeypatch.setattr(settings, "gmail_sa_key_b64", None)
    monkeypatch.setattr(settings, "gmail_sa_key_json", '{"type": "service_account"}')
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "mailboxes": ["a@one.com"]}]),
    )
    firms = load_firms()
    assert firms[0].sa_info == {"type": "service_account"}


def test_load_firms_requires_some_sa_key(monkeypatch):
    monkeypatch.setattr(settings, "gmail_sa_key_b64", None)
    monkeypatch.setattr(settings, "gmail_sa_key_json", None)
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "mailboxes": ["a@one.com"]}]),
    )
    with pytest.raises(ValidationError, match="no SA key"):
        load_firms()


def test_load_firms_requires_config(monkeypatch):
    monkeypatch.setattr(settings, "gmail_firms", None)
    with pytest.raises(ValidationError, match="GMAIL_FIRMS"):
        load_firms()


def test_load_firms_rejects_entry_without_mailboxes(monkeypatch):
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": []}]),
    )
    with pytest.raises(ValidationError, match="no mailboxes"):
        load_firms()


# ── adapter: fetch_threads ──────────────────────────────────────────


@pytest.fixture
def _firm(monkeypatch):
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": ["me@acme.com"]}]),
    )

    async def fake_mint(sa_info, subject, scopes):
        return f"tok-{subject}"

    monkeypatch.setattr(gmail_mod, "_mint_token", fake_mint)
    return load_firms()[0]


def _thread_handler(messages: dict[str, str]):
    ids = list(messages.keys())

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/threads"):
            return httpx.Response(200, json={"threads": [{"id": "t1"}]})
        if path.endswith("/threads/t1"):
            return httpx.Response(200, json={"messages": [{"id": i} for i in ids]})
        for mid, raw in messages.items():
            if path.endswith(f"/messages/{mid}"):
                return httpx.Response(200, json={"raw": raw})
        return httpx.Response(404, json={})

    return handler


@pytest.mark.asyncio
async def test_fetch_threads_splits_public_and_private(_firm):
    r1 = _raw(
        "Alice <alice@x.com>", "me@acme.com, noreply@stripe.com", "Q3 secret terms",
        "Mon, 1 Jun 2026 10:00:00 +0000", "First.", "<root@x.com>",
    )
    r2 = _raw(
        "me@acme.com", "Alice <alice@x.com>", "Re: Q3 secret terms",
        "Mon, 1 Jun 2026 12:00:00 +0000", "Reply.", "<r2@acme.com>",
        references="<root@x.com>", cc="cc@acme.com",
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_thread_handler({"m1": r1, "m2": r2})))
    threads = await GmailAdapter().fetch_threads(_firm, "me@acme.com", http, query="newer_than:7d")
    await http.aclose()

    assert len(threads) == 1
    t = threads[0]
    assert t.tenant_id == "T1"
    # Stable cross-mailbox root from References chain.
    assert t.metadata["thread_root_id"] == "<root@x.com>"
    # Subject is private: absent from public label + metadata, present in body.
    assert "secret" not in t.event_label.lower()
    assert "secret" not in json.dumps(t.metadata).lower()
    assert "secret" in t.body.lower()
    # Real people become participants; noise is filtered out of entities…
    emails = {p.email for p in t.participants}
    assert {"alice@x.com", "me@acme.com", "cc@acme.com"} <= emails
    assert "noreply@stripe.com" not in emails
    # …but kept in the public who-contacted-whom metadata.
    assert "noreply@stripe.com" in t.metadata["participants"]["to"]
    # occurred_at = latest message.
    assert "12:00:00" in t.occurred_at


@pytest.mark.asyncio
async def test_thread_hash_stable_across_mailboxes(_firm):
    """Two mailboxes whose copies share a References root produce the same thread
    hash (so the event + private class are shared), despite different Gmail IDs."""
    a = _raw("X <x@x.com>", "a@acme.com", "Hi", "Mon, 1 Jun 2026 10:00:00 +0000",
             "Body.", "<root@x.com>")
    b_reply = _raw("a@acme.com", "X <x@x.com>", "Re: Hi", "Mon, 1 Jun 2026 11:00:00 +0000",
                   "Re.", "<b-only@acme.com>", references="<root@x.com>")

    http_a = httpx.AsyncClient(transport=httpx.MockTransport(_thread_handler({"m1": a})))
    http_b = httpx.AsyncClient(transport=httpx.MockTransport(_thread_handler({"m9": b_reply})))
    ta = await GmailAdapter().fetch_threads(_firm, "a@acme.com", http_a)
    tb = await GmailAdapter().fetch_threads(_firm, "b@acme.com", http_b)
    await http_a.aclose()
    await http_b.aclose()

    assert ta[0].thread_hash == tb[0].thread_hash


@pytest.mark.asyncio
async def test_fetch_threads_skips_noise_only_sender(_firm, monkeypatch):
    """A thread whose only sender is a no-reply/alert address is dropped (no human
    sender) — but kept when gmail_skip_noise_senders is off."""
    raw = _raw(
        "TTR Alerts <alerts@ttrdata.com>", "jose@kiboventures.com", "Market alert",
        "Mon, 1 Jun 2026 10:00:00 +0000", "Newsletter body.", "<n1@ttrdata.com>",
    )
    monkeypatch.setattr(settings, "gmail_skip_noise_senders", True)
    http = httpx.AsyncClient(transport=httpx.MockTransport(_thread_handler({"m1": raw})))
    assert await GmailAdapter().fetch_threads(_firm, "jose@kiboventures.com", http) == []
    await http.aclose()

    monkeypatch.setattr(settings, "gmail_skip_noise_senders", False)
    http2 = httpx.AsyncClient(transport=httpx.MockTransport(_thread_handler({"m1": raw})))
    kept = await GmailAdapter().fetch_threads(_firm, "jose@kiboventures.com", http2)
    await http2.aclose()
    assert len(kept) == 1


@pytest.mark.asyncio
async def test_fetch_threads_empty(_firm):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    threads = await GmailAdapter().fetch_threads(_firm, "me@acme.com", http)
    await http.aclose()
    assert threads == []


# ── endpoint orchestration: firm isolation + grant tiers ────────────


@pytest.mark.asyncio
async def test_ingest_gmail_endpoint_splits_tiers_and_namespaces(async_client, monkeypatch):
    """POST /gmail wires the firm-wide graph (firm:<tenant>, tenant-granted) and the
    private body (gmailthread:<tenant>:<hash>, user-granted) with tenant-namespaced
    canonical keys."""
    from pipeline.adapters.gmail import EmailThread, ThreadParticipant
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": ["me@acme.com"]}]),
    )

    thread = EmailThread(
        tenant_id="T1", mailbox="me@acme.com", gmail_thread_id="t1", thread_hash="HASH",
        participants=[
            ThreadParticipant("alice@x.com", "Alice", "from"),
            ThreadParticipant("me@acme.com", None, "to"),
        ],
        event_label="Email: Alice -> me", occurred_at="2026-06-01T12:00:00+00:00",
        metadata={"event_type": "email", "thread_root_id": "<root@x.com>"},
        body="Subject: secret\n\nBody.",
    )

    async def fake_fetch(self, firm, subject, http, query=None, max_results=None):
        return [thread]

    monkeypatch.setattr(GmailAdapter, "fetch_threads", fake_fetch)
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value={"me@acme.com": "user-uuid"}))
    ensure_class = AsyncMock(return_value="class-id")
    tenant_grant = AsyncMock()
    user_grant = AsyncMock()
    monkeypatch.setattr(ingest_mod, "ensure_class", ensure_class)
    monkeypatch.setattr(ingest_mod, "ensure_tenant_grant", tenant_grant)
    monkeypatch.setattr(ingest_mod, "ensure_user_grant", user_grant)

    client = AsyncMock()
    client.ingest_email.return_value = {"status": "created", "pointer_id": "event-1"}
    client.ingest_document.return_value = {"status": "created", "pointer_id": "doc-1"}
    app.state.client = client

    resp = await async_client.post("/api/v1/ingest/gmail", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["items_produced"] == 1

    # firm-wide class ensured + tenant-granted; private class ensured + user-granted.
    ensured_keys = {c.args[1] for c in ensure_class.call_args_list}
    assert "firm:T1" in ensured_keys
    assert "gmailthread:T1:HASH" in ensured_keys
    tenant_grant.assert_awaited()
    user_grant.assert_awaited()

    # Public communication graph under the firm class, tenant-namespaced keys.
    ekw = client.ingest_email.call_args.kwargs
    assert ekw["access_class"] == "firm:T1"
    assert ekw["event"]["canonical_key"] == "event:T1:gmailthread:HASH"
    assert all(p["canonical_key"].startswith("person::T1::") for p in ekw["participants"])

    # Private body under the per-thread class, namespaced, linked to the event.
    dkw = client.ingest_document.call_args.kwargs
    assert dkw["access_class"] == "gmailthread:T1:HASH"
    assert dkw["canonical_key_namespace"] == "T1"
    assert dkw["link"]["target_id"] == "event-1"
    assert "secret" in dkw["content"]


@pytest.mark.asyncio
async def test_ingest_gmail_manual_pull_defaults_lookback(async_client, monkeypatch):
    """A manual pull (no query, since_last false) is date-bounded to
    GMAIL_BACKFILL_DAYS; an explicit query still overrides it."""
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": ["me@acme.com"]}]),
    )
    monkeypatch.setattr(settings, "gmail_backfill_days", 7)

    captured: dict[str, str | None] = {}

    async def fake_fetch(self, firm, subject, http, query=None, max_results=None):
        captured["query"] = query
        return []

    monkeypatch.setattr(GmailAdapter, "fetch_threads", fake_fetch)
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value={}))
    monkeypatch.setattr(ingest_mod, "ensure_class", AsyncMock(return_value="class-id"))
    monkeypatch.setattr(ingest_mod, "ensure_tenant_grant", AsyncMock())
    monkeypatch.setattr(ingest_mod, "ensure_user_grant", AsyncMock())
    app.state.client = AsyncMock()

    # No query → defaults to the lookback window.
    resp = await async_client.post("/api/v1/ingest/gmail", json={})
    assert resp.status_code == 200, resp.text
    assert captured["query"] == "newer_than:7d"

    # Explicit query wins.
    resp = await async_client.post("/api/v1/ingest/gmail", json={"query": "newer_than:2d"})
    assert resp.status_code == 200, resp.text
    assert captured["query"] == "newer_than:2d"
