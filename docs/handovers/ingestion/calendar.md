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
- **communication** node (`type=communication`, `event_type:"meeting"`; was `event`),
  keyed **`communication:{tenant}:gcal:{iCalUID}`**. Because `iCalUID` is
  stable across every attendee's copy of a meeting, the same meeting read from N
  calendars **collapses to one node** (edges accumulate). `occurred_at` = start;
  metadata = `{event_type:"meeting", location, end, organizer_email, provider,
  calendar_email, is_recurring, series_id}`.
- **recurring meetings**: an occurrence with a `recurringEventId` is tagged
  (`is_recurring=true`, `series_id`) and linked `event -instance_of-> series`,
  where the **series** node is keyed `communication:{tenant}:gcal-series:{recurringEventId}`
  (type `communication`, `event_type:"meeting_series"`, no attendance of its own). All
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
(deduped by iCalUID), linked `content_of -> ` its event node (was `event_details`,
unified with the other content edges in `20260629130000`).

**Incremental cursor**: `google-calendar:{tenant}:{mailbox}`, advanced to the run
start on success (overlap is harmless — canonical-key dedup is a transactional
upsert).

---

## Verification

- Unit: `pytest tests/test_adapters/test_calendar.py
  tests/test_adapters/test_calendar_entities.py
  tests/test_adapters/test_calendar_ingest.py`.
- Live smoke: `POST /api/v1/ingest/calendar {"subject":"<mailbox>","max_results":10}`
  → `communication` pointers + `attended` edges (symmetric — no `attended_by`) at `firm:{tenant}`.
- Read-back: `get_person_calendar(<person_id>)` returns the meetings with
  co-attendees.
- Incremental: re-run with `{"subject":"…","since_last":true}` → cursor advances,
  only changed events re-pulled, no duplicate event nodes (iCalUID merge).

---

## Rework — updates/cancellations + notes convergence (implemented)

Implemented in `pipeline/pipeline/supabase_rest.py` (thin PostgREST passthrough),
`pipeline/pipeline/event_sync.py` (the app-layer reconciliation/matching), and the
calendar + notes handlers in `pipeline/pipeline/api/ingest.py`. Unit-tested in
`tests/test_supabase_rest.py`, `tests/test_event_sync.py`,
`tests/test_adapters/test_calendar.py`, `test_calendar_ingest.py`, `test_notes_ingest.py`
(full suite green). **Live/branch verification still pending** (see below).

The connector above was **insert-only / first-write-wins**, which left three gaps,
all rooted in `insert-pointer` only unioning `acl` and setting `occurred_at`-if-null
on merge (`supabase/functions/insert-pointer/index.ts:142`):

1. **Cancellations are silently dropped** (`adapters/calendar.py` filter on
   `status==cancelled`) → a meeting ingested then cancelled stays in the graph forever.
2. **Moves/retitles don't update the node** → a re-timed meeting keeps its old
   `occurred_at`; `end`/`location`/`title` never change.
3. **Removed attendees leave stale `attended` edges** (edges are insert-only; no
   unlink RPC; the pipeline client has only write methods).

And **notes never converge with calendar meetings**: notes create their own `event`
node and `meeting_transcripts` carries no iCalUID, so one real meeting → two nodes.

**Decisions (confirmed with user):**
- Cancelled meeting → **soft-mark**: keep node, `metadata.status="cancelled"` +
  `cancelled_at`, drop calendar-sourced attendance edges. Reversible.
- Changed meeting → **full source-of-truth**: overwrite time/title/location/end, add
  new attendees, **delete attendees no longer present** (calendar-sourced only).
- Notes ↔ calendar → **bidirectional heuristic convergence**, matching on
  **tenant + start time at clock-hour granularity + normalized title** (note titles
  are lifted from the calendar event, so title+hour is expected to suffice — tune
  later). Calendar event is the canonical meeting node; a note **attaches** to it and
  creates its own event **only when no calendar meeting matches**. Works in both
  ingestion orders.

**Key safety detail — edge provenance.** Every `attended` edge carries
`payload.source` (`"calendar"` | `"notes"`). Calendar reconciliation prunes only
`source="calendar"` edges absent from the new attendee set, so it never wipes
note-contributed attendees. Node `metadata` updates are a **shallow merge** (calendar
keys win) so overwrite never erases note-contributed keys.

**Architecture principle.** Edge functions stay **dumb mechanical create primitives**
(embed, chunk, acl-resolve, insert); **all** matching, dedup, filtering, identity
resolution and update/cancel/merge **decisions live in the pipeline**. An edge function is
always handed a **concrete UUID the app already resolved** — it never looks anything up.
Mutations are plain **PostgREST PATCH/DELETE** issued from the pipeline with the
service-role key. → No new edge functions, no new RPCs, no `overwrite` flag.

**New surface — `pipeline/pipeline/supabase_rest.py`** (thin, logic-free PostgREST
passthroughs, generalising the inline httpx pattern in `connector_state.py`):
- `select_pointers(filters)` — e.g. `type=eq.communication`, `acl=cs.{tenant_uuid}`,
  `occurred_at=gte/lte` (backs notes→calendar matching + move/cancel existence checks;
  the orphan-note absorb path instead queries `type=eq.event`, the notes-side marker).
- `patch_pointer(id, fields)` — move/retitle, soft-cancel.
- `select_edges` / `patch_edges` / `delete_edges` — e.g.
  `target_id=eq.X&relationship_type=eq.attended&payload->>source=eq.calendar`.
Node/document creation still uses the existing `insert_pointer` / `ingest_document` /
`link_pointers` edge functions, always with a resolved `target_id`.

**Connector changes.**
- `adapters/calendar.py`: surface cancelled iCalUIDs (don't discard); treat
  owner-declined on a previously-kept meeting like a cancellation.
- `adapters/calendar_entities.py`: tag `attended` edges with `payload.source="calendar"`.
- `api/ingest.py` (calendar), all app-layer:
  - **move/retitle** — `select_pointers` by canonical_key → `patch_pointer`
    `{occurred_at, label, metadata}` (metadata shallow-merged in Python) or create;
  - **attendee reconcile** — diff desired vs existing `source="calendar"` `attended`
    edges in Python → `link_pointers` adds, `delete_edges` removals (note edges untouched);
  - **cancel** — `patch_pointer` `status=cancelled`/`cancelled_at` + `delete_edges`
    calendar attendance; no-op if never ingested;
  - **absorb** — for new events, `select_pointers` same-hour; re-point an orphan
    note-event's doc edge (`patch_edges`) and delete it.
- `adapters/notes_entities.py` / `api/ingest.py` (notes): before creating a note event,
  `select_pointers(type=communication, acl=tenant, occurred_at in containing hour)` — i.e.
  look for an existing **calendar meeting** (keyed `…:gcal:…`) — + normalized-title
  match **in Python** → resolve exactly one `pointer_id`. On match, `ingest_document(link=
  {"target_id": pointer_id, "relationship_type":"content_of"})` + extra attendees
  (`payload.source="notes"`) + `about`; **no new event node**. On no match, create as today.
  Confidential bodies keep their own private acl on the firm-wide event node.

**Execution order:** (1) `supabase_rest.py` data-access layer → (2) calendar
updates/cancellations/moves → (3) notes → calendar attach (calendar-first) →
(4) bidirectional absorb (re-point + delete orphan note-event).

**Added verification:** exercise `supabase_rest.py` against a Supabase branch (select
filter, patch fields, `payload->>source` delete only removes calendar edges, patch re-point);
move-then-reingest asserts `occurred_at`/`end` update (regression for first-write-wins);
run calendar→notes and notes→calendar for one meeting → single converged node.
