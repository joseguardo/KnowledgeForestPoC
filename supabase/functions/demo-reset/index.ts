import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

// Deletes ONLY demo-namespaced data created by the explainer's live examples:
// pointers whose canonical_key starts with "demo:" or whose label contains "(demo)".
// Real knowledge-graph data is untouchable through this function.
Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, serviceRoleKey);

    // Two separate queries: "(demo)" contains parens that break PostgREST
    // .or() filter parsing, so the patterns must not share an or-string.
    const { data: byKey, error: keyError } = await supabase
      .from("pointers")
      .select("id")
      .like("canonical_key", "demo:%");
    const { data: byLabel, error: labelError } = await supabase
      .from("pointers")
      .select("id")
      .like("label", "%(demo)%");

    const selError = keyError || labelError;
    if (selError) {
      return new Response(
        JSON.stringify({ error: selError.message }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const ids = [...new Set([...(byKey || []), ...(byLabel || [])].map((p: { id: string }) => p.id))];

    if (ids.length === 0) {
      return new Response(
        JSON.stringify({ status: "clean", pointers_deleted: 0 }),
        { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    await supabase.from("document_chunks").delete().in("pointer_id", ids);
    await supabase.from("attributes_kv").delete().in("pointer_id", ids);
    await supabase.from("duplicate_flags").delete().or(
      `pointer_id_a.in.(${ids.join(",")}),pointer_id_b.in.(${ids.join(",")})`
    );
    await supabase.from("edges").delete().or(
      `source_id.in.(${ids.join(",")}),target_id.in.(${ids.join(",")})`
    );
    await supabase.from("tenant_coaccess").delete().or(
      `pointer_a.in.(${ids.join(",")}),pointer_b.in.(${ids.join(",")})`
    );
    await supabase.from("tenant_pointer_assignments").delete().in("pointer_id", ids);

    const { error: delError } = await supabase.from("pointers").delete().in("id", ids);
    if (delError) {
      return new Response(
        JSON.stringify({ error: delError.message }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    return new Response(
      JSON.stringify({ status: "clean", pointers_deleted: ids.length }),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
