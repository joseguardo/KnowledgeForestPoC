from __future__ import annotations

import asyncio
import base64
import email
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import timezone
from email import policy
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

import httpx

from pipeline.adapters.document import _extract_email
from pipeline.config import settings
from pipeline.errors import AdapterError, ValidationError

log = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
DIRECTORY_API_BASE = "https://admin.googleapis.com/admin/directory/v1"

# Automated / non-human senders that should NOT become person entities. They
# stay in the event metadata only, keeping the who-contacted-whom graph clean.
# Matched anywhere in the local-part (word-bounded), so e.g. "comments-noreply"
# and "bounce+tag" are caught, not just addresses that start with the word.
_NOISE_LOCALPARTS = re.compile(
    r"\b(no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|mailer-daemon|postmaster|"
    r"bounce|bounces|notifications?|notify|alerts?|automated|auto|noreply)\b",
    re.IGNORECASE,
)


# ── Per-firm connector config ───────────────────────────────────────


@dataclass
class GmailFirm:
    """One firm = one tenant with its own Google Workspace + service account.

    Mailboxes are either listed explicitly (`mailboxes`) or auto-discovered from
    `domain` via the Admin Directory API at ingest time (impersonating
    `admin_subject`). Exactly one of the two is required per firm.
    """

    tenant_id: str
    sa_info: dict[str, Any]
    mailboxes: list[str]
    scopes: str
    domain: str | None = None
    admin_subject: str | None = None


@dataclass
class EmailMessage:
    """One message within a thread — the atomic unit of the step-1 rebuild.

    Identity is the RFC822 Message-ID (fallback synthetic hash); `thread_id`
    groups messages of the same conversation. Entity classification and
    direction are applied later in the orchestration layer (they need run
    context: CRM domains, own domains, correspondence)."""

    tenant_id: str
    mailbox: str
    message_id: str
    thread_id: str
    occurred_at: str | None
    sender: tuple[str, str | None]          # (email, display name)
    to: list[tuple[str, str | None]]
    cc: list[tuple[str, str | None]]
    subject: str                            # private (used in a later body step)
    body: str                               # private (used in a later body step)


def load_firms(tenant_id: str | None = None) -> list[GmailFirm]:
    """Parse settings.gmail_firms (JSON array). Optionally filter to one tenant."""
    raw = (settings.gmail_firms or "").strip()
    if not raw:
        raise ValidationError(
            "Gmail connector not configured: set GMAIL_FIRMS (JSON array of "
            '{tenant_id, sa_key_b64, mailboxes})'
        )
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"GMAIL_FIRMS is not valid JSON: {exc}")
    if not isinstance(entries, list):
        raise ValidationError("GMAIL_FIRMS must be a JSON array")

    firms: list[GmailFirm] = []
    for entry in entries:
        tid = str(entry.get("tenant_id") or "").strip()
        if tenant_id and tid != tenant_id:
            continue
        if not tid:
            raise ValidationError("GMAIL_FIRMS entry missing tenant_id")
        mailboxes = [m.strip() for m in (entry.get("mailboxes") or []) if m.strip()]
        domain = str(entry.get("domain") or "").strip() or None
        # A firm supplies its mailbox set one of two ways: an explicit list, or a
        # domain to auto-discover. Auto-discovery impersonates a Workspace admin.
        if not mailboxes and not domain:
            raise ValidationError(
                f"GMAIL_FIRMS entry for {tid} has no mailboxes and no domain"
            )
        admin_subject = (
            str(entry.get("admin_subject") or "").strip()
            or settings.gmail_admin_subject
        )
        if domain and not mailboxes and not admin_subject:
            raise ValidationError(
                f"GMAIL_FIRMS entry for {tid} uses domain discovery but has no "
                "admin_subject (set its admin_subject or GMAIL_ADMIN_SUBJECT)"
            )
        # One service account typically serves every tenant (its client ID is
        # DWD-authorized in each firm's Workspace). Resolve the key per entry,
        # else fall back to the global GMAIL_SA_KEY_B64 / GMAIL_SA_KEY_JSON.
        entry_b64 = (entry.get("sa_key_b64") or settings.gmail_sa_key_b64 or "").strip()
        if entry_b64:
            sa_info = _decode_sa_key(entry_b64)
        elif settings.gmail_sa_key_json:
            sa_info = _load_sa_info_json(settings.gmail_sa_key_json)
        else:
            raise ValidationError(
                f"GMAIL_FIRMS entry for {tid} has no SA key: set its sa_key_b64, "
                "or a global GMAIL_SA_KEY_B64 / GMAIL_SA_KEY_JSON"
            )
        firms.append(
            GmailFirm(
                tenant_id=tid,
                sa_info=sa_info,
                mailboxes=mailboxes,
                scopes=(entry.get("scopes") or settings.gmail_scopes),
                domain=domain,
                admin_subject=admin_subject,
            )
        )
    if tenant_id and not firms:
        raise ValidationError(f"GMAIL_FIRMS has no firm for tenant_id {tenant_id!r}")
    return firms


def _decode_sa_key(b64: str) -> dict[str, Any]:
    try:
        return json.loads(base64.b64decode(b64.strip()))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValidationError(f"sa_key_b64 is not valid base64-encoded JSON: {exc}")


def _load_sa_info_json(raw: str) -> dict[str, Any]:
    """Global SA from GMAIL_SA_KEY_JSON: a raw JSON string, or a path to the key
    file. Lets a firm entry omit its own key and reuse the already-configured SA."""
    raw = raw.strip()
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        with open(raw, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValidationError(
            f"GMAIL_SA_KEY_JSON is not valid JSON or a readable key-file path: {exc}"
        )


# ── Adapter ─────────────────────────────────────────────────────────


class GmailAdapter:
    """Fetches Gmail messages for one firm mailbox via domain-wide delegation and
    flattens each thread into per-message `EmailMessage` records. Orchestration of
    class/grant provisioning and graph writes lives in the API layer."""

    async def fetch_messages(
        self,
        firm: GmailFirm,
        subject: str,
        http: httpx.AsyncClient,
        query: str | None = None,
        max_results: int | None = None,
    ) -> list[EmailMessage]:
        """Step-1 path: fetch threads and flatten to per-message records.

        Mints a DWD token, lists thread ids, fetches each thread's messages, and
        emits one `EmailMessage` per message. Entity classification/direction are
        applied later in the orchestration layer (CRM + own-domain context)."""
        token = await _mint_token(firm.sa_info, subject, firm.scopes)
        headers = {"Authorization": f"Bearer {token}"}
        cap = max_results or settings.gmail_max_results
        thread_ids = await _list_thread_ids(http, headers, query, cap)

        out: list[EmailMessage] = []
        for thread_id in thread_ids:
            try:
                parsed = await _fetch_thread_parsed(http, headers, thread_id)
            except (AdapterError, ValidationError) as exc:
                log.warning("skipping gmail thread %s for %s: %s", thread_id, subject, exc)
                continue
            out.extend(
                messages_from_thread(parsed, tenant_id=firm.tenant_id, mailbox=subject)
            )
        return out


async def _mint_token(sa_info: dict[str, Any], subject: str, scopes: str) -> str:
    """Mint a domain-wide-delegation access token for `subject`. The google-auth
    refresh is a synchronous network call, so run it off the event loop."""
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account

    scope_list = [s for s in scopes.split() if s]
    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=scope_list, subject=subject
    )

    def _refresh() -> str:
        creds.refresh(GoogleAuthRequest())
        return creds.token

    return await asyncio.to_thread(_refresh)


async def discover_mailboxes(
    firm: GmailFirm,
    http: httpx.AsyncClient,
    exclude: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """Enumerate active mailboxes in `firm.domain` via the Admin Directory API.

    Impersonates `firm.admin_subject` (an admin) with the directory scope, pages
    through users.list, drops suspended/archived accounts, and removes any
    address in `exclude` (mailboxes another firm has claimed explicitly, so a
    shared-Workspace tenant isn't swept into the wrong graph). Returns the sorted,
    de-duplicated primary emails.
    """
    token = await _mint_token(
        firm.sa_info, firm.admin_subject, settings.gmail_directory_scope
    )
    headers = {"Authorization": f"Bearer {token}"}
    excluded = {e.lower() for e in exclude}

    emails: set[str] = set()
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"domain": firm.domain, "maxResults": 500}
        if settings.gmail_directory_query:
            params["query"] = settings.gmail_directory_query
        if page_token:
            params["pageToken"] = page_token
        data = await _get(http, f"{DIRECTORY_API_BASE}/users", headers, params)
        for user in data.get("users", []):
            if user.get("suspended") or user.get("archived"):
                continue
            primary = (user.get("primaryEmail") or "").strip()
            if primary and primary.lower() not in excluded:
                emails.add(primary)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return sorted(emails)


async def _list_thread_ids(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    query: str | None,
    max_results: int,
) -> list[str]:
    """Collect up to `max_results` thread IDs, following nextPageToken.

    Gmail caps a single threads.list page at 500, so a full-history backfill
    needs to page. `max_results` is the total cap across pages; `gmail_max_pages`
    bounds the loop so a huge query can't run away.
    """
    ids: list[str] = []
    page_token: str | None = None
    for _ in range(settings.gmail_max_pages):
        remaining = max_results - len(ids)
        if remaining <= 0:
            break
        params: dict[str, Any] = {"maxResults": min(500, remaining)}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        data = await _get(http, f"{GMAIL_API_BASE}/threads", headers, params)
        ids.extend(t["id"] for t in data.get("threads", []) if t.get("id"))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_results]


async def _fetch_thread_parsed(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    thread_id: str,
) -> list[dict[str, Any]]:
    """Fetch a thread and parse each message to the `_parse_message` dict form.

    threads.get only supports full/metadata/minimal — not raw — so enumerate
    message IDs minimally, then pull each as raw RFC822 and parse. Bad messages
    are skipped, not fatal."""
    data = await _get(
        http, f"{GMAIL_API_BASE}/threads/{thread_id}", headers, {"format": "minimal"}
    )
    parsed_msgs: list[dict[str, Any]] = []
    for msg in data.get("messages", []):
        msg_id = msg.get("id")
        if not msg_id:
            continue
        full = await _get(
            http, f"{GMAIL_API_BASE}/messages/{msg_id}", headers, {"format": "raw"}
        )
        raw = full.get("raw")
        if not raw:
            continue
        try:
            parsed_msgs.append(_parse_message(base64.urlsafe_b64decode(raw)))
        except (AdapterError, ValueError):
            continue
    return parsed_msgs


def _utf16_len(s: str) -> int:
    """Length in UTF-16 code units — what JS String.length (and the
    ingest-document edge function's content check) counts."""
    return len(s.encode("utf-16-le")) // 2


def _truncate_utf16(s: str, max_units: int) -> str:
    """Truncate `s` to at most `max_units` UTF-16 code units without splitting a
    surrogate pair (which would leave a lone surrogate that can't decode)."""
    if _utf16_len(s) <= max_units:
        return s
    chunk = s.encode("utf-16-le")[: max_units * 2]
    try:
        return chunk.decode("utf-16-le")
    except UnicodeDecodeError:
        # Cut landed mid surrogate pair — drop the dangling half code unit.
        return chunk[:-2].decode("utf-16-le")


def _thread_root_id(parsed_msgs: list[dict[str, Any]]) -> str | None:
    """Cross-mailbox-stable thread identity: the root of the References chain
    (References[0] of any reply), else the earliest message's own Message-ID."""
    for m in parsed_msgs:
        if m["references"]:
            return m["references"][0]
    for m in parsed_msgs:
        if m["message_id"]:
            return m["message_id"]
    return None


def _addr_list(header: str | None) -> list[tuple[str, str | None]]:
    """Parse an address header into (lowercased email, display name) pairs."""
    out: list[tuple[str, str | None]] = []
    for name, addr in getaddresses([header] if header else []):
        a = addr.strip().lower()
        if a:
            out.append((a, name.strip() or None))
    return out


def _iso_or_none(raw: str | None) -> str | None:
    """RFC822 Date → tz-aware UTC ISO string (naive dates assumed UTC)."""
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _fallback_message_id(parsed: dict[str, Any]) -> str:
    """Stable synthetic id for a message missing a Message-ID header."""
    basis = f"{parsed.get('from', '')}|{parsed.get('occurred_at', '')}|{parsed.get('subject', '')}"
    return "synthetic:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


_BULK_PRECEDENCE = {"bulk", "list", "junk"}
# Display-name words that mark a brand/team rather than a person.
_BRAND_NAME_RE = re.compile(
    r"\b(teams?|equipos?|[ée]quipes?|crew|newsletters?|notifications?|"
    r"updates?|alerts?|support|no[-\s]?reply)\b",
    re.IGNORECASE,
)


def _is_brandy_name(name: str | None) -> bool:
    """A sender display name that signals an org/team, not a person — e.g.
    'El equipo de Miro', 'The X Team', or a single brandy token like 'Fun.xyz'.
    Deliberately conservative: a normal personal name (with a space, or a single
    token without a dotted-domain/digit) is kept."""
    if not name:
        return False
    n = name.strip()
    if _BRAND_NAME_RE.search(n):
        return True
    # Single token that looks like a domain/handle ("Fun.xyz") or carries digits.
    return " " not in n and bool(re.search(r"\w\.\w{2,}", n) or re.search(r"\d", n))


def _is_drop_sender(addr: str) -> bool:
    """A sender role mailbox (info@, sales@, marketing@, newsletter@, …) — not
    human 1:1 correspondence. Configurable via gmail_drop_sender_localparts."""
    local = addr.split("@", 1)[0].lower()
    drop = {p.strip().lower() for p in (settings.gmail_drop_sender_localparts or "").split(",") if p.strip()}
    return local in drop


def _is_noise_message(parsed: dict[str, Any]) -> bool:
    """True for non-human mail we don't ingest: newsletters / mailing lists,
    marketing & product info, login/transactional, meeting invitations, and other
    automated mail.

    Detected from headers we already receive (List-Unsubscribe/List-Id,
    Precedence: bulk|list|junk, Auto-Submitted, a text/calendar part), a
    no-reply/automated or role-mailbox sender address, or a brand/team sender
    display name (for marketing mail that carries no machine headers). A plain
    header-less mail from a real address (e.g. a recurring internal agenda) can
    still slip through — that needs content/LLM signals, not headers."""
    if parsed.get("list_mail"):
        return True
    if parsed.get("is_calendar"):
        return True
    if parsed.get("precedence") in _BULK_PRECEDENCE:
        return True
    auto = parsed.get("auto_submitted", "")
    if auto and auto != "no":
        return True
    senders = _addr_list(parsed.get("from"))
    if not senders:
        return False
    addr, name = senders[0]
    return _is_noise(addr) or _is_drop_sender(addr) or _is_brandy_name(name)


def messages_from_thread(
    parsed_msgs: list[dict[str, Any]],
    *,
    tenant_id: str,
    mailbox: str,
) -> list[EmailMessage]:
    """Flatten a thread's parsed messages into per-message records.

    Non-human messages (newsletters, automated/transactional, no-reply — see
    `_is_noise_message`) are skipped entirely: no event, no entities. Pure: no
    run context applied (direction/entities come later). `thread_id` is the
    cross-mailbox-stable thread hash; messages with no References root fall back
    to grouping by their own id.
    """
    root_id = _thread_root_id(parsed_msgs)
    thread_id = hashlib.sha256(root_id.encode("utf-8")).hexdigest()[:32] if root_id else ""

    out: list[EmailMessage] = []
    for m in parsed_msgs:
        if _is_noise_message(m):
            continue
        senders = _addr_list(m.get("from"))
        sender = senders[0] if senders else ("", None)
        mid = (m.get("message_id") or "").strip() or _fallback_message_id(m)
        out.append(
            EmailMessage(
                tenant_id=tenant_id,
                mailbox=mailbox,
                message_id=mid,
                thread_id=thread_id or hashlib.sha256(mid.encode("utf-8")).hexdigest()[:32],
                occurred_at=_iso_or_none(m.get("occurred_at")),
                sender=sender,
                to=_addr_list(m.get("to")),
                cc=_addr_list(m.get("cc")),
                subject=m.get("subject") or "",
                body=m.get("body") or "",
            )
        )
    return out


def _is_noise(addr: str) -> bool:
    local = addr.split("@", 1)[0]
    return bool(_NOISE_LOCALPARTS.search(local))


def _parse_message(msg_bytes: bytes) -> dict[str, Any]:
    # Reuse the RFC822 parser (subject/body/date + HTML stripping) from the
    # document adapter, then read the addressing + threading headers it omits.
    subject, body, occurred_at = _extract_email(msg_bytes)
    msg = email.message_from_bytes(msg_bytes, policy=policy.default)
    refs_raw = str(msg.get("References", "")).strip()
    references = re.findall(r"<[^>]+>", refs_raw)
    if not references:
        in_reply = str(msg.get("In-Reply-To", "")).strip()
        references = re.findall(r"<[^>]+>", in_reply)
    return {
        "subject": subject,
        "body": body,
        "occurred_at": occurred_at,
        "from": str(msg.get("From", "")).strip(),
        "to": str(msg.get("To", "")).strip(),
        "cc": str(msg.get("Cc", "")).strip(),
        "message_id": str(msg.get("Message-ID", "")).strip() or None,
        "references": references,
        # Automated/bulk-mail signals (used to skip non-human messages).
        "list_mail": bool(msg.get("List-Unsubscribe") or msg.get("List-Id")),
        "precedence": str(msg.get("Precedence", "")).strip().lower(),
        "auto_submitted": str(msg.get("Auto-Submitted", "")).strip().lower(),
        "is_calendar": _has_calendar_part(msg),
    }


def _has_calendar_part(msg: email.message.Message) -> bool:
    """True if the message carries a calendar invite (text/calendar part, any
    method — REQUEST/REPLY/CANCEL — or an Outlook calendar Content-Class)."""
    for part in msg.walk():
        if (part.get_content_type() or "").lower() == "text/calendar":
            return True
    return "calendarmessage" in str(msg.get("Content-Class", "")).lower()


async def _get(
    http: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
) -> dict[str, Any]:
    try:
        resp = await http.get(
            url, headers=headers, params=params, timeout=settings.web_scrape_timeout
        )
        resp.raise_for_status()
    except httpx.TimeoutException:
        raise AdapterError(f"Timeout calling Gmail API: {url}")
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"Gmail API HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"Gmail API request failed: {exc}")
    return resp.json()
