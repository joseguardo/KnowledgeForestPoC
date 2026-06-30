from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx

from pipeline import supabase_rest as sr

# App-layer graph reconciliation for events. The write layer (insert-pointer) is
# first-write-wins and insert-only, so the *decisions* about updating a moved
# meeting, soft-marking a cancelled one, and pruning attendees who left live here
# (see the dumb-edge-functions principle). All mutations go through the thin
# PostgREST passthrough in `supabase_rest`.


async def overwrite_event(
    http: httpx.AsyncClient,
    *,
    pointer_id: str,
    occurred_at: str | None = None,
    label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Refresh a re-ingested event's time/title/metadata. Calendar is the source of
    truth for the meeting, so on re-ingest its current values overwrite the node
    (insert-pointer would otherwise keep the first-written ones). Event-node
    metadata is calendar-owned (notes attach via documents/edges, not node
    metadata), so replacing it wholesale loses nothing note-contributed."""
    fields: dict[str, Any] = {}
    if occurred_at is not None:
        fields["occurred_at"] = occurred_at
    if label is not None:
        fields["label"] = label
    if metadata is not None:
        fields["metadata"] = metadata
    if fields:
        await sr.patch_pointer(http, pointer_id, fields)


async def reconcile_attendees(
    http: httpx.AsyncClient,
    *,
    event_id: str,
    desired_person_ids: Iterable[str],
    source: str = "calendar",
) -> list[str]:
    """Prune `source`-tagged `attended` edges for `event_id` whose person is no
    longer in `desired_person_ids`. Adds are handled by the normal link upsert;
    this only removes the ones that left. Edges tagged with a different source
    (e.g. note-contributed attendees) are never selected, so never pruned.
    Returns the ids of the deleted edges."""
    desired = set(desired_person_ids)
    existing = await sr.select_edges(
        http,
        filters=[
            ("target_id", f"eq.{event_id}"),
            ("relationship_type", "eq.attended"),
            ("payload->>source", f"eq.{source}"),
        ],
    )
    stale = [e for e in existing if e.get("source_id") not in desired]
    for e in stale:
        await sr.delete_edges(http, filters=[("id", f"eq.{e['id']}")])
    return [e["id"] for e in stale]


def meeting_title_key(title: str | None) -> str:
    """Whitespace/punctuation-insensitive, lowercased key for matching a meeting
    title across sources. Note titles are lifted from the calendar event, so the
    cleaned titles agree; this just absorbs case/spacing/punctuation drift."""
    return " ".join(re.findall(r"[^\W_]+", (title or "").lower()))


def _parse_utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hour_window(iso: str | None) -> tuple[str | None, str | None]:
    """The UTC clock-hour containing `iso`, as (lo, hi_inclusive) ISO bounds, or
    (None, None) if unparseable. Matching is "down to the hour"."""
    dt = _parse_utc(iso)
    if dt is None:
        return None, None
    lo = dt.replace(minute=0, second=0, microsecond=0)
    hi = lo + timedelta(hours=1) - timedelta(microseconds=1)
    return lo.isoformat(), hi.isoformat()


def _day_window(iso: str | None) -> tuple[str | None, str | None]:
    """The UTC calendar day containing `iso`, as (lo, hi_inclusive) ISO bounds.
    Used for date-only notes (no real clock time) — match on day + title instead."""
    dt = _parse_utc(iso)
    if dt is None:
        return None, None
    lo = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    hi = lo + timedelta(days=1) - timedelta(microseconds=1)
    return lo.isoformat(), hi.isoformat()


async def find_calendar_event(
    http: httpx.AsyncClient,
    *,
    tenant_id: str,
    scheduled_at: str | None,
    title: str | None,
    day: bool = False,
) -> str | None:
    """Resolve an already-ingested calendar meeting for a note to attach to: a
    `:gcal:` event in the same tenant whose normalized title matches, within the
    UTC clock-hour of `scheduled_at` (default) or — for a date-only note with no
    real clock time (`day=True`) — anywhere in that UTC day. Returns its
    pointer_id, or None. All matching is here in the app layer."""
    lo, hi = _day_window(scheduled_at) if day else _hour_window(scheduled_at)
    if lo is None:
        return None
    rows = await sr.select_pointers(
        http, ptype="communication", tenant_id=tenant_id, occurred_from=lo, occurred_to=hi
    )
    want = meeting_title_key(title)
    for r in rows:
        ck = r.get("canonical_key") or ""
        # Only a calendar-sourced meeting is a valid attach target (not a notes
        # event, not a recurring-series parent `:gcal-series:`).
        if ":gcal:" not in ck:
            continue
        if meeting_title_key(r.get("label")) == want:
            return r.get("id")
    return None


async def absorb_note_events(
    http: httpx.AsyncClient,
    *,
    tenant_id: str,
    calendar_event_id: str,
    scheduled_at: str | None,
    title: str | None,
) -> list[str]:
    """Notes-first reconciliation: when a calendar meeting is first ingested, fold
    any orphan note-event for the same meeting (same tenant + UTC clock-hour +
    title, with a non-`gcal` canonical key) into the calendar node — re-point its
    edges (its body document, extra attendees) to the calendar event, then delete
    the orphan. Returns the absorbed note-event ids. Keeps the calendar event as the
    single canonical meeting regardless of ingestion order."""
    lo, hi = _hour_window(scheduled_at)
    if lo is None:
        return []
    # NB: note-events are type `event` (notes-side marker); calendar meetings are
    # `communication`. We deliberately query `event` here to find orphan note-events
    # to absorb — not the calendar meetings themselves (which are skipped via `:gcal`).
    rows = await sr.select_pointers(
        http, ptype="event", tenant_id=tenant_id, occurred_from=lo, occurred_to=hi
    )
    want = meeting_title_key(title)
    absorbed: list[str] = []
    for r in rows:
        pid = r.get("id")
        ck = r.get("canonical_key") or ""
        if not pid or pid == calendar_event_id or ":gcal" in ck:
            continue  # skip self and any calendar-sourced node (meeting or series)
        if meeting_title_key(r.get("label")) != want:
            continue
        await sr.patch_edges(
            http, filters=[("source_id", f"eq.{pid}")],
            body={"source_id": calendar_event_id},
        )
        await sr.patch_edges(
            http, filters=[("target_id", f"eq.{pid}")],
            body={"target_id": calendar_event_id},
        )
        await sr.delete_rows(http, "pointers", filters=[("id", f"eq.{pid}")])
        absorbed.append(pid)
    return absorbed


async def soft_cancel_event(
    http: httpx.AsyncClient, *, canonical_key: str
) -> bool:
    """Soft-mark a cancelled meeting: keep the node (history/reversible), flag
    `metadata.status="cancelled"` + `cancelled_at`, and drop its calendar-sourced
    attendance edges. No-op (returns False) if the meeting was never ingested."""
    rows = await sr.select_pointers(http, canonical_key=canonical_key, ptype="communication")
    if not rows:
        return False
    row = rows[0]
    pid = row["id"]
    meta = {
        **(row.get("metadata") or {}),
        "status": "cancelled",
        "cancelled_at": datetime.now(timezone.utc).isoformat(),
    }
    await sr.patch_pointer(http, pid, {"metadata": meta})
    await sr.delete_edges(
        http,
        filters=[
            ("target_id", f"eq.{pid}"),
            ("relationship_type", "eq.attended"),
            ("payload->>source", "eq.calendar"),
        ],
    )
    return True
