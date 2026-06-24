# Meeting-notes ingestion — handover

Notes are meeting rows from a source Supabase project (the Notion "Meeting
Notes" mirror, table `meeting_transcripts`), read over a least-privilege
Postgres role. Adapter: `pipeline/pipeline/adapters/notes.py`; deterministic
extraction: `pipeline/pipeline/adapters/notes_entities.py`; orchestration:
`ingest_notes` in `pipeline/pipeline/api/ingest.py`.

The extraction stage was **rebuilt from scratch to mirror the Gmail rework**,
keeping all connectivity (source DSN, owner-map team tables, per-tenant
`notes:{tenant}` cursor, Confidential body tier). Notes and email now share one
classification brain — `classify_address` — so an address means the same thing
in both.

---

## Legacy path (replaced 2026-06)

The old `_ingest_meeting` collapsed each meeting into a single `ingest-calendar`
edge-function call with **person-only** participants and a **free-text** company,
plus a per-meeting body. Its problems (the motivation for the rebuild):

- **Companies as people** — every attendee email became a `person`; no
  role-mailbox / free-mail / noise handling; the CRM was never consulted.
- **Free-text company nodes** — `external_org` went straight to a label-keyed
  company, so "Poseidon", "Poseidon Inc." and "poseidon-vc" were three nodes.
- **`name:{slug}` people** — an owner whose email didn't resolve got a
  slug-keyed person node that could never dedup.
- **Bespoke edge function** — went through `ingest-calendar` instead of the
  shared `insert_pointer` + `link_pointers` write path.

The `client.ingest_calendar` method is **deleted**; the `ingest-calendar` edge
function is **deprecated** (no caller remains).

---

## The pipeline (endpoint `/api/v1/ingest/notes`)

Per-meeting model, deterministic, no LLM. The adapter fetches rows and resolves
the owner's name → email via the firm's team tables (`owner_map`), exposing the
firm's **own email domains** (derived from those team emails) so colleagues
classify as person-only. `notes_entities.extract_graph` then produces, per row:

- **event** — the meeting. Keyed `event:{tenant}:meetingnote:{page_id}`;
  `occurred_at` = `meeting_start` (falls back to `last_edited_time`); label =
  cleaned title; metadata `{event_type: meeting, page_id}`.
- **person** per resolvable human (owner + human attendees). Keyed
  `person::{tenant}::{email}`. Attendee emails carry no display name, so labels
  start as the address and are upgraded later (see "Names").
- **company** per *qualifying* attendee domain, keyed
  `company::{tenant}::{domain}` so it merges with the CRM company; label = CRM
  name else derived from the domain.
- **role mailbox** (`info@`, …) → the company, no person.
- **free-mail** → person only; **own domain** → colleague (person only);
  **noise** (`no-reply@`, …) → skipped.

A domain **qualifies** only if it is known to the CRM (`crm_domains`, from the
graph's existing `company::{tenant}::{domain}` nodes via `_load_company_domains`).
Notes have no "outbound correspondence" signal, so unlike email there is no
correspondent set — CRM-known is the only qualifier.

**Edges:**
- `person -attended-> event` — owner and every human attendee. No separate
  owner/hosted relationship; attendance is the only participation edge.
- `person -affiliated_with-> company` — an attendee's own company.
- `event -about-> company` — the meeting's named company, **gated**: emitted
  only when the free-text `external_org` resolves to a CRM company **and** a
  member of that company actually attended (an attendee at that same domain).
  Both signals must agree onto the one domain-keyed node.

### The `about` gate (why it's strict)

`external_org` is free text and genuinely names what the meeting is about — but
to keep `about` high-certainty we require corroboration: the named org must (a)
resolve to a CRM company and (b) have someone in the room (an attendee at that
domain). If `external_org` resolves but nobody from that domain attended (e.g.
the contact used a personal Gmail), **no `about` edge and no orphan company
node**. If it doesn't resolve, nothing. This is tunable in `extract_graph` — the
looser reading ("any external attendee present") is a one-line change.

`external_org` resolution normalizes the free text (`normalize_company_name`:
lowercase, strip punctuation + legal/VC suffixes like `inc`/`ltd`/`vc`/
`ventures`) and matches it against normalized CRM company names
(`build_company_index`). So "Poseidon", "Poseidon Inc." and "poseidon-vc" all
collapse onto `company::{tenant}::{poseidon.vc}`.

### Owner resolution / dropping

The owner is a name in `meeting_transcripts`, resolved to an email via the
firm's team tables (`owner_map_tables`, e.g. `nzyme_team`). **Resolved → person
+ `attended`. Unresolved → dropped** (no `name:{slug}` fallback). The team
tables are the firm's people directory; there is no fuzzy CRM person-name lookup
(it would risk false identity merges).

### Body (summary)

Each meeting's `notion_summary` is ingested as a **document** (chunked +
embedded), linked `document --meeting_notes--> event`. Access:

- **Shareable** → the firm class `firm:{tenant}` (public-within-firm).
- **Confidential** → a private class `meetingnote:{tenant}:{page_id}`, ensured
  **before** ingest (fail closed) and granted to the owner + attendees who have
  platform accounts (`resolve_user_ids` → `ensure_user_grant`).

The write path is the shared `insert_pointer` (→ `insert_pointer_with_dedup`) +
`link_pointers` + `ingest_document` — no bespoke edge function.

### Names

Attendee person nodes start labelled with the bare email (the source has no
display names). They upgrade to real names via the source-agnostic
**label-upgrade on merge** (migration `20260624120000_dedup_label_upgrade.sql`):
when Affinidad (CRM) or Gmail later writes the same `person::{tenant}::{email}`
node with a real name, the email label is replaced. The owner is named directly
(team-table `name`).

### Config (`config.py`)
`notes_firms` (JSON array of `{tenant_id, source_dsn, table?, content_fields?,
confidential_field?, owner_map_tables?}`) or the single-firm `notes_source_dsn` +
`notes_default_tenant_id`. Shared with email: `gmail_free_mail_domains`,
`gmail_role_localparts`.

### Tests
`tests/test_adapters/test_notes_entities.py` (pure extraction: normalization,
event/owner/attendee/about), `test_notes.py` (adapter: row mapping, owner
resolution, own-domain derivation, config), `test_notes_ingest.py` (endpoint
orchestration: graph write, confidential grants, owner drop). Run
`pytest pipeline/tests`.

### Run it / verify
```bash
curl -XPOST localhost:8000/api/v1/ingest/notes \
  -H 'content-type: application/json' -d '{"tenant_id":"<uuid>","since_last":true}'
```
Then on KnowledgeForest (`sjiepibqadbdowcizccw`):
```sql
-- meetings are events; participants attend
select count(*) from pointers where type='event'
  and metadata->>'event_type'='meeting';
select count(*) from edges where relationship_type='attended';
-- companies reconciled to CRM domains; meeting-about links
select count(*) from edges where relationship_type='affiliated_with';
select count(*) from edges where relationship_type='about';
-- bodies linked to their meeting
select count(*) from edges where relationship_type='meeting_notes';
```

---

## Open steps

- **`about` precision** — currently CRM-resolved + member-present only; revisit
  if too few `about` edges land (relax to any external attendee, or resolve
  `external_org` against company *names* even without a domain match).
- **Attendee names** — depend on CRM/Gmail label-upgrade; consider pulling
  display names if the source ever carries them.
- **Identity & dedup** — role-mailbox→company reconciliation, one human across
  multiple addresses (shared with email step 4).
