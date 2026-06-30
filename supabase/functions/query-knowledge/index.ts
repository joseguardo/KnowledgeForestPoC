import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

// The POINTER TYPES / EDGE TYPES lines are injected at runtime from the live DB
// (see buildSchemaContext) so the planner prompt always reflects the types and
// edges that actually exist — new pointer types (e.g. fund) or edge types (e.g.
// transaction_of / booked_to) appear automatically with no manual upkeep. The
// constants below are only a fallback if the lookup fails.
const FALLBACK_POINTER_TYPES =
  "company, person, sector, geography, regulation, document, timeseries, agent, skill, tool, flow, component, architecture, best_practice, meta, event, fund";
const FALLBACK_EDGE_TYPES =
  "primary_sector, ceo, competitor, hq_location, jurisdiction, related, uses_skill, uses_tool, uses_agent, triggers, part_of, transaction_of, booked_to, guides, follows, ensures_compliance, dispatches, executes, routes, routed_through, connects_to, powers, contains, accessed_via, triggered_by, used_by, connects";

function schemaContextFor(pointerTypes: string, edgeTypes: string): string {
  return `
You are a query planner for a knowledge graph with hierarchy-aware retrieval.

The system has 3 retrieval layers:
1. SEARCH: hybrid text+semantic match on pointer labels, attributes, and full-text index
2. COACCESS: tenant-specific behavioral signal
3. GRAPH: structural edge traversal as fallback

Main function:
  search_hierarchy_aware(query, tenant_id, embedding?, type_filter?, limit)
  Returns: pointer_id, label, type, source, relevance_score, match_details, coaccess_weight, via_pointer, attributes

Additional:
  traverse_graph(start_ids, edge_types?, direction?, target_type?, depth?)
  get_pointer_subgraph(pointer_id)

POINTER TYPES: ${pointerTypes}
EDGE TYPES: ${edgeTypes}

FUND / PORTFOLIO (Naluat ledger): fund pointers are investment funds. company —part_of→ fund (portfolio membership); each transaction is an event pointer with event —transaction_of→ company and event —booked_to→ fund (edge payload carries {amount,currency,transaction_type,company,fund,date}). To list/total a fund's transactions, traverse inbound booked_to from the fund (or read the fund's naluat_invested_by_currency attribute). Company rollups: naluat_status, naluat_invested_by_currency, naluat_realized_by_currency, naluat_current_value_by_currency, naluat_moic, naluat_valuation_series.

RULES:
1. Prefer hierarchy_search as first step — it returns attributes inline.
2. Use traverse only for specific edge-following queries.
3. When DATA HINTS are provided, follow them precisely.
4. When SEMANTIC MATCHES are provided, they tell you which edge types, attribute keys, or pointer types are semantically relevant to the query. Use them to pick the right type_filter or edge_types.
5. Do NOT add type_filter unless you are confident it won't exclude relevant results. When in doubt, omit it.
6. Output ONLY valid JSON. 1-3 steps max.
`;
}

// Cached for the lifetime of the warm instance — type/edge vocab changes rarely
// and is schema (not row) data, so we enumerate it with the service role (which
// sees every type, even those only present in access-restricted rows) while the
// actual query EXECUTION still runs under the caller's RLS. Any failure falls
// back to the static lists above, so the planner never breaks.
let _schemaContextCache: string | null = null;
async function buildSchemaContext(schemaClient: any): Promise<string> {
  if (_schemaContextCache) return _schemaContextCache;
  let pt = FALLBACK_POINTER_TYPES;
  let et = FALLBACK_EDGE_TYPES;
  try {
    const [pRes, eRes] = await Promise.all([
      schemaClient.from("pointers").select("type"),
      schemaClient.from("edges").select("relationship_type"),
    ]);
    const ptList = [...new Set((pRes.data || []).map((r: any) => r.type).filter(Boolean))].sort();
    const etList = [...new Set((eRes.data || []).map((r: any) => r.relationship_type).filter(Boolean))].sort();
    if (ptList.length) pt = ptList.join(", ");
    if (etList.length) et = etList.join(", ");
  } catch (_e) {
    // keep fallbacks
  }
  _schemaContextCache = schemaContextFor(pt, et);
  return _schemaContextCache;
}

const PLAN_EXAMPLE = `
Examples:
Q: "What are the biggest AI companies?"
{"steps":[{"action":"hierarchy_search","query":"AI companies","type_filter":"company"}]}

Q: "Who leads NVIDIA?" [semantic: ceo edge, CEO attr, person type]
{"steps":[{"action":"hierarchy_search","query":"NVIDIA"},{"action":"traverse","from":"$step1","edge_types":["ceo"],"direction":"inbound","target_type":"person"}]}

Q: "List all CEOs" [hint: don't filter by type]
{"steps":[{"action":"hierarchy_search","query":"CEO"}]}

Q: "Which sector grows fastest?" [semantic: CAGR attr, sector type]
{"steps":[{"action":"hierarchy_search","query":"growth rate CAGR","type_filter":"sector"}]}
`;

interface QueryRequest {
  query: string;
  tenant_id?: string;
  mode?: "search" | "answer" | "explore";
}

const DEFAULT_TENANT = "ca61f0e5-563e-5894-954f-38f5a9e0eabc";

async function getEmbedding(text: string): Promise<number[] | null> {
  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey) return null;
  try {
    const res = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: { "Authorization": `Bearer ${openaiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: "text-embedding-3-small", input: text }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.data[0].embedding;
  } catch { return null; }
}

async function generatePlan(query: string, regexHints: string[], semanticMatches: any[], schemaContext: string): Promise<any> {
  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey) {
    return { steps: [{ action: "hierarchy_search", query }] };
  }

  let userMessage = `Q: "${query}"`;

  if (regexHints.length > 0) {
    userMessage += `\n\nDATA HINTS:\n${regexHints.map((h, i) => `${i + 1}. ${h}`).join("\n")}`;
  }

  if (semanticMatches.length > 0) {
    const grouped: Record<string, string[]> = {};
    for (const m of semanticMatches) {
      if (!grouped[m.category]) grouped[m.category] = [];
      grouped[m.category].push(`${m.term} (${m.similarity}) - ${m.description}`);
    }
    let semStr = "\nSEMANTIC MATCHES (vocabulary terms similar to this query):";
    for (const [cat, terms] of Object.entries(grouped)) {
      semStr += `\n  ${cat}: ${terms.join("; ")}`;
    }
    userMessage += semStr;
  }

  try {
    const res = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "Authorization": `Bearer ${openaiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: schemaContext + PLAN_EXAMPLE },
          { role: "user", content: userMessage },
        ],
        temperature: 0.1,
        response_format: { type: "json_object" },
      }),
    });
    if (!res.ok) return { steps: [{ action: "hierarchy_search", query }] };
    const data = await res.json();
    return JSON.parse(data.choices[0].message.content);
  } catch {
    return { steps: [{ action: "hierarchy_search", query }] };
  }
}

async function executePlan(plan: any, supabase: any, tenantId: string, queryEmbedding: number[] | null) {
  const stepResults: Map<number, any[]> = new Map();
  const allResults: any[] = [];

  for (let i = 0; i < plan.steps.length; i++) {
    const step = plan.steps[i];
    let inputIds: string[] = [];

    if (step.from && typeof step.from === "string" && step.from.startsWith("$step")) {
      const refIdx = parseInt(step.from.replace("$step", "")) - 1;
      const refResults = stepResults.get(refIdx) || [];
      inputIds = refResults.map((r: any) => r.pointer_id || r.id);
    }

    let results: any[] = [];

    if (step.action === "hierarchy_search" || step.action === "search") {
      const { data, error } = await supabase.rpc("search_hierarchy_aware", {
        p_query: step.query || step.q || "",
        p_tenant_id: tenantId,
        p_embedding: queryEmbedding ? JSON.stringify(queryEmbedding) : null,
        p_type_filter: step.type_filter || null,
        p_limit: step.limit || 15,
      });
      if (!error && data) results = data;

    } else if (step.action === "traverse") {
      if (inputIds.length === 0) continue;
      const { data, error } = await supabase.rpc("traverse_graph", {
        p_start_ids: inputIds,
        p_edge_types: step.edge_types || null,
        p_direction: step.direction || "both",
        p_target_type: step.target_type || null,
        p_depth: step.depth || 1,
        p_limit: step.limit || 30,
      });
      if (!error && data) results = data;

    } else if (step.action === "enrich") {
      if (inputIds.length === 0) continue;
      for (const pid of inputIds.slice(0, 10)) {
        const { data } = await supabase.rpc("get_pointer_subgraph", { p_pointer_id: pid });
        if (data) {
          allResults.push({
            pointer: data.pointer,
            attributes: data.attributes,
            outbound_edges: data.outbound_edges?.length || 0,
            inbound_edges: data.inbound_edges?.length || 0,
          });
        }
      }
    }

    stepResults.set(i, results);
  }

  if (allResults.length === 0) {
    const lastStep = plan.steps.length - 1;
    const lastResults = stepResults.get(lastStep) || stepResults.get(lastStep - 1) || [];
    for (const r of lastResults) {
      allResults.push({
        pointer: { id: r.pointer_id, label: r.label, type: r.type },
        source: r.source || null,
        score: r.relevance_score || r.combined_score || null,
        coaccess_weight: r.coaccess_weight || null,
        via: r.via_pointer || r.via_edge_type || null,
        match_details: r.match_details || null,
        attributes: r.attributes || null,
        depth: r.depth || null,
        why: r.via_edge_why || null,
      });
    }
  }

  return allResults;
}

async function composeAnswer(query: string, results: any[]): Promise<string> {
  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey || results.length === 0) return "";

  const context = results.map((r: any) => {
    const label = r.pointer?.label || r.label || "unknown";
    const type = r.pointer?.type || r.type || "";
    const source = r.source || "";
    const via = r.via || "";
    const coac = r.coaccess_weight ? ` [behavioral weight: ${r.coaccess_weight}]` : "";
    let attrStr = "";
    const attrs = r.attributes || [];
    if (Array.isArray(attrs) && attrs.length > 0) {
      attrStr = " | Attributes: " + attrs.map((a: any) => `${a.key}=${a.value}`).join(", ");
    }
    return `${label} (${type}) found via ${source}${via ? " — " + via : ""}${coac}${attrStr}`;
  }).join("\n");

  try {
    const res = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "Authorization": `Bearer ${openaiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: [
          {
            role: "system",
            content: `You are a concise knowledge analyst. Answer based ONLY on the provided knowledge graph results.

RULES:
1. Results come from 3 layers: search (text match), coaccess (behavioral), graph (structural edges).
2. Each result includes attributes (key=value). USE THEM.
3. CRITICAL: Some entities are referenced ONLY inside attributes e.g. CEO=Bancel means Bancel is a CEO. Include these in your answer.
4. Be specific — cite names, numbers, values.
5. 2-4 sentences max.`,
          },
          { role: "user", content: `Question: ${query}\n\nKnowledge graph results:\n${context}` },
        ],
        temperature: 0.3,
        max_tokens: 400,
      }),
    });
    if (!res.ok) return "";
    const data = await res.json();
    return data.choices[0].message.content.trim();
  } catch { return ""; }
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const anonKey = Deno.env.get("SUPABASE_ANON_KEY")!;
    // Access control: run every DB read under the CALLER's identity (forward
    // their JWT) instead of the service role. RLS then filters restricted rows
    // out of the planner hints, the results, AND the LLM answer context — so a
    // low-clearance caller can never have confidential content surfaced or
    // narrated back to them. Falls back to the anon key (public only) if no
    // Authorization header is present.
    const authHeader = req.headers.get("Authorization") ?? `Bearer ${anonKey}`;
    const supabase = createClient(supabaseUrl, anonKey, {
      global: { headers: { Authorization: authHeader } },
    });
    // Separate client used ONLY to enumerate the live pointer/edge types for the
    // planner prompt (schema metadata, not row data). Uses the service role so
    // the type list is complete even when the caller is low-clearance; query
    // execution below still runs under `supabase` (the caller's RLS).
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const schemaClient = serviceKey ? createClient(supabaseUrl, serviceKey) : supabase;

    const body: QueryRequest = await req.json();
    if (!body.query?.trim()) {
      return new Response(
        JSON.stringify({ error: "query is required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const mode = body.mode || "search";
    const tenantId = body.tenant_id || DEFAULT_TENANT;

    // Step 0: Generate query embedding (reused for search + vocab matching)
    const queryEmbedding = await getEmbedding(body.query);

    // Step 1: Get context hints (regex + semantic vocabulary matching)
    const { data: queryContext } = await supabase.rpc("get_query_context_v2", {
      p_query: body.query,
      p_query_embedding: queryEmbedding ? JSON.stringify(queryEmbedding) : null,
    });
    const regexHints: string[] = queryContext?.regex_hints || [];
    const semanticMatches: any[] = queryContext?.semantic_matches || [];

    // Step 2: Generate plan (with both hint types injected). The schema context
    // (valid pointer/edge types) is fetched live from the DB so the prompt always
    // reflects what actually exists.
    const schemaContext = await buildSchemaContext(schemaClient);
    const plan = await generatePlan(body.query, regexHints, semanticMatches, schemaContext);

    // Step 3: Execute plan (runs under the caller's RLS)
    const results = await executePlan(plan, supabase, tenantId, queryEmbedding);

    // Step 4: Compose answer (only from results the caller is cleared to see)
    let answer = "";
    if (mode === "answer" && results.length > 0) {
      answer = await composeAnswer(body.query, results);
    }

    // Step 5: Suggestions
    const suggestions: string[] = [];
    if (mode === "explore" && results.length > 0) {
      const topLabels = results.slice(0, 3).map((r: any) => r.pointer?.label || r.label).filter(Boolean);
      if (topLabels.length > 0) {
        suggestions.push(`Who leads ${topLabels[0]}?`);
        suggestions.push(`What regulations affect ${topLabels[0]}?`);
        if (topLabels.length > 1) suggestions.push(`How are ${topLabels[0]} and ${topLabels[1]} connected?`);
      }
    }

    return new Response(
      JSON.stringify({
        query: body.query,
        mode,
        tenant_id: tenantId,
        context: {
          regex_hints: regexHints.length > 0 ? regexHints : undefined,
          semantic_matches: semanticMatches.length > 0 ? semanticMatches : undefined,
        },
        plan,
        results,
        answer: answer || undefined,
        suggestions: suggestions.length > 0 ? suggestions : undefined,
        result_count: results.length,
      }),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
