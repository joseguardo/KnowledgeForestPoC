---
description: Retrieve from the KnowledgeForest graph — natural-language or structured (auto-picks query-knowledge vs direct RPCs)
argument-hint: <question or retrieval request> [--mode search|answer|explore]
allowed-tools: Read, Bash, mcp__claude_ai_Supabase__execute_sql
---

You are retrieving from a KnowledgeForest knowledge graph. Answer the request
below using the right retrieval procedure, generalized over question type.

Request:
$ARGUMENTS

## Procedure

1. **Ground yourself.** Read `.claude/kf/DATA_MODEL.md` for the retrieval
   procedures (query-knowledge modes, the RPC catalog and signatures), the
   3-layer model (search → co-access → graph), and the access-class gate.

2. **Get the connection.** Read `.env.local` for `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_ANON_KEY`, `VITE_KIBO_TENANT_ID`. Use the anon key (public
   rows) unless the user supplies a JWT for higher clearance. If the Supabase
   MCP is connected, `execute_sql` is fine for the direct-RPC path.

3. **Pick the procedure:**
   - **Open-ended / "answer me" / exploratory** → `query-knowledge` edge
     function (the default). It plans + executes across all three layers and
     respects the caller's clearance. Choose `mode`:
     `search` (ranked results), `answer` (cited summary), `explore` (results +
     follow-ups). Honor a `--mode` flag; default to `answer` for questions,
     `search` for "find/list".
   - **Deterministic filter** ("all companies in fintech since 2024 with Stage=Series B")
     → `search_pointers` with `p_types`, `p_date_from/to`, `p_attr_filters`.
   - **Relationship / path** ("who attended X", "what connects A and B") →
     `traverse_graph`, or `get_pointer_subgraph` for one node's neighborhood,
     or `get_person_calendar` for a person's timeline.
   - **Structure / overview** → `get_tenant_forest`.

4. **Execute.**
   - query-knowledge:
     ```bash
     curl -s -X POST "$URL/functions/v1/query-knowledge" \
       -H "Authorization: Bearer $ANON_KEY" -H "apikey: $ANON_KEY" \
       -H "Content-Type: application/json" \
       -d '{"query":"...","tenant_id":"<VITE_KIBO_TENANT_ID>","mode":"answer"}'
     ```
   - Direct RPC via MCP `execute_sql` (`select * from <fn>(...)`) or PostgREST
     `POST $URL/rest/v1/rpc/<fn>` with the key headers. For semantic ranking,
     generate the query embedding (`text-embedding-3-small`, 1536d) and pass it
     as a JSON-array string; pass null for text-only.

5. **Present results** grouped and readable: label, type, why it matched
   (search / co-access / graph layer + the edge or attribute), and key
   attributes inline. For `answer` mode, give the composed answer first, then
   the supporting pointers. Note when results are empty because the graph has no
   matching content vs. because the caller's clearance filtered them out.

Never widen access by switching to the service_role key just to return more
rows — retrieval is meant to honor the caller's clearance.
