from __future__ import annotations

import asyncio
import base64
import email
import hashlib
import json
import re
from dataclasses import dataclass
from email import policy
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

import httpx

from pipeline.adapters.document import _extract_email, _validate_content
from pipeline.config import settings
from pipeline.errors import AdapterError, ValidationError

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_RE_PREFIX = re.compile(r"^\s*(re|fwd|fw)\s*:\s*", re.IGNORECASE)

# Automated / non-human senders that should NOT become person entities. They
# stay in the event metadata only, keeping the who-contacted-whom graph clean.
_NOISE_LOCALPARTS = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|mailer-daemon|postmaster|"
    r"bounce|bounces|notifications?|notify|alerts?|automated|auto|noreply)\b",
    re.IGNORECASE,
)


# ── Per-firm connector config ───────────────────────────────────────


@dataclass
class GmailFirm:
    """One firm = one tenant with its own Google Workspace + service account."""

    tenant_id: str
    sa_info: dict[str, Any]
    mailboxes: list[str]
    scopes: str


@dataclass
class ThreadParticipant:
    email: str
    name: str | None
    role: str  # "from" | "to" | "cc"


@dataclass
class EmailThread:
    """One Gmail thread, normalized for the public-graph + private-body split."""

    tenant_id: str
    mailbox: str
    gmail_thread_id: str
    thread_hash: str  # sha256(References-chain root Message-ID); stable cross-mailbox
    participants: list[ThreadParticipant]  # real people only (noise filtered)
    event_label: str  # subject-free
    occurred_at: str | None
    metadata: dict[str, Any]
    body: str  # private content: subject(s) + bodies


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
        if not mailboxes:
            raise ValidationError(f"GMAIL_FIRMS entry for {tid} has no mailboxes")
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
    """Fetches Gmail threads for one firm mailbox via domain-wide delegation and
    normalizes each into an EmailThread (public communication graph + private
    body). Orchestration of class/grant provisioning and ingestion lives in the
    API layer, since it spans several edge-function calls per thread."""

    async def fetch_threads(
        self,
        firm: GmailFirm,
        subject: str,
        http: httpx.AsyncClient,
        query: str | None = None,
        max_results: int | None = None,
    ) -> list[EmailThread]:
        token = await _mint_token(firm.sa_info, subject, firm.scopes)
        headers = {"Authorization": f"Bearer {token}"}
        cap = max_results or settings.gmail_max_results
        thread_ids = await _list_thread_ids(http, headers, query, cap)

        threads: list[EmailThread] = []
        for thread_id in thread_ids:
            thread = await _thread_to_email(http, headers, thread_id, firm.tenant_id, subject)
            if thread is not None:
                threads.append(thread)
        return threads


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


async def _list_thread_ids(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    query: str | None,
    max_results: int,
) -> list[str]:
    params: dict[str, Any] = {"maxResults": max_results}
    if query:
        params["q"] = query
    data = await _get(http, f"{GMAIL_API_BASE}/threads", headers, params)
    return [t["id"] for t in data.get("threads", []) if t.get("id")][:max_results]


async def _thread_to_email(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    thread_id: str,
    tenant_id: str,
    mailbox: str,
) -> EmailThread | None:
    # threads.get only supports full/metadata/minimal — NOT raw. Enumerate
    # message IDs minimally, then pull each as raw RFC822 and reuse the parser.
    data = await _get(
        http, f"{GMAIL_API_BASE}/threads/{thread_id}", headers, {"format": "minimal"}
    )

    parsed_msgs: list[dict[str, Any]] = []
    sections: list[str] = []
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
            parsed = _parse_message(base64.urlsafe_b64decode(raw))
        except (AdapterError, ValueError):
            continue
        parsed_msgs.append(parsed)

        header_block = "\n".join(
            line
            for line in (
                f"From: {parsed['from']}" if parsed["from"] else "",
                f"To: {parsed['to']}" if parsed["to"] else "",
                f"Date: {parsed['occurred_at']}" if parsed["occurred_at"] else "",
                f"Subject: {parsed['subject']}",
            )
            if line
        )
        sections.append(f"{header_block}\n\n{parsed['body']}")

    if not parsed_msgs:
        return None

    root_id = _thread_root_id(parsed_msgs)
    if not root_id:
        return None
    thread_hash = hashlib.sha256(root_id.encode("utf-8")).hexdigest()[:32]

    # Participants by role across the whole thread.
    by_role: dict[str, list[tuple[str, str]]] = {"from": [], "to": [], "cc": []}
    seen: set[tuple[str, str]] = set()
    for m in parsed_msgs:
        for role, header in (("from", "from"), ("to", "to"), ("cc", "cc")):
            for name, addr in getaddresses([m[header]] if m[header] else []):
                addr = addr.strip().lower()
                if not addr or (role, addr) in seen:
                    continue
                seen.add((role, addr))
                by_role[role].append((addr, name.strip()))

    # Skip machine-only threads (no human sender) — keeps newsletters/alerts out
    # of the graph and off the embedding bill. Side effect: every kept thread has
    # a real sender, so the event label is never "Email: ? -> …".
    if settings.gmail_skip_noise_senders and not any(
        not _is_noise(addr) for addr, _ in by_role["from"]
    ):
        return None

    participants: list[ThreadParticipant] = []
    for role in ("from", "to", "cc"):
        for addr, name in by_role[role]:
            if _is_noise(addr):
                continue
            participants.append(ThreadParticipant(email=addr, name=name or None, role=role))

    # Dates → occurred_at (latest), first/last for metadata.
    dates = []
    for m in parsed_msgs:
        if m["occurred_at"]:
            try:
                dates.append(parsedate_to_datetime(m["occurred_at"]))
            except (TypeError, ValueError):
                pass
    occurred_at = max(dates).isoformat() if dates else None
    first_at = min(dates).isoformat() if dates else None

    body = "\n\n---\n\n".join(sections)
    _validate_content(body)

    metadata = {
        "event_type": "email",
        "thread_root_id": root_id,
        "gmail_thread_id": thread_id,
        "mailbox": mailbox,
        "message_count": len(parsed_msgs),
        "first_at": first_at,
        "last_at": occurred_at,
        # All addresses incl. noise — public who-contacted-whom record.
        "participants": {role: [a for a, _ in by_role[role]] for role in by_role},
    }

    return EmailThread(
        tenant_id=tenant_id,
        mailbox=mailbox,
        gmail_thread_id=thread_id,
        thread_hash=thread_hash,
        participants=participants,
        event_label=_event_label(by_role),
        occurred_at=occurred_at,
        metadata=metadata,
        body=body,
    )


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


def _event_label(by_role: dict[str, list[tuple[str, str]]]) -> str:
    """Subject-free label (subject is private), e.g. 'Email: Alice -> Bob'.
    Built from real people only (noise senders/recipients are left out)."""

    def short(addr: str, name: str) -> str:
        return name or addr.split("@")[0]

    def people(role: str) -> list[str]:
        return [short(a, n) for a, n in by_role[role] if not _is_noise(a)]

    senders = people("from")
    recipients = people("to")
    sender_s = ", ".join(senders[:2]) or "?"
    recip_s = ", ".join(recipients[:2]) or "?"
    if len(recipients) > 2:
        recip_s += f", +{len(recipients) - 2}"
    return f"Email: {sender_s} -> {recip_s}"[:200]


def _is_noise(addr: str) -> bool:
    local = addr.split("@", 1)[0]
    return bool(_NOISE_LOCALPARTS.match(local))


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
    }


def _clean_subject(subject: str | None) -> str:
    if not subject:
        return ""
    s = subject.strip()
    while True:
        stripped = _RE_PREFIX.sub("", s)
        if stripped == s:
            break
        s = stripped
    return s[:120]


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
