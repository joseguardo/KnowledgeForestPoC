"""Google Calendar connector — fetch one mailbox's `primary` calendar and flatten
each event into a `CalendarEvent` record.

Reuses the Gmail service account + firm config: same domain-wide-delegation token
minting (`_mint_token`) and HTTP helper (`_get`), impersonating each mailbox with
the read-only Calendar scope. Calendars carry no per-user privacy (everyone in a
firm sees everyone's calendar), so the orchestration layer writes everything at
the firm-wide access class.

Two layers, mirroring the Gmail adapter:
  - `events_from_calendar` is pure (parse + filter, no I/O) — testable in isolation;
  - `fetch_events` mints a token, pages `events.list`, and flattens via the above.

Filtering drops the noise that has no graph value: cancelled tombstones, all-day
blocks (birthdays/OOO), events the owner declined, and solo events with no other
human participant. The same meeting appears on every attendee's calendar; it is
deduped to one node downstream by `iCalUID`, not here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

# Reuse the Gmail connector's Google auth + HTTP plumbing + SA-key decoding.
from pipeline.adapters.gmail import (
    GmailFirm,
    _decode_sa_key,
    _get,
    _load_sa_info_json,
    _mint_token,
)
from pipeline.config import settings

log = logging.getLogger(__name__)

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


def _calendar_sa_info() -> dict[str, Any] | None:
    """The calendar connector's own service account, or None to reuse Gmail's.

    Calendar runs on a separate SA whose client id is the one authorized for
    `calendar.readonly` domain-wide delegation. Base64 takes precedence over the
    raw-JSON/path form, mirroring the Gmail key resolution."""
    b64 = (settings.calendar_sa_key_b64 or "").strip()
    if b64:
        return _decode_sa_key(b64)
    raw = (settings.calendar_sa_key_json or "").strip()
    if raw:
        return _load_sa_info_json(raw)
    return None


@dataclass
class CalendarEvent:
    """One calendar event — the atomic unit of calendar ingestion.

    Identity is the `iCalUID` (stable across every attendee's copy of the meeting)
    so the graph dedups the shared event to a single node. `attendees` are the
    *other* human participants (owner and meeting-room resources excluded);
    entity classification/direction are applied later in the orchestration layer.
    """

    tenant_id: str
    calendar_email: str                       # impersonated mailbox = event owner
    owner_name: str | None
    ical_uid: str
    event_id: str
    title: str
    start: str | None                         # ISO datetime (occurred_at)
    end: str | None
    location: str | None
    description: str
    organizer: tuple[str, str | None]         # (email, display name)
    attendees: list[tuple[str, str | None]]   # other humans: (email, display name)
    # `recurringEventId` — the series id when this is an instance of a recurring
    # meeting; None for a one-off. (Distinct from iCalUID, which is per-occurrence.)
    recurring_event_id: str | None = None


def _attendee_name(att: dict[str, Any]) -> str | None:
    name = (att.get("displayName") or "").strip()
    return name or None


def events_from_calendar(
    items: list[dict[str, Any]],
    *,
    tenant_id: str,
    calendar_email: str,
) -> list[CalendarEvent]:
    """Flatten raw `events.list` items into records, dropping the noise.

    Skips: cancelled events; all-day events (a `start.date` with no `dateTime`);
    events the owner declined (their `self` attendee `responseStatus == declined`);
    and solo events with no other human participant. Pure: no run context applied.
    """
    owner = calendar_email.strip().lower()
    out: list[CalendarEvent] = []
    for it in items:
        if (it.get("status") or "").lower() == "cancelled":
            continue

        start_obj = it.get("start") or {}
        end_obj = it.get("end") or {}
        start = start_obj.get("dateTime")
        if not start:
            # All-day (date only) or a free/busy stub with no time → skip.
            continue

        raw_attendees = it.get("attendees") or []
        owner_declined = any(
            a.get("self") and (a.get("responseStatus") or "").lower() == "declined"
            for a in raw_attendees
        )
        if owner_declined:
            continue

        # Other human participants: every attendee that isn't the owner or a
        # meeting-room resource, plus an external organizer not already listed.
        others: dict[str, str | None] = {}
        for a in raw_attendees:
            if a.get("resource"):
                continue
            addr = (a.get("email") or "").strip().lower()
            if not addr or addr == owner:
                continue
            others.setdefault(addr, _attendee_name(a))

        org = it.get("organizer") or {}
        org_email = (org.get("email") or "").strip().lower()
        org_name = (org.get("displayName") or "").strip() or None
        if org_email and org_email != owner and org_email not in others:
            others[org_email] = org_name

        if not others:
            continue  # solo / personal block — no who-met-whom signal

        owner_name = next(
            (_attendee_name(a) for a in raw_attendees if a.get("self")), None
        )
        if owner_name is None and org_email == owner:
            owner_name = org_name

        out.append(
            CalendarEvent(
                tenant_id=tenant_id,
                calendar_email=owner,
                owner_name=owner_name,
                ical_uid=(it.get("iCalUID") or it.get("id") or "").strip(),
                event_id=(it.get("id") or "").strip(),
                title=(it.get("summary") or "").strip() or "(no title)",
                start=start,
                end=end_obj.get("dateTime") or end_obj.get("date"),
                location=(it.get("location") or "").strip() or None,
                description=(it.get("description") or "").strip(),
                organizer=(org_email, org_name),
                attendees=list(others.items()),
                recurring_event_id=(it.get("recurringEventId") or "").strip() or None,
            )
        )
    return out


async def fetch_events(
    firm: GmailFirm,
    subject: str,
    http: httpx.AsyncClient,
    *,
    updated_min: str | None = None,
    max_results: int | None = None,
    sa_info: dict[str, Any] | None = None,
) -> list[CalendarEvent]:
    """Fetch `subject`'s primary calendar and flatten to records.

    Mints a DWD token for the Calendar scope using `sa_info` (the calendar SA)
    when given, else the firm's Gmail SA. Pages `events.list` (recurring events
    expanded to instances, ordered by start) over a `timeMin = now -
    calendar_backfill_days` window with no upper bound (upcoming events included),
    and — when `updated_min` is given (incremental sync) — only events changed
    since then. Bounded by `calendar_max_pages` / `max_results`.
    """
    token = await _mint_token(sa_info or firm.sa_info, subject, settings.calendar_scopes)
    headers = {"Authorization": f"Bearer {token}"}
    cap = max_results or settings.calendar_max_results
    time_min = (
        datetime.now(timezone.utc) - timedelta(days=settings.calendar_backfill_days)
    ).isoformat()
    # The DWD token already impersonates `subject`, so `primary` is their calendar.
    url = f"{CALENDAR_API_BASE}/calendars/primary/events"

    raw: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(settings.calendar_max_pages):
        remaining = cap - len(raw)
        if remaining <= 0:
            break
        params: dict[str, Any] = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": time_min,
            "maxResults": min(250, remaining),
        }
        if updated_min:
            params["updatedMin"] = updated_min
        if page_token:
            params["pageToken"] = page_token
        data = await _get(http, url, headers, params)
        raw.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return events_from_calendar(raw[:cap], tenant_id=firm.tenant_id, calendar_email=subject)
