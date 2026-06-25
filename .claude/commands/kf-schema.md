---
description: Explain / inspect the KnowledgeForest database structure, conventions, and live state
argument-hint: [optional focus, e.g. "edges" | "access classes" | "verify"]
allowed-tools: Read, Bash, mcp__claude_ai_Supabase__execute_sql
---

You are the reference for the KnowledgeForest data model. Explain the structure
and, when asked, inspect the live project.

Focus (optional):
$ARGUMENTS

## Procedure

1. Read `.claude/kf/DATA_MODEL.md` — that is the source of truth for tables,
   enums, edge/attribute conventions, dedup, ingestion schemes, retrieval
   procedures, the behavioral loop, and the access-class model.

2. **If the focus is a concept** (e.g. "edges", "dedup", "access classes",
   "how do I add a new pointer type"), explain just that part precisely, citing
   the relevant tables/functions and the conventions to follow. When introducing
   a new edge type / attribute key / pointer type, remind the user to add a
   `schema_vocabulary` row and re-run `backfill-vocab-embeddings` so the query
   planner knows about it.

3. **If the focus is "verify" / "inspect" / "live"** (or the user wants current
   state), connect (`.env.local` / `pipeline/.env`, or the Supabase MCP if
   connected) and report the live picture:
   - table count, row counts per core table (`pointers`, `edges`,
     `attributes_kv`, `document_chunks`, `schema_vocabulary`);
   - distinct `pointers.type` and edge `relationship_type` in use;
   - access classes + grant/membership counts;
   - `schema_vocabulary` embedded vs null;
   - cron job presence; dedup thresholds (`get_dedup_stats`).
   Use read-only queries only here; never mutate from this command.

4. **If no focus is given**, give a one-screen orientation: what a pointer /
   edge / attribute is, the ingestion commands (`/kf-ingest`), the retrieval
   commands (`/kf-query`), and the access-class gate — enough for a teammate to
   start.

Keep it accurate to `DATA_MODEL.md`; if the live schema and the doc disagree,
surface the discrepancy rather than guessing.
