import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

interface LinkRequest {
  source_id: string;
  target_id: string;
  relationship_type?: string;
  why?: string;
  payload?: Record<string, unknown>;
  weight?: number;
  // Principals (acl) for this edge — the relationship's tenant(s). Defaults to
  // public; the RLS edges_read also requires both endpoints visible, so a public
  // edge between two private pointers still can't be read.
  principals?: string[];
}

const PUBLIC_CLASS_ID = "00000000-0000-0000-0000-000000000001";

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, serviceRoleKey);

    const body: LinkRequest = await req.json();

    if (!body.source_id || !body.target_id) {
      return new Response(
        JSON.stringify({ error: "source_id and target_id are required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Validate both pointers exist
    const { data: sourcePtr } = await supabase
      .from("pointers")
      .select("id")
      .eq("id", body.source_id)
      .single();

    const { data: targetPtr } = await supabase
      .from("pointers")
      .select("id")
      .eq("id", body.target_id)
      .single();

    if (!sourcePtr || !targetPtr) {
      return new Response(
        JSON.stringify({
          error: "One or both pointers not found",
          source_exists: !!sourcePtr,
          target_exists: !!targetPtr,
        }),
        { status: 404, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Create the edge
    const { data: edge, error } = await supabase
      .from("edges")
      .insert({
        source_id: body.source_id,
        target_id: body.target_id,
        relationship_type: body.relationship_type || "related",
        why: body.why || null,
        payload: body.payload || {},
        weight: body.weight || 1.0,
        acl: (body.principals && body.principals.length) ? body.principals : [PUBLIC_CLASS_ID],
      })
      .select()
      .single();

    if (error) {
      // Handle duplicate edge
      if (error.code === "23505") {
        return new Response(
          JSON.stringify({ error: "Edge already exists between these pointers with this relationship type" }),
          { status: 409, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }
      return new Response(
        JSON.stringify({ error: error.message }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    return new Response(
      JSON.stringify({ status: "created", edge }),
      { status: 201, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
