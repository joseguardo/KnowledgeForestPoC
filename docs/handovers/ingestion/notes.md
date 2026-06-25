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

- **event** — the meeting. Keyed by **meeting identity** (`event_key`): when the
  raw title carries a scheduled-slot timestamp (`… 2026-06-25T09:30:00…`, captured
  as `scheduled_at` before `_clean_title` strips it) →
  `event:{tenant}:meeting:{hash(title+slot)}`; else falls back to
  `event:{tenant}:meetingnote:{page_id}`. So the **two/three Notion note-pages of
  one meeting** (different note-takers, different `page_id`) collapse to **one
  event** — while distinct occurrences (different slot) stay separate. Each
  note-page's body stays its **own** `document` linked `meeting_notes -> ` that
  one event (notes don't merge; provenance per-doc via `page_id`). `occurred_at` =
  `scheduled_at` ?? `meeting_start` ?? `last_edited`; label = cleaned title.
- **person** per **nameable** human (owner + attendees we can name). Keyed
  `person::{tenant}::{email}`; **label = the real name, never the email**. The
  email is stored as an **attribute** (`attributes_kv` key `email`), not the
  label. An attendee whose email resolves to no name is **dropped** (see
  "Names"). The canonical key keeps the email — that's the cross-source dedup
  identity, not a display value.
- **company** per *qualifying* attendee domain, keyed
  `company::{tenant}::{domain}` so it merges with the CRM company; label = CRM
  name else derived from the domain. Asserted from the domain regardless of
  whether the attendee could be named.
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

Naming gates only the *person* (below). An attendee at the resolved domain still
satisfies the `about` gate **even if we couldn't name them** — attendance is
observed regardless, and the company is CRM-known so no orphan is created.

`external_org` resolution normalizes the free text (`normalize_company_name`:
lowercase, strip punctuation + legal/VC suffixes like `inc`/`ltd`/`vc`/
`ventures`) and matches it against normalized CRM company names
(`build_company_index`). So "Poseidon", "Poseidon Inc." and "poseidon-vc" all
collapse onto `company::{tenant}::{poseidon.vc}`.

### Owner resolution / dropping

The owner is a name in `meeting_transcripts`, resolved to an email via the
firm's team tables (`owner_map_tables`, e.g. `nzyme_team`). **Resolved → person
(label = the team-table name, email as attribute) + `attended`. Unresolved →
dropped** (no `name:{slug}` fallback).

### Body (summary)

Each meeting's `notion_summary` is ingested as a **document** (chunked +
embedded), linked `document --meeting_notes--> event`. Access:

- **Shareable** → the firm class `firm:{tenant}` (public-within-firm).
- **Confidential** → a private class `meetingnote:{tenant}:{page_id}`, ensured
  **before** ingest (fail closed) and granted to the owner + attendees who have
  platform accounts (`resolve_user_ids` → `ensure_user_grant`).

The write path is the shared `insert_pointer` (→ `insert_pointer_with_dedup`) +
`link_pointers` + `ingest_document` — no bespoke edge function.

### Names (a person pointer's label is always a name)

The source `attendee_emails` column carries only addresses. A person pointer's
label must be a **real name**, never the email — the email is an attribute. So an
attendee's name is resolved (in `extract_graph`, via `name_by_email`) from, in
precedence order:

1. the firm's **team directory** — `team_names` (email → name) from the same
   `owner_map` team tables, for internal colleagues who attend;
2. the **CRM/graph person directory** — `_load_person_names` reads existing
   `person::{tenant}::{email}` nodes whose label is already a real name (Affinidad
   `full_name`, Gmail display names), excluding bare-email labels;
3. the owner's own row name for the owner;
4. the **email local-part** itself, when it is *confidently* a name —
   `name_from_email` (`pablo.campos@…` → "Pablo Campos"). Conservative: needs ≥2
   alphabetic tokens (≥2 chars each), so a single mashed token
   (`claudiagarcia@…`), an initial (`j.carazo@…`), digits, or a generic/role word
   (`sales.team@…`) all → no name.

**No name from any of these → the attendee is dropped** (no person, no
`attended`, no `affiliated_with`). This is the "resolve via CRM, else drop" rule
from the owner, extended to attendees — with the local-part heuristic as a last
confident resort so external attendees aren't lost when the CRM has no entry.
**Operational consequence:** for a tenant with no CRM/team match and an
un-parseable address, the attendee is still dropped. Externals captured by the
heuristic become `person` nodes but get **no company** node unless their domain
is CRM-known (company qualification is unchanged — CRM-only).

The label-upgrade migration `20260624120000_dedup_label_upgrade.sql` is now a
legacy/no-op path for new Notes data (we no longer write email labels), but still
fires usefully when a named Notes person merges with a Gmail node that *is* still
email-labelled (Gmail keeps its email-label fallback for now).

> **Gmail is unchanged.** This name-only rule is Notes-only; `email_entities`
> (Gmail) still uses its `name or email` label fallback.

### Same-name people → review flags (DB, pipeline-wide)

People are keyed by email, so one human with two addresses (or the same human
across two tenants) is two `person` nodes. `insert_pointer_with_dedup`'s flag
loop used to **skip** any pair with differing non-null canonical_keys
("declared-distinct", migration `20260622150000`), so same-name/different-email
people were never surfaced. Migration `20260625120000_dedup_flag_same_name_persons`
**exempts persons whose full name matches** (case-insensitive, ≥2 tokens) from
that skip → they get a `duplicate_flags` row (`resolution='pending'`) for review.
**Review-only — no auto-merge** (there is no node-merge mechanism; deferred). This
also flags cross-tenant same-person pairs (kept intentionally, for visibility).

### Config (`config.py`)
`notes_firms` (JSON array of `{tenant_id, source_dsn, table?, content_fields?,
confidential_field?, owner_map_tables?}`) or the single-firm `notes_source_dsn` +
`notes_default_tenant_id`. Shared with email: `gmail_free_mail_domains`,
`gmail_role_localparts`.

### Tests
`tests/test_adapters/test_notes_entities.py` (pure extraction: normalization,
event/owner/attendee/about, name-only labels + email attribute, unnamed-attendee
drop), `test_notes.py` (adapter: row mapping, owner resolution, own-domain +
`team_names` derivation, config), `test_notes_ingest.py` (endpoint orchestration:
graph write with email attributes, confidential grants, owner/unnamed-attendee
drop, `_load_person_names`). Run `pytest pipeline/tests`.

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
-- no NEW person is labelled with a bare email; email lives as an attribute
select count(*) from pointers where type='person' and label ~ '@' and label !~ '\s';
select count(*) from attributes_kv where key='email';
```

---

## Open steps

- **`about` precision** — currently CRM-resolved + member-present only; revisit
  if too few `about` edges land (relax to any external attendee, or resolve
  `external_org` against company *names* even without a domain match).
- **Attendee names** — resolved from team/CRM directory, else the attendee is
  dropped (so attendance is only as complete as the CRM). Revisit if too many
  real attendees are dropped (e.g. ingest Affinidad first, or accept a fallback).
- **Identity & dedup** — role-mailbox→company reconciliation, one human across
  multiple addresses (shared with email step 4).
