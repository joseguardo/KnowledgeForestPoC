# Email ingestion — handover

Gmail is the only true email source (`pipeline/pipeline/adapters/gmail.py` +
orchestration in `pipeline/pipeline/api/ingest.py`). The Document adapter can take
an uploaded `.eml`, but that's a dumb one-file→one-document path with none of the
graph logic here.

The extraction stage was **rebuilt from scratch**, keeping all connectivity. The
per-message model is now the canonical `/api/v1/ingest/gmail` endpoint; the legacy
thread-collapsed path has been **removed**.

---

## Legacy thread path (removed 2026-06)

The original `/gmail` collapsed each thread into **one `event`** with person-only
participants (`insert-email` edge fn) + a per-thread private body (`ingest-document`).
It's gone — code deleted, the `ingest-email` edge function deprecated. Kept here as
the motivation for the rebuild:

### Problems it had (found with live data)
- **Companies as people** — every participant hardcoded `type=person`
  (`ingest.py:325`). Role mailboxes (`info@`, `sales@`) and company senders
  ("GoHub Ventures") became persons. The CRM (which knows company domains) was
  never consulted.
- **Bare-email labels** — 363 / 1010 person nodes (36%) labelled with the email.
  Header display names under-captured (first `(role,addr)` occurrence kept); and
  the dedup `merged` branch never upgrades a label, so even the 50 people the CRM
  *does* name stayed email-labelled.
- **Thread collapse** — a whole thread = one event at the latest timestamp;
  per-message sender/direction/cadence lost.

---

## The pipeline (endpoint `/api/v1/ingest/gmail`)

Per-message model, deterministic, no LLM. Code:
`pipeline/pipeline/adapters/email_entities.py` (pure classification + extraction),
per-message parsing in `gmail.py` (`messages_from_thread`, `fetch_messages`), and
orchestration `ingest_gmail` in `api/ingest.py`. Connectivity (auth, `discover_mailboxes`,
per-mailbox `gmail:{tenant}:{mailbox}` cursor, query/backfill window, the NZYME
carve-out) is unchanged from the legacy path.

**Atomic unit: per message** (thread implicit via `thread_id` metadata; no
conversation node). Each email →
- **communication** — pointer type `communication` (shared with Affinidad/Calendar
  comms; **was `message`**). Keyed `message:{tenant}:gmail:{hash}` (**key prefix
  unchanged** — hash of `Message-ID`, fallback synthetic); `occurred_at` = message
  date; metadata `{event_type:email, thread_id, direction, mailbox}` — `event_type`
  is the *medium* (email), like Affinidad's email/call/message communications;
  subject-free label.
- **person** per human address; label = display name.
- **company** per *qualifying* domain, keyed `company::{tenant}::{domain}` so it
  merges with the CRM company; label = CRM name else derived from domain.
  - qualifies if: domain ∈ CRM (always), or we sent outbound to it (correspondent).
- **role mailbox** (`info@`, …) → the company, no person.
- **free-mail** → person only; **own domain** → colleague; **noise** → skipped.

**Edges:**
- `person -sent-> communication` — the sender (a company, for a role-mailbox sender)
- `communication -received-> person` — each recipient (to + cc; persons only)
- `person -affiliated_with-> company` — a person's own company (companies are
  reached via their people, 2-hop).

**Deferred — `communication -about-> company/person`.** An `about` (subject) edge would
make entity-centric queries 1-hop, but it's *inferred*, not observed: "emailed a
Fossa partner" ≠ "about Fossa," derived/platform domains aren't really companies,
and `about→person` just restates `received`. We only want `about` with high
certainty, so it's left out until we can do it well (likely CRM-known companies
only, and/or content-based mentions in step 2). Person↔person correspondence
aggregation (weights/strength) is also a later step.

### Message content (private body)

Each email's subject+body is ingested as a **private `document`** (chunked +
embedded by `ingest-document`), linked `document --content_of-->
communication` (same relationship Affinidad uses for its comms — and for CRM
notes about entities; **was `email_content`, then `communication_content`**).
The communication node stays firm-wide and subject-free; the
body behaves like any other document and the content is participant-private.

Access is the standard per-row `acl uuid[]` model (see
[access-model.md](../access-model.md)) — the old `email_body` sentinel class +
`thread_membership` table + `can_read_thread*` policies were **dropped** (Stage 4):
- the body document (+ its chunks) is written with **`principals = member_uids`** —
  the thread's participants who are platform users (resolved from the message's
  addresses via `resolve_user_ids`). That list becomes the row's `acl`;
- the standard `acl && my_principals()` RLS then authorizes exactly those users;
- an empty participant list ⇒ `acl=[]` ⇒ visible to no one (fail-closed). Verified:
  a member sees the doc+chunks, a non-member and anon see nothing.

Dedup/idempotency: the doc is content-hash keyed (tenant-namespaced), and the
body is ingested **only when the communication pointer is newly `created`** — so the
sender/recipient copies and `since_last` overlaps never re-embed. Semantic
"email about XY" runs over the document/chunks (the communication-node embedding is
label-only). Content is UTF-16-truncated to `max_content_length`.

### Attachments

Real document attachments are ingested as their own `document` nodes, linked
`document --attachment--> communication`, with the **same visibility as the body**
(`principals` = the thread members with accounts). They ride the already-fetched
raw RFC822, so no extra Gmail calls. `_extract_attachments` (gmail.py) keeps only
parts with a filename and `attachment` disposition, dropping inline images,
`image/*`, `text/calendar` invites, `*.p7s` signatures, and anything over
`max_upload_bytes`. Each attachment goes through `DocumentAdapter.process_file`
(real text for PDF/txt/md/eml; Office `.docx/.pptx/.xlsx` get a placeholder node
until parsers are added). Same created-only gating + content-hash dedup as bodies,
so the same file on two emails is one node with two `attachment` edges, and a
failed attachment is logged, not fatal.

> Known wart: re-ingesting emits `link-pointers` 409s ("edge already exists") for
> the `sent`/`received` edges — harmless (no data growth), but noisy; fixable by
> making `link-pointers` upsert-ignore like `ingest-email` does.

### What is NOT ingested

Only genuine human correspondence is ingested. A message is **dropped entirely**
(no event, no entities) when `_is_noise_message` (`gmail.py`) matches — detected
from headers we already receive, deterministic, no LLM:

| Category | Signal |
|---|---|
| Newsletters / mailing lists | `List-Unsubscribe` or `List-Id` present |
| Marketing / product info | usually `List-Unsubscribe` (as above) |
| Automated / login / transactional | `Precedence: bulk\|list\|junk`, or `Auto-Submitted:` ≠ `no` |
| System / bounce | sender is no-reply / mailer-daemon (`_is_noise`, matched anywhere in the local-part — e.g. `comments-noreply@`) |
| Role-mailbox sender | the **From** local-part is a role mailbox (`gmail_drop_sender_localparts`: info / sales / marketing / newsletter) — catches header-less marketing like `info@southsummit.io` |
| Marketing with no machine headers | sender **display name** is a brand/team (`_is_brandy_name`: "team"/"equipo"/"newsletter"/…, or a single dotted/numeric token like "Fun.xyz") |
| Meeting invitations | a `text/calendar` part (any method — REQUEST/REPLY/CANCEL) or Outlook calendar `Content-Class`; handled by the separate calendar path |

This is what stopped "El equipo de Miro" (`your@product.miro.com`) and
"TheSequence" (`thesequence@substack.com`) from being ingested as people, and
keeps calendar invites out of the email graph.

**Residual limit:** a plain mail from a real (non-role) address carrying none of
these signals can still slip through — e.g. a login/OTP from a custom domain, or a
recurring internal agenda email ("Int.IA Daily" sent by a colleague, with no
`text/calendar` part). Distinguishing those needs content/LLM signals, not headers.

### Person names (no email-string labels)

A person's label should be a real name, never the bare address. Two mechanisms:
- **Best name across the batch** (`extract_graph`): a person first seen as a bare
  address upgrades to a real name if any later message names them; never
  downgrades.
- **Label-upgrade on merge** (`insert_pointer_with_dedup`, migration
  `20260624120000_dedup_label_upgrade.sql`): in the `merged` branch, if the stored
  label is a bare email and the incoming label is a real name, the stored label is
  upgraded. Source-agnostic — so the CRM's `full_name` (Affinidad writes the same
  `person::{tenant}::{email}` node) and later email display names both win over an
  email placeholder, going forward. No gmail→CRM coupling; CRM names land whenever
  Affinidad is ingested.

CRM domains are read from the graph's existing `company::{tenant}::{domain}`
nodes (`_load_company_domains`). The write path reuses `insert_pointer`
(→ `insert_pointer_with_dedup`) + `link_pointers` + `ingest_document`, modelled on
the Affinidad adapter — no bespoke email edge function.

### Config (`config.py`)
Comma-separated, sensible defaults:
- `gmail_free_mail_domains` — webmail domains that get a person but never a company.
- `gmail_role_localparts` — role mailboxes that, as a **recipient**, resolve to the
  company (no person).
- `gmail_drop_sender_localparts` — role mailboxes that, as the **sender**, drop the
  whole message as marketing/transactional (narrower than `gmail_role_localparts`;
  default `info,sales,marketing,newsletter`).
- `gmail_skip_noise_senders` (bool, default `True`) — master switch for the
  `_is_noise_message` drop logic; set `False` to ingest everything regardless of
  sender.

### Tests
`tests/test_adapters/test_email_entities.py`, `test_gmail_messages.py`,
`test_email_extraction.py`, and the `/gmail` endpoint tests in `test_gmail.py`.
Run `pytest pipeline/tests`.

### Run it / verify
```bash
# one firm, recurrent window (or {"subject":"x@firm.com","query":"newer_than:3650d"})
curl -XPOST localhost:8000/api/v1/ingest/gmail \
  -H 'content-type: application/json' -d '{"tenant_id":"<uuid>","since_last":true}'
```
Then on KnowledgeForest (`sjiepibqadbdowcizccw`):
```sql
-- per-message nodes exist (emails are type 'communication')
select metadata->>'direction', count(*) from pointers
where type='communication' and metadata->>'event_type'='email' group by 1;
-- private bodies linked to their communications
select count(*) from edges where relationship_type='content_of';
-- private bodies are scoped to their participants (acl = member uids, not public)
select count(*) from pointers where type='document'
  and not acl && array['00000000-0000-0000-0000-000000000001'::uuid];
-- companies / affiliations
select count(*) from pointers where type='company';
select count(*) from edges where relationship_type='affiliated_with';
```

---

## Open steps (designed later)

2. **Content** — subject/body as a per-message private document **(done — see
   "Message content (private body)" above)**; still open: signatures, attachments.
3. **Relationships** — person↔person edges, relationship strength/frequency.
4. **Identity & dedup** — email-label→real-name upgrade rule **(done — see "Person
   names" above)**; still open: role-mailbox→company reconciliation, cross-source
   identity (one human across multiple addresses).
5. **Write path** — **done**: the per-message path is now the canonical `/gmail`
   endpoint; the legacy thread path + `client.ingest_email` are deleted and the
   `ingest-email` edge function is deprecated.
6. **Sync correctness** — Gmail `historyId` vs wall-clock cursor; don't advance the
   cursor past errored messages; concurrency. Also: make `link-pointers`
   upsert-ignore (re-ingest currently logs 409s for existing `sent`/`received` edges).
