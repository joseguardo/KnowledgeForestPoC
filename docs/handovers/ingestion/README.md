# Ingestion — handover

How raw sources become the knowledge graph. One intermediate contract, one typed
graph, deterministic extraction (no LLM), transactional dedup.

## The shared model

Every adapter normalizes to `NormalizedItem` (`pipeline/pipeline/models.py`) —
`kind = pointer | document` — and writes into one graph (Supabase project
**KnowledgeForest**, `sjiepibqadbdowcizccw`):

| Table | Role | Key fields |
|---|---|---|
| `pointers` | nodes | `type` (company/person/communication/document/event/…), `canonical_key` (unique = identity), `label`, `occurred_at`, `acl uuid[]` |
| `edges` | relationships | `source_id`, `target_id`, `relationship_type`, `why`, `weight`; unique `(source,target,type)` |
| `attributes_kv` | facts | `(pointer_id, key)` unique → upsert; `value`, `data_type` |
| `document_chunks` | bodies | `(pointer_id, sequence)`; per-chunk embedding + access |

**Identity & dedup:** the `insert_pointer_with_dedup` RPC merges on a matching
`canonical_key`; trigram+embedding similarity only flags lookalikes for review.
**Person email-overlap merge:** because sources key the same human by different
addresses (team directory by their kibo address, Affinidad by their primary/nzyme
address), a `person` insert first folds into any existing person that already
carries one of its emails (in `metadata.emails`) or is keyed on one — *before*
name/canonical matching. The survivor keeps its `canonical_key` and unions the
incoming emails, so the human stays a single node and the merge is durable across
re-syncs (a source keying by the other address still resolves to the survivor).
Migration `20260629150000_person_email_overlap_dedup.sql`; only `person` is
affected (companies stay keyed by tenant+domain). Caveat: a shared/role mailbox
appearing in two people's email lists could over-merge — keep role inboxes as
their own nodes.
**Access:** every row carries `acl uuid[]` — the principals (tenant ids, user
ids, public sentinel) that may read it — and RLS is `acl && (select
my_principals())`. People are one **global** `person::{email}` node across firms;
each firm's ingest unions its tenant into the node's acl, while edges/attributes
stay per-tenant. See [access-model.md](../access-model.md). (The legacy
`access_class_id`/`can_read_class`/`thread_membership` mechanisms were **dropped**
in Stage 4, migration `20260625170000_drop_legacy_access_model.sql`.)

## Sources

- **Gmail** — Workspace threads (`adapters/gmail.py`). See [emails.md](emails.md).
- **Calendar** — Workspace primary calendars, same SA as Gmail
  (`adapters/calendar.py`). Firm-wide events; see [calendar.md](calendar.md).
- **Notes** — `meeting_transcripts` from a source Supabase (`adapters/notes.py`).
  See [notes.md](notes.md).
- **Affinidad** — Kibo's in-house CRM Postgres (`adapters/affinidad.py`); the
  authority on companies (domains + names), people, opportunities, list
  memberships (deals) and notes. **Does NOT ingest meetings or emails** — Calendar
  is the source of truth for meetings and Gmail for emails, so the CRM connector
  skips those interaction types (`fetch_events` filters `type NOT IN
  ('meeting','email')`) to avoid duplicate communication nodes. (The ~4.8k calendar
  meetings that the CRM had previously double-created were merged onto their
  Google-Calendar nodes, tagged `metadata.merged_affinity_key`, on 2026-06-30.)
- **Document / Web / Conversation / Structured** — single documents or explicit
  pointers (`adapters/{document,web,conversation,structured}.py`).

A visual version of this overview (schemas, per-source cards, extraction modes)
is published as a Claude artifact; ask for the link.

## Known problems (2026-06)

- **Companies typed as `person`** — Gmail/Notes had no person/company logic; every
  address became a `person`. **Fixed** for both: Gmail (emails.md) and Notes
  (notes.md) now share `classify_address`. Other sources unaffected.
- **Bare-email labels** — 36% of person nodes were labelled with the email, not a
  name. Two causes: under-captured header display names, and the dedup `merged`
  branch never upgrading a label. Tracked for step 4.
