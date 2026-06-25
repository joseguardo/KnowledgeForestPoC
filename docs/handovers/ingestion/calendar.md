# Calendar ingestion — handover

Google Calendar events for every mailbox in a firm, read with the **same service
account as Gmail** (domain-wide delegation) which additionally holds the
read-only Calendar scope. Adapter: `pipeline/pipeline/adapters/calendar.py`;
deterministic extraction: `pipeline/pipeline/adapters/calendar_entities.py`;
orchestration: `ingest_calendar` in `pipeline/pipeline/api/ingest.py`.

Built to mirror the Gmail/Notes rework: it reuses the same classification brain
(`classify_address`), the same email-keyed person/company nodes, and the same
shared write path (`insert_pointer` + `link_pointers`). No bespoke edge function
— the old `ingest-calendar` function is **deprecated** (the Notes rework already
removed its only caller; this connector does not use it either).

**No per-user privacy.** Everyone in a firm sees everyone's calendar, so events,
people, companies, edges *and* event-description bodies all land at the firm-wide
`firm:{tenant_id}` access class. There is no per-event/per-attendee grant tier
(unlike email bodies / confidential notes).

---

## Configuration

Reuses **`GMAIL_FIRMS`** verbatim — same firms, same mailboxes/domain discovery.
But calendar mints its DWD token with a **dedicated service account** (the one
whose client id is authorized for `calendar.readonly` in the Workspace's
domain-wide delegation — distinct from the Gmail SA). Settings (`config.py`):

- `CALENDAR_SA_KEY_JSON` / `CALENDAR_SA_KEY_B64` — the calendar SA key (raw JSON /
  path, or base64; b64 wins). **When unset, falls back to the Gmail SA**
  (`firm.sa_info`). Resolved by `_calendar_sa_info()` in `adapters/calendar.py`
  and threaded into `fetch_events(..., sa_info=…)`; the endpoint resolves it once
  per request. Domain auto-discovery still uses the Gmail SA (it needs the admin
  directory scope), so only the per-mailbox calendar fetch uses the calendar SA.
- `calendar_scopes` = `https://www.googleapis.com/auth/calendar.readonly` (default).
  **Gotcha:** the live `calendarbot` SA's DWD is authorized for the *full* scope
  `…/auth/calendar`, not the readonly one, so `.env` sets
  `CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar`. The connector only
  ever GETs, so it stays read-only in practice.
- `calendar_backfill_days` (default 30) — first-run / non-incremental lookback.
- `calendar_max_results` (250), `calendar_max_pages` (20) — per-calendar caps.

---

## The pipeline (endpoint `POST /api/v1/ingest/calendar`)

Request (`CalendarRequest`): `subject?`, `max_results?`, `since_last`, `tenant_id?`.
Mailbox selection and the shared-Workspace carve-out are **identical to Gmail**
(subject trusted when `tenant_id` pins the firm; else only the owning firm acts;
no subject → the firm's mailbox list or domain auto-discovery).

**Fetch** (`fetch_events`): mints a DWD token per mailbox, reads its **`primary`**
calendar via `events.list` with `singleEvents=true` + `orderBy=startTime`,
`timeMin = now − calendar_backfill_days` and **no `timeMax`** (upcoming events are
ingested too). Incremental runs add `updatedMin = cursor` to re-pull new/edited
events. Pages on `nextPageToken`.

**Filter** (`events_from_calendar`, pure) drops the no-signal noise:
- `status == cancelled` (tombstones from incremental sync);
- all-day events (a `start.date` with no `start.dateTime`);
- events the owner declined (their `self` attendee `responseStatus == declined`);
- solo events with no other human participant (meeting-room *resources* don't
  count; an external organizer does).

**Extract** (`calendar_entities.extract_graph`), per event:
- **event** node, keyed **`event:{tenant}:gcal:{iCalUID}`**. Because `iCalUID` is
  stable across every attendee's copy of a meeting, the same meeting read from N
  calendars **collapses to one node** (edges accumulate). `occurred_at` = start;
  metadata = `{event_type:"meeting", location, end, organizer_email, provider,
  calendar_email, is_recurring, series_id}`.
- **recurring meetings**: an occurrence with a `recurringEventId` is tagged
  (`is_recurring=true`, `series_id`) and linked `event -instance_of-> series`,
  where the **series** node is keyed `event:{tenant}:gcal-series:{recurringEventId}`
  (type `event`, `event_type:"meeting_series"`, no attendance of its own). All
  occurrences of one series share it; one-offs have `is_recurring=false` and no
  series node. Note distinct series can share a title — grouping is by
  recurringEventId, not name.
- **person** per participant, keyed `person::{email}` (global, cross-firm). Name
  resolution (Google usually omits attendee displayName): the provided displayName,
  else the graph person directory `_load_person_names` (email→name from existing
  named nodes), else the `name_from_email` heuristic (`pablo.campos@…`→"Pablo
  Campos"; skips ambiguous initials), else the address as fallback. Everyone is
  kept (unlike Notes, which drops the unnameable) — calendar invitees are real.
  Re-ingesting upgrades a node's email label once a name is found.
- **company** per *qualifying* attendee domain (CRM-known — calendar has no
  outbound-correspondence signal), keyed `company::{tenant}::{domain}`.
- **edges**: the owner **and** every other participant relate to the event the
  same way — `person -attended-> event` (one symmetric label, no owner/attendee
  distinction). Plus `person -affiliated_with-> company` and `event -regarding->
  company`. The **`get_person_calendar`** RPC was updated (migration
  `20260625130000`) to resolve co-attendees from `attended` edges in either
  direction, so the reader keeps working.

**Bodies**: an event with a `description` becomes one **firm-wide** `document`
(deduped by iCalUID), linked `event_details -> ` its event node.

**Incremental cursor**: `google-calendar:{tenant}:{mailbox}`, advanced to the run
start on success (overlap is harmless — canonical-key dedup is a transactional
upsert).

---

## Verification

- Unit: `pytest tests/test_adapters/test_calendar.py
  tests/test_adapters/test_calendar_entities.py
  tests/test_adapters/test_calendar_ingest.py`.
- Live smoke: `POST /api/v1/ingest/calendar {"subject":"<mailbox>","max_results":10}`
  → `event` pointers + `attended`/`attended_by` edges at `firm:{tenant}`.
- Read-back: `get_person_calendar(<person_id>)` returns the meetings with
  co-attendees.
- Incremental: re-run with `{"subject":"…","since_last":true}` → cursor advances,
  only changed events re-pulled, no duplicate event nodes (iCalUID merge).
