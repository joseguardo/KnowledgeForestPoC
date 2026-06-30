import base64
import json
from email.message import EmailMessage
from unittest.mock import AsyncMock

import httpx
import pytest

from pipeline.adapters import gmail as gmail_mod
from pipeline.adapters.gmail import (
    GmailAdapter,
    MessageFetch,
    _decode_sa_key,
    _is_noise,
    _list_thread_ids,
    _parse_message,
    _thread_root_id,
    _truncate_utf16,
    _utf16_len,
    discover_mailboxes,
    load_firms,
)
from pipeline.config import settings
from pipeline.errors import ValidationError


def _raw(sender, to, subject, date, body, msgid, references=None, cc=None,
         extra_headers=None) -> str:
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
    for k, v in (extra_headers or {}).items():
        msg[k] = v
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _sa_b64() -> str:
    return base64.b64encode(json.dumps({"type": "service_account"}).encode()).decode()


# ── pure helpers ────────────────────────────────────────────────────


def test_utf16_len_counts_astral_as_two():
    assert _utf16_len("abc") == 3
    # An emoji is one Python code point but two UTF-16 code units.
    assert _utf16_len("😀") == 2
    assert _utf16_len("a😀b") == 4


def test_truncate_utf16_respects_edge_budget():
    # An all-emoji string: 10 code points = 20 UTF-16 units. Cap at 500000 is
    # what the edge function (JS String.length) enforces.
    body = "😀" * 400_000  # 800,000 UTF-16 units, well over the 500k edge cap
    out = _truncate_utf16(body, 500_000)
    assert _utf16_len(out) <= 500_000
    # No dangling surrogate: it must round-trip cleanly (truncation cut between
    # whole emoji, not through a surrogate pair).
    out.encode("utf-16-le").decode("utf-16-le")
    # BMP-only text truncates exactly to the code-unit budget.
    assert _truncate_utf16("X" * 1000, 500) == "X" * 500


def test_is_noise():
    assert _is_noise("noreply@stripe.com")
    assert _is_noise("no-reply@x.com")
    assert _is_noise("mailer-daemon@x.com")
    assert _is_noise("notifications@github.com")
    # 'noreply' anywhere in the local part (not just the start) counts.
    assert _is_noise("comments-noreply@docs.google.com")
    assert not _is_noise("alice@x.com")
    assert not _is_noise("bob.smith@firm.com")
    assert not _is_noise("autumn@x.com")  # 'auto' substring must not false-positive


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


def test_load_firms_rejects_entry_without_mailboxes_or_domain(monkeypatch):
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": []}]),
    )
    with pytest.raises(ValidationError, match="no mailboxes and no domain"):
        load_firms()


def test_load_firms_accepts_domain_entry(monkeypatch):
    """A firm may declare a domain (auto-discovery) instead of an explicit list."""
    monkeypatch.setattr(settings, "gmail_admin_subject", None)
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([
            {"tenant_id": "T1", "sa_key_b64": _sa_b64(),
             "domain": "acme.com", "admin_subject": "admin@acme.com"},
        ]),
    )
    firm = load_firms()[0]
    assert firm.domain == "acme.com"
    assert firm.admin_subject == "admin@acme.com"
    assert firm.mailboxes == []


def test_load_firms_domain_admin_subject_falls_back_to_global(monkeypatch):
    monkeypatch.setattr(settings, "gmail_admin_subject", "admin@global.com")
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "domain": "acme.com"}]),
    )
    assert load_firms()[0].admin_subject == "admin@global.com"


def test_load_firms_domain_without_admin_subject_rejected(monkeypatch):
    monkeypatch.setattr(settings, "gmail_admin_subject", None)
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "domain": "acme.com"}]),
    )
    with pytest.raises(ValidationError, match="no admin_subject"):
        load_firms()


# ── adapter: discover_mailboxes (Directory API) ─────────────────────


def _domain_firm(monkeypatch, exclude_admin_subject=False):
    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(),
                     "domain": "acme.com", "admin_subject": "admin@acme.com"}]),
    )

    async def fake_mint(sa_info, subject, scopes):
        return f"tok-{subject}"

    monkeypatch.setattr(gmail_mod, "_mint_token", fake_mint)
    monkeypatch.setattr(settings, "gmail_directory_query", None)
    return load_firms()[0]


def _directory_handler(pages: list[dict]):
    """Serve users.list pages in order, keyed by the request's pageToken."""
    by_token = {p.get("_token"): p for p in pages}

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/users"):
            return httpx.Response(404, json={})
        token = request.url.params.get("pageToken")
        page = by_token.get(token, {})
        return httpx.Response(200, json={
            "users": page.get("users", []),
            **({"nextPageToken": page["next"]} if page.get("next") else {}),
        })

    return handler


@pytest.mark.asyncio
async def test_discover_mailboxes_filters_and_excludes(monkeypatch):
    firm = _domain_firm(monkeypatch)
    page = {
        "_token": None,
        "users": [
            {"primaryEmail": "alice@acme.com"},
            {"primaryEmail": "bob@acme.com", "suspended": True},
            {"primaryEmail": "carol@acme.com", "archived": True},
            {"primaryEmail": "dave@acme.com"},
            {"primaryEmail": "nzyme@acme.com"},  # claimed by another firm
        ],
    }
    http = httpx.AsyncClient(transport=httpx.MockTransport(_directory_handler([page])))
    result = await discover_mailboxes(firm, http, exclude={"NZYME@acme.com"})
    await http.aclose()
    # suspended/archived dropped, excluded (case-insensitive) dropped, sorted.
    assert result == ["alice@acme.com", "dave@acme.com"]


@pytest.mark.asyncio
async def test_discover_mailboxes_paginates(monkeypatch):
    firm = _domain_firm(monkeypatch)
    pages = [
        {"_token": None, "users": [{"primaryEmail": "a@acme.com"}], "next": "p2"},
        {"_token": "p2", "users": [{"primaryEmail": "b@acme.com"}]},
    ]
    http = httpx.AsyncClient(transport=httpx.MockTransport(_directory_handler(pages)))
    result = await discover_mailboxes(firm, http)
    await http.aclose()
    assert result == ["a@acme.com", "b@acme.com"]



def _threads_list_handler(pages: list[dict]):
    """Serve threads.list pages in order, keyed by the request's pageToken.

    Records the requested maxResults per call so the test can assert the
    per-page size stays within Gmail's 500 limit.
    """
    by_token = {p.get("_token"): p for p in pages}
    requested_max: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/threads"):
            return httpx.Response(404, json={})
        requested_max.append(int(request.url.params["maxResults"]))
        token = request.url.params.get("pageToken")
        page = by_token.get(token, {})
        return httpx.Response(200, json={
            "threads": [{"id": i} for i in page.get("ids", [])],
            **({"nextPageToken": page["next"]} if page.get("next") else {}),
        })

    return handler, requested_max


@pytest.mark.asyncio
async def test_list_thread_ids_paginates_until_no_token():
    handler, requested_max = _threads_list_handler([
        {"_token": None, "ids": ["t1", "t2"], "next": "p2"},
        {"_token": "p2", "ids": ["t3"]},
    ])
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ids = await _list_thread_ids(http, {}, query="newer_than:7d", max_results=2000)
    await http.aclose()
    # Both pages collected; per-page size never exceeds Gmail's 500 cap.
    assert ids == ["t1", "t2", "t3"]
    assert all(m <= 500 for m in requested_max)


@pytest.mark.asyncio
async def test_list_thread_ids_respects_total_cap():
    """max_results caps the total across pages and stops paging once reached."""
    handler, requested_max = _threads_list_handler([
        {"_token": None, "ids": ["t1", "t2"], "next": "p2"},
        {"_token": "p2", "ids": ["t3", "t4"]},
    ])
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ids = await _list_thread_ids(http, {}, query=None, max_results=3)
    await http.aclose()
    assert ids == ["t1", "t2", "t3"]


@pytest.mark.asyncio
async def test_list_thread_ids_page_guard(monkeypatch):
    """gmail_max_pages bounds the loop even when pages keep offering a token."""
    monkeypatch.setattr(settings, "gmail_max_pages", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"threads": [{"id": "t"}], "nextPageToken": "more"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ids = await _list_thread_ids(http, {}, query=None, max_results=10_000)
    await http.aclose()
    assert len(ids) == 2  # two pages, then the guard stops it


# ── endpoint orchestration: firm isolation + grant tiers ────────────



@pytest.mark.asyncio
async def test_ingest_gmail_messages_builds_per_message_entities(async_client, monkeypatch):
    """POST /gmail/messages (step-1 path): one event per message; humans → person,
    role mailboxes/CRM domains → company; edges sent/to/affiliated_with; everything
    under the firm class. Uses the real extract_graph; only I/O is mocked."""
    from pipeline.adapters.gmail import EmailMessage
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": ["me@kiboventures.com"]}]),
    )

    msgs = [
        EmailMessage(
            tenant_id="T1", mailbox="me@kiboventures.com", message_id="<a@x>", thread_id="TH",
            occurred_at="2026-06-01T10:00:00+00:00", sender=("me@kiboventures.com", "Me"),
            to=[("ana@gohub.vc", "Ana")], cc=[("info@gohub.vc", "GoHub Info")],
            subject="Q3 secret terms", body="Body.",
        ),
    ]

    async def fake_fetch(self, firm, subject, http, query=None, max_results=None):
        return MessageFetch(messages=msgs)

    monkeypatch.setattr(GmailAdapter, "fetch_messages", fake_fetch)
    # CRM knows gohub.vc with a real name.
    monkeypatch.setattr(
        ingest_mod, "_load_company_domains",
        AsyncMock(return_value={"gohub.vc": "GoHub Ventures"}),
    )
    # Only the internal colleague resolves to a platform user.
    monkeypatch.setattr(
        ingest_mod, "resolve_user_ids",
        AsyncMock(return_value={"me@kiboventures.com": "uid-me"}),
    )
    add_members = AsyncMock()

    # pointer_id == canonical_key, so edge source/target are the keys themselves.
    async def fake_insert(**kw):
        return {"status": "created", "pointer_id": kw["canonical_key"]}

    client = AsyncMock()
    client.insert_pointer = AsyncMock(side_effect=fake_insert)
    client.ingest_document = AsyncMock(return_value={"status": "created", "pointer_id": "doc-1"})
    app.state.client = client

    resp = await async_client.post("/api/v1/ingest/gmail", json={})
    assert resp.status_code == 200, resp.text

    inserted = {(c.kwargs["type"], c.kwargs["canonical_key"]): c.kwargs
                for c in client.insert_pointer.call_args_list}
    keys = {ck for _t, ck in inserted}
    # role mailbox info@ → company, not a person; CRM name used; ana is a person.
    assert ("company", "company::T1::gohub.vc") in inserted
    assert inserted[("company", "company::T1::gohub.vc")]["label"] == "GoHub Ventures"
    assert ("person", "person::ana@gohub.vc") in inserted
    assert ("person", "person::me@kiboventures.com") in inserted
    assert "person::info@gohub.vc" not in keys
    # exactly one event, subject-free, under the firm class.
    events = [ck for t, ck in inserted if t == "communication"]
    assert len(events) == 1
    assert "secret" not in inserted[("communication", events[0])]["label"].lower()
    assert all(c.kwargs["access_class"] == "firm:T1" for c in client.insert_pointer.call_args_list)

    links = {(c.kwargs["source_id"], c.kwargs["relationship_type"], c.kwargs["target_id"])
             for c in client.link_pointers.call_args_list}
    assert ("person::ana@gohub.vc", "affiliated_with", "company::T1::gohub.vc") in links
    assert ("person::me@kiboventures.com", "sent", events[0]) in links
    assert (events[0], "received", "person::ana@gohub.vc") in links
    # no to/cc/about edges — recipients are `received`, `about` is deferred
    assert not any(rel in ("to", "cc", "about") for _s, rel, _t in links)

    # Private body: one document whose acl = the thread participants with accounts
    # (here only the internal colleague), linked to the message, tenant-namespaced.
    dkw = client.ingest_document.call_args.kwargs
    assert set(dkw["principals"]) == {"uid-me"}  # external ana/info not platform users
    assert dkw.get("access_class") is None
    assert dkw["canonical_key_namespace"] == "T1"
    assert dkw["link"]["target_id"] == events[0]
    assert dkw["link"]["relationship_type"] == "content_of"
    assert "Body." in dkw["content"]
    assert dkw["metadata"]["thread_id"] == "TH"


@pytest.mark.asyncio
async def test_ingest_gmail_body_acl_includes_mailbox_owner(async_client, monkeypatch):
    """The body acl always includes the mailbox owner, even when they are not on the
    visible header (BCC'd, or an external↔external thread in their mailbox). Without
    that, such bodies would be readable by nobody."""
    from pipeline.adapters.gmail import EmailMessage
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": ["owner@kiboventures.com"]}]),
    )
    msgs = [
        EmailMessage(
            tenant_id="T1", mailbox="owner@kiboventures.com", message_id="<b@x>", thread_id="TH2",
            occurred_at="2026-06-01T10:00:00+00:00", sender=("ext1@ext.com", "Ext One"),
            to=[("ext2@ext.com", "Ext Two")], cc=[],
            subject="External thread", body="Body.",
        ),
    ]

    async def fake_fetch(self, firm, subject, http, query=None, max_results=None):
        return MessageFetch(messages=msgs)

    monkeypatch.setattr(GmailAdapter, "fetch_messages", fake_fetch)
    monkeypatch.setattr(ingest_mod, "_load_company_domains", AsyncMock(return_value={}))
    # Only the mailbox owner is a platform user; both header parties are external.
    monkeypatch.setattr(
        ingest_mod, "resolve_user_ids",
        AsyncMock(return_value={"owner@kiboventures.com": "uid-owner"}),
    )

    async def fake_insert(**kw):
        return {"status": "created", "pointer_id": kw["canonical_key"]}

    client = AsyncMock()
    client.insert_pointer = AsyncMock(side_effect=fake_insert)
    client.ingest_document = AsyncMock(return_value={"status": "created", "pointer_id": "doc-1"})
    app.state.client = client

    resp = await async_client.post("/api/v1/ingest/gmail", json={})
    assert resp.status_code == 200, resp.text
    dkw = client.ingest_document.call_args.kwargs
    # owner is on neither From/To/Cc, yet is granted because it is their mailbox.
    assert set(dkw["principals"]) == {"uid-owner"}


@pytest.mark.asyncio
async def test_ingest_gmail_messages_skips_body_when_message_merged(async_client, monkeypatch):
    """A message that already exists (insert returns `merged`) does not re-ingest
    its body — avoids re-embedding the second-mailbox copy / since_last overlap."""
    from pipeline.adapters.gmail import EmailMessage
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": ["me@kiboventures.com"]}]),
    )
    msgs = [EmailMessage(
        tenant_id="T1", mailbox="me@kiboventures.com", message_id="<a@x>", thread_id="TH",
        occurred_at="2026-06-01T10:00:00+00:00", sender=("me@kiboventures.com", "Me"),
        to=[("jose@kiboventures.com", "Jose")], cc=[], subject="Hi", body="Body.",
    )]

    async def fake_fetch(self, firm, subject, http, query=None, max_results=None):
        return MessageFetch(messages=msgs)

    monkeypatch.setattr(GmailAdapter, "fetch_messages", fake_fetch)
    monkeypatch.setattr(ingest_mod, "_load_company_domains", AsyncMock(return_value={}))
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value={}))
    add_members = AsyncMock()

    async def fake_insert(**kw):
        # the message node already exists → merged; entities otherwise created
        status = "merged" if kw["type"] == "communication" else "created"
        return {"status": status, "pointer_id": kw["canonical_key"]}

    client = AsyncMock()
    client.insert_pointer = AsyncMock(side_effect=fake_insert)
    client.ingest_document = AsyncMock()
    app.state.client = client

    resp = await async_client.post("/api/v1/ingest/gmail", json={})
    assert resp.status_code == 200, resp.text
    client.ingest_document.assert_not_called()
    add_members.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_gmail_ingests_and_links_attachments(async_client, monkeypatch):
    """A real document attachment → its own document node, participant-private
    (acl = thread members with accounts), linked to the message via `attachment`."""
    from pipeline.adapters.gmail import Attachment, EmailMessage
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(), "mailboxes": ["me@kiboventures.com"]}]),
    )
    msgs = [EmailMessage(
        tenant_id="T1", mailbox="me@kiboventures.com", message_id="<a@x>", thread_id="TH",
        occurred_at="2026-06-01T10:00:00+00:00", sender=("me@kiboventures.com", "Me"),
        to=[("jose@kiboventures.com", "Jose")], cc=[], subject="Deck", body="See attached.",
        attachments=[Attachment(filename="notes.txt", content_type="text/plain", data=b"Deal terms inside.")],
    )]

    async def fake_fetch(self, firm, subject, http, query=None, max_results=None):
        return MessageFetch(messages=msgs)

    monkeypatch.setattr(GmailAdapter, "fetch_messages", fake_fetch)
    monkeypatch.setattr(ingest_mod, "_load_company_domains", AsyncMock(return_value={}))
    monkeypatch.setattr(
        ingest_mod, "resolve_user_ids",
        AsyncMock(return_value={"me@kiboventures.com": "uid-me", "jose@kiboventures.com": "uid-jose"}),
    )

    async def fake_insert(**kw):
        return {"status": "created", "pointer_id": kw["canonical_key"]}

    client = AsyncMock()
    client.insert_pointer = AsyncMock(side_effect=fake_insert)
    client.ingest_document = AsyncMock(return_value={"status": "created", "pointer_id": "doc-1"})
    app.state.client = client

    resp = await async_client.post("/api/v1/ingest/gmail", json={})
    assert resp.status_code == 200, resp.text

    att = [c.kwargs for c in client.ingest_document.call_args_list
           if (c.kwargs.get("link") or {}).get("relationship_type") == "attachment"]
    assert len(att) == 1
    a = att[0]
    assert a["title"] == "notes.txt"
    assert "Deal terms inside." in a["content"]
    assert set(a["principals"]) == {"uid-me", "uid-jose"}
    assert a["canonical_key_namespace"] == "T1"
    assert a["link"]["target_id"].startswith("message:T1:gmail:")
    assert a["metadata"]["attachment_filename"] == "notes.txt"
    # the body is still ingested too
    assert any((c.kwargs.get("link") or {}).get("relationship_type") == "content_of"
               for c in client.ingest_document.call_args_list)


@pytest.mark.asyncio
async def test_ingest_gmail_messages_scopes_to_subject(async_client, monkeypatch):
    """`subject` restricts the step-1 run to that one mailbox, skipping discovery."""
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([{"tenant_id": "T1", "sa_key_b64": _sa_b64(),
                     "mailboxes": ["me@acme.com", "other@acme.com"]}]),
    )

    fetched: list[str] = []

    async def fake_fetch(self, firm, subject, http, query=None, max_results=None):
        fetched.append(subject)
        return MessageFetch()

    monkeypatch.setattr(GmailAdapter, "fetch_messages", fake_fetch)
    monkeypatch.setattr(ingest_mod, "_load_company_domains", AsyncMock(return_value={}))
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value={}))
    app.state.client = AsyncMock()

    resp = await async_client.post(
        "/api/v1/ingest/gmail", json={"subject": "me@acme.com"}
    )
    assert resp.status_code == 200, resp.text
    assert fetched == ["me@acme.com"]  # only the requested mailbox

    # With an explicit tenant_id, a subject outside the static list is still
    # honored (the firm's SA has domain-wide delegation).
    fetched.clear()
    resp = await async_client.post(
        "/api/v1/ingest/gmail",
        json={"tenant_id": "T1", "subject": "niklas@acme.com"},
    )
    assert resp.status_code == 200, resp.text
    assert fetched == ["niklas@acme.com"]


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
        return MessageFetch()

    monkeypatch.setattr(GmailAdapter, "fetch_messages", fake_fetch)
    monkeypatch.setattr(ingest_mod, "_load_company_domains", AsyncMock(return_value={}))
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value={}))
    app.state.client = AsyncMock()

    # No query → defaults to the lookback window.
    resp = await async_client.post("/api/v1/ingest/gmail", json={})
    assert resp.status_code == 200, resp.text
    assert captured["query"] == "newer_than:7d"

    # Explicit query wins.
    resp = await async_client.post("/api/v1/ingest/gmail", json={"query": "newer_than:2d"})
    assert resp.status_code == 200, resp.text
    assert captured["query"] == "newer_than:2d"


@pytest.mark.asyncio
async def test_ingest_gmail_domain_discovery_carves_out_explicit(async_client, monkeypatch):
    """A domain firm (kibo) and an explicit-list firm (nzyme) share one Workspace.
    Discovery for kibo must exclude nzyme's explicitly-claimed mailboxes, and the
    explicit firm must never trigger discovery."""
    from pipeline.api import ingest as ingest_mod
    from pipeline.main import app

    monkeypatch.setattr(
        settings, "gmail_firms",
        json.dumps([
            {"tenant_id": "nzyme", "sa_key_b64": _sa_b64(),
             "mailboxes": ["lead@kiboventures.com"]},
            {"tenant_id": "kibo", "sa_key_b64": _sa_b64(),
             "domain": "kiboventures.com", "admin_subject": "admin@kiboventures.com"},
        ]),
    )

    seen_exclude: dict[str, frozenset[str] | set[str]] = {}

    async def fake_discover(firm, http, exclude=frozenset()):
        seen_exclude["exclude"] = exclude
        # The Workspace holds nzyme's lead plus two genuine kibo people.
        return [m for m in ["lead@kiboventures.com", "ceo@kiboventures.com",
                            "cfo@kiboventures.com"] if m.lower() not in exclude]

    monkeypatch.setattr(ingest_mod, "discover_mailboxes", fake_discover)

    fetched: list[tuple[str, str]] = []

    async def fake_fetch(self, firm, subject, http, query=None, max_results=None):
        fetched.append((firm.tenant_id, subject))
        return MessageFetch()

    monkeypatch.setattr(GmailAdapter, "fetch_messages", fake_fetch)
    monkeypatch.setattr(ingest_mod, "_load_company_domains", AsyncMock(return_value={}))
    monkeypatch.setattr(ingest_mod, "resolve_user_ids", AsyncMock(return_value={}))
    app.state.client = AsyncMock()

    resp = await async_client.post("/api/v1/ingest/gmail", json={})
    assert resp.status_code == 200, resp.text

    # Discovery received nzyme's explicit mailbox as a carve-out.
    assert "lead@kiboventures.com" in seen_exclude["exclude"]

    # nzyme pulled only its explicit mailbox; kibo only its discovered ones.
    nzyme_boxes = {m for t, m in fetched if t == "nzyme"}
    kibo_boxes = {m for t, m in fetched if t == "kibo"}
    assert nzyme_boxes == {"lead@kiboventures.com"}
    assert kibo_boxes == {"ceo@kiboventures.com", "cfo@kiboventures.com"}
    # The two tenants never share a mailbox.
    assert nzyme_boxes.isdisjoint(kibo_boxes)
