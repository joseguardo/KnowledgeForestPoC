import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

interface LogPathRequest {
  tenant_id: string;
  user_id?: string;
  agent_id?: string;
  session_id: string;
  pointer_ids: string[];
  query_text?: string;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, serviceRoleKey);

    const body: LogPathRequest = await req.json();

    if (!body.tenant_id || !body.session_id || !body.pointer_ids?.length) {
      return new Response(
        JSON.stringify({ error: "tenant_id, session_id, and pointer_ids are required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // 1. Insert the query path
    const { data: path, error: pathError } = await supabase
      .from("query_paths")
      .insert({
        tenant_id: body.tenant_id,
        user_id: body.user_id || null,
        agent_id: body.agent_id || null,
        session_id: body.session_id,
        pointer_ids: body.pointer_ids,
        query_text: body.query_text || null,
      })
      .select("id")
      .single();

    if (pathError) {
      return new Response(
        JSON.stringify({ error: pathError.message }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // 2. Generate co-access pairs with proximity weighting
    const pointerIds = body.pointer_ids;
    const pairs: { a: string; b: string; proximityBonus: number }[] = [];

    // Cap at 50 pointers to keep pair count manageable
    const capped = pointerIds.slice(0, 50);

    for (let i = 0; i < capped.length; i++) {
      for (let j = i + 1; j < capped.length; j++) {
        const distance = j - i;
        const proximityBonus = 1.0 / distance;
        const [a, b] = capped[i] < capped[j]
          ? [capped[i], capped[j]]
          : [capped[j], capped[i]];
        pairs.push({ a, b, proximityBonus });
      }
    }

    // 3. Batch upsert co-access weights
    if (pairs.length > 0) {
      const { error: coaccessError } = await supabase.rpc(
        "upsert_coaccess_batch",
        { p_tenant_id: body.tenant_id, p_pairs: pairs }
      );

      if (coaccessError) {
        console.error("Co-access upsert error:", coaccessError);
      }
    }

    // 4. Update cursor and check threshold
    const { data: shouldRecompute, error: cursorError } = await supabase.rpc(
      "update_coaccess_cursor",
      {
        p_tenant_id: body.tenant_id,
        p_path_id: path.id,
        p_new_edges: pairs.length,
      }
    );

    if (cursorError) {
      console.error("Cursor update error:", cursorError);
    }

    return new Response(
      JSON.stringify({
        status: "logged",
        path_id: path.id,
        pairs_updated: pairs.length,
        recompute_triggered: shouldRecompute || false,
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
