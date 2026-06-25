import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

interface InsertPointerRequest {
  label: string;
  type: string;
  canonical_key?: string;
  metadata?: Record<string, unknown>;
  occurred_at?: string;
  // Access class the ingesting process assigns. Defaults to "public". Translated
  // to the row's acl[] (principals that may read it). `principals` overrides it
  // with an explicit set (e.g. body participants). Per-attribute overrides too.
  access_class?: string;
  principals?: string[];
  attributes?: { key: string; value: unknown; data_type?: string; sort_order?: number; source?: string; access_class?: string; principals?: string[] }[];
}

const PUBLIC_CLASS_ID = "00000000-0000-0000-0000-000000000001";

// Translate a named access-class key to its principal set (mirrors the SQL
// principals_for_class): public->sentinel, firm:{uuid}/user:{uuid}->[uuid],
// unknown->[] (fail-closed).
function principalsForClass(key?: string): string[] {
  if (!key || key === "public") return [PUBLIC_CLASS_ID];
  if (key.startsWith("firm:")) return [key.slice(5)];
  if (key.startsWith("user:")) return [key.slice(5)];
  return [];
}

async function getEmbedding(text: string): Promise<number[] | null> {
  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey) return null;

  try {
    const res = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${openaiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "text-embedding-3-small",
        input: text,
      }),
    });

    if (!res.ok) {
      console.error("OpenAI embedding error:", await res.text());
      return null;
    }

    const data = await res.json();
    return data.data[0].embedding;
  } catch (err) {
    console.error("Embedding generation failed:", err);
    return null;
  }
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, serviceRoleKey);

    const body: InsertPointerRequest = await req.json();

    if (!body.label || !body.type) {
      return new Response(
        JSON.stringify({ error: "label and type are required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Generate embedding from label + metadata context
    const embeddingText = body.metadata
      ? `${body.label} ${JSON.stringify(body.metadata)}`
      : body.label;
    const embedding = await getEmbedding(embeddingText);

    const pointerClass = body.access_class || "public";
    const pointerPrincipals = body.principals ?? principalsForClass(pointerClass);

    // Call the dedup-aware insert RPC (it stamps the pointer's acl + unions on merge)
    const { data: result, error: rpcError } = await supabase.rpc(
      "insert_pointer_with_dedup",
      {
        p_label: body.label,
        p_type: body.type,
        p_canonical_key: body.canonical_key || null,
        p_metadata: body.metadata || {},
        p_embedding: embedding ? JSON.stringify(embedding) : null,
        p_access_class: pointerClass,
        p_acl: pointerPrincipals,
      }
    );

    if (rpcError) {
      return new Response(
        JSON.stringify({ error: rpcError.message }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Attributes are written on ALL outcomes. On 'merged' this is the
    // enrichment path: re-ingesting an entity updates its attribute values
    // on the existing pointer instead of dropping them.
    if (body.attributes && body.attributes.length > 0 && result.pointer_id) {
      const attrRows = body.attributes.map((attr, i) => ({
        pointer_id: result.pointer_id,
        key: attr.key,
        value: typeof attr.value === "string" ? JSON.stringify(attr.value) : attr.value,
        data_type: attr.data_type || "string",
        sort_order: attr.sort_order ?? i,
        source: attr.source || "api",
        acl: attr.principals ?? (attr.access_class ? principalsForClass(attr.access_class) : pointerPrincipals),
        updated_at: new Date().toISOString(),
      }));

      const { error: attrError } = await supabase
        .from("attributes_kv")
        .upsert(attrRows, { onConflict: "pointer_id,key" });

      if (attrError) {
        console.error("Attribute upsert error:", attrError);
        // Non-fatal: pointer exists, attributes failed
        result.attribute_error = attrError.message;
      } else if (result.status === "merged") {
        result.enriched_attributes = attrRows.length;
      }
    }

    // Domain event time. On merge, never clobber an existing occurred_at.
    if (body.occurred_at && result.pointer_id) {
      const update =
        result.status === "merged"
          ? supabase
              .from("pointers")
              .update({ occurred_at: body.occurred_at })
              .eq("id", result.pointer_id)
              .is("occurred_at", null)
          : supabase
              .from("pointers")
              .update({ occurred_at: body.occurred_at })
              .eq("id", result.pointer_id);

      const { error: occError } = await update;
      if (occError) {
        console.error("occurred_at update error:", occError);
        result.occurred_at_error = occError.message;
      }
    }

    return new Response(
      JSON.stringify(result),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
