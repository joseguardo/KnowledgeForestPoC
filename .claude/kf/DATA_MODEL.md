# KnowledgeForest — data model & operations reference

Shared knowledge for the `/kf-*` commands. This is a tenant-scoped knowledge
graph: typed **pointers** (entities) connected by **edges**, enriched with
**attributes**, optionally chunked **documents**, with hybrid retrieval
(text + semantic + behavioral + graph) and an access-class security gate.

## Connecting

Connection details are NOT hardcoded — read them from the project's env so the
commands work against any KnowledgeForest project (original or a duplicate):

- Frontend / read side — `.env.local`: `VITE_SUPABASE_URL`,
  `VITE_SUPABASE_ANON_KEY`, `VITE_KIBO_TENANT_ID`.
- Backend / write side — `pipeline/.env`: `SUPABASE_URL`,
  `SUPABASE_SERVICE_ROLE_KEY`.
- Edge functions: `{SUPABASE_URL}/functions/v1/<name>`. PostgREST RPC:
  `{SUPABASE_URL}/rest/v1/rpc/<fn>`. Both need `Authorization: Bearer <key>`
  and `apikey: <key>` headers.
- **Ingestion / admin** → service_role key. **Retrieval** → anon key (public
  rows only) or a signed-in user's JWT (their clearance). RLS is enforced either
  way; the service_role bypasses it.
- If the Supabase MCP is connected to this project, `execute_sql` /
  `apply_migration` can be used directly instead of PostgREST.

## Tables (public schema)

- **pointers** — entities. `id`, `label`, `type` (pointer_type enum),
  `canonical_key` (unique when set — the dedup identity), `metadata` jsonb,
  `embedding` vector(1536), `search_text` tsvector (auto-maintained by trigger),
  `occurred_at` (domain event time), `access_class_id`.
- **attributes_kv** — key/value facts on a pointer. `pointer_id`, `key`,
  `value` jsonb, `data_type`, `sort_order`, `source`, `access_class_id`.
  **UNIQUE(pointer_id, key)** → upsert on conflict.
- **edges** — typed relationships. `source_id`, `target_id`,
  `relationship_type`, `why`, `payload`, `weight`, `access_class_id`.
  **UNIQUE(source_id, target_id, relationship_type)**.
- **document_chunks** — `pointer_id`, `sequence`, `content`, `heading`,
  `embedding`, `access_class_id`. **UNIQUE(pointer_id, sequence)**.
- **timeseries_data** — `pointer_id`, `ts`, `metric_name`, `value` jsonb.
- **schema_vocabulary** — `term`, `category` ∈ {edge_type, attribute_key,
  pointer_type}, `description`, `embedding`. Drives query planning; keep it
  current when you introduce new edge/attr/type conventions, then re-run
  `backfill-vocab-embeddings`.
- **access_classes** / **access_grants** / **tenant_members** — security model
  (below). **tenants** — tenant registry.
- Forest (auto-computed, don't hand-edit): `tenant_trees`, `tenant_branches`,
  `tenant_pointer_assignments`, `tenant_coaccess(_cursor)`,
  `tenant_structure_events`, `tenant_structure_mapping`, `naming_cache`,
  `forest_computation_jobs`.
- **query_paths** (behavioral log), **duplicate_flags** (dedup review queue),
  **system_config** (dedup thresholds).

## Enums & conventions

- **pointer_type**: company, person, sector, geography, regulation, document,
  timeseries, agent, skill, tool, flow, component, architecture, best_practice,
  meta, event.
- **attribute_data_type**: string, number, boolean, json, date, url.
- **edge relationship_type** (common): primary_sector, ceo, competitor,
  hq_location, jurisdiction, related, part_of, contains, powers, guides,
  follows, ensures_compliance, uses_skill, uses_tool, uses_agent; calendar:
  `attended` (person→event), `attended_by` (event→person), `regarding`
  (event→company); document: `describes`.
- **attribute keys** (canonical, from vocabulary): CEO, Rev, HQ, Location,
  Title, Stage, PE, Market, CAGR, GDP, Scope, Enacted, Conf, occurred_at.
- **canonical_key** (the dedup identity — make it stable & deterministic):
  documents `doc:<sha256(content)>`; calendar events `event:<owner>:<start>`;
  entities a stable slug like `company:openai`, `person:jensen-huang`. Omit only
  if you want pure fuzzy dedup.

## Dedup (how writes resolve)

All entity writes go through `insert_pointer_with_dedup`:
1. Exact `canonical_key` match → returns that pointer (`merged`).
2. Else trigram(label) + cosine(embedding); top score ≥ `auto_merge_threshold`
   (default 0.8, in system_config) → `merged` (only within the same access
   class or same canonical identity); ≥ `review_threshold` (0.4) → inserts a new
   pointer and files a `duplicate_flags` row (`pending_review`); else `created`.
Re-ingesting a `merged` entity still upserts its attributes (enrichment) but
never clobbers an existing `occurred_at`.

## Ingestion schemes (edge functions, service_role)

Pick by input shape:

- **insert-pointer** — one entity. Body: `{ label, type, canonical_key?,
  metadata?, occurred_at?, access_class?, attributes?: [{ key, value, data_type?,
  sort_order?, source?, access_class? }] }`.
- **ingest-batch** — many entities (**≤50 per call**, chunk larger sets).
  Body: `{ items: [<insert-pointer item>...], source?, access_class? }`.
  Sequential so in-batch dedup works.
- **ingest-document** — long text. Body: `{ title, content, occurred_at?,
  metadata?, chunk_size?, access_class?, link?: { target_id | target_canonical_key
  | target_label, relationship_type?, why? } }`. Chunks on paragraphs, embeds
  each, dedups on content hash, optionally links doc→entity.
- **ingest-calendar** — meetings/emails. Body: `{ owner: { label, type?,
  canonical_key? }, events: [{ title, start, end?, location?, notes?,
  event_type?, from?, canonical_key?, attendees?: [{ label, type? }], company? }],
  access_class?, source? }`. Creates an `event` pointer per meeting + people/
  company pointers + attended/attended_by/regarding edges. Defaults to
  `confidential`.
- **link-pointers** — explicit edge between two existing pointers. Body:
  `{ source_id, target_id, relationship_type?, why?, payload?, weight? }`.

Every function reads `OPENAI_API_KEY` (set as an edge-function secret) for
`text-embedding-3-small`; without it, rows are created with null embeddings
(text/attribute search still works, semantic doesn't).

## Retrieval procedures

- **query-knowledge** edge function (natural language; the default path). POST
  `{ query, tenant_id?, mode?: "search" | "answer" | "explore" }`. It embeds the
  query, pulls regex + semantic hints (`get_query_context_v2`), asks gpt-4o-mini
  for a 1–3 step plan, and executes it under the **caller's** RLS. `answer` mode
  also composes a cited summary; `explore` adds follow-up suggestions. Call with
  the anon key (public) or a user JWT (their clearance). `tenant_id` defaults to
  the Kibo tenant.
- **Direct RPCs** (deterministic / structured; via MCP `execute_sql` or
  `/rest/v1/rpc/<fn>`):
  - `search_hierarchy_aware(p_query, p_tenant_id, p_embedding?, p_type_filter?,
    p_limit)` — 3-layer (search → behavioral co-access → graph), attributes
    inline. The main retrieval RPC.
  - `search_knowledge(p_query, p_embedding?, p_type_filter?, p_limit)` — hybrid
    trigram+embedding+attribute+fulltext fused with RRF.
  - `search_pointers(p_types[], p_date_from, p_date_to, p_attr_filters,
    p_query_text, p_embedding, p_limit, p_offset)` — deterministic filtered
    list; returns `{ total, results:[...] }`. Use for "all X of type Y between
    dates with attr Z".
  - `traverse_graph(p_start_ids[], p_edge_types[], p_direction, p_target_type,
    p_depth, p_limit)` — follow edges (depth capped at 3).
  - `get_pointer_subgraph(p_pointer_id)` — full neighborhood (attrs, in/out
    edges, chunks, latest timeseries).
  - `get_person_calendar(p_person_id)` — that person's events + co-attendees.
  - `get_tenant_forest(p_tenant_id)` — tree/branch structure for the 3D view.
  - `get_query_context_v2` / `get_semantic_hints` — planner hints.
  - `get_dedup_stats` — thresholds + flag counts.
- Embeddings for direct RPCs: generate the query embedding with OpenAI
  `text-embedding-3-small` (1536 dims) and pass as a JSON-array string, or pass
  null for text-only.

## Behavioral loop

`log-query-path` records which pointers were surfaced together → accumulates
`tenant_coaccess` weights → the nightly `compute-forest` (cron `0 3 * * *`)
clusters them into trees/branches via union-find + LLM naming. Retrieval's
co-access layer reflects this. You don't call compute-forest directly; it runs
on schedule or when the change threshold trips.

## Security (access classes)

Classes: `public` (id `00000000-0000-0000-0000-000000000001`, readable by all),
`confidential`, `restricted`. Ingestion stamps a class on the pointer and its
attributes/chunks/edges. Reads are gated by `can_read_class(access_class_id)`:
public always; otherwise the caller (`auth.uid()`) needs a direct user grant or
a grant via a tenant they belong to (`access_grants` + `tenant_members`).
`query-knowledge` forwards the caller's JWT, so restricted content is filtered
out of hints, results, AND the composed answer for under-cleared callers. Grant
management is service_role-only (`access_grants` has no public policy).
