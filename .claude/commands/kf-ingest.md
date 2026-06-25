---
description: Ingest information of any type into the KnowledgeForest graph (auto-routes to the right scheme)
argument-hint: <paste/describe what to ingest, or a file path> [--class public|confidential|restricted]
allowed-tools: Read, Bash, mcp__claude_ai_Supabase__execute_sql
---

You are ingesting information into a KnowledgeForest knowledge graph. Take the
input below, figure out the correct ingestion scheme, build valid payloads, and
write it — generalized over whatever shape the input is.

Input:
$ARGUMENTS

## Procedure

1. **Ground yourself.** Read `.claude/kf/DATA_MODEL.md` for tables, the
   `pointer_type`/edge/attribute conventions, dedup semantics, the edge-function
   request shapes, and the access-class model.

2. **Get the connection.** Read `pipeline/.env` for `SUPABASE_URL` +
   `SUPABASE_SERVICE_ROLE_KEY` (ingestion needs the service_role key). If
   `pipeline/.env` is missing, fall back to the Supabase MCP `execute_sql`
   against the active project. Never print the service_role key.

3. **Classify the input** into one (or several) ingestion schemes:
   - One entity → `insert-pointer`.
   - A list of entities → `ingest-batch` (**≤50 items per call**; chunk more).
   - Long-form text / a document file → `ingest-document` (with a `link` if it's
     clearly about a known entity).
   - Meetings / calendar / emails → `ingest-calendar`.
   - An explicit relationship between two existing pointers → `link-pointers`
     (resolve ids first; by `canonical_key` or `label`).
   - Mixed input → split it and run several calls in dependency order
     (entities first, then documents/edges that reference them).

4. **Map fields carefully:**
   - Choose `type` from the `pointer_type` enum; never invent a type.
   - Set a stable deterministic `canonical_key` (see the conventions) so re-runs
     dedup instead of duplicating. Omit only if fuzzy dedup is intended.
   - Turn facts into `attributes` using the canonical keys (CEO, Rev, HQ, CAGR,
     …) where they fit; put loose context in `metadata`.
   - Use real `occurred_at` for time-anchored items (events, dated docs).
   - `access_class`: default `public`; honor a `--class` flag in the input;
     calendar defaults to `confidential`. Apply consistently to linked rows.

5. **Confirm before writing if the action is large or ambiguous** (>20 items,
   destructive merges, or unclear typing): show the planned calls + a sample
   payload and ask. Otherwise proceed.

6. **Execute.** POST to `{SUPABASE_URL}/functions/v1/<fn>` with headers
   `Authorization: Bearer <service_role>`, `apikey: <service_role>`,
   `Content-Type: application/json`. Example:
   ```bash
   curl -s -X POST "$SUPABASE_URL/functions/v1/insert-pointer" \
     -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
     -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
     -H "Content-Type: application/json" \
     -d '{ ...payload... }'
   ```

7. **Report** per item/call: `created` / `merged` / `pending_review` (+ pointer
   ids), any edges made, and anything that landed in the dedup review queue.
   Flag items needing human review. Do not retry blindly on a 4xx — fix the
   payload.

Be idempotent: rely on canonical keys and the unique constraints so re-running
this command on the same input does not create duplicates.
