import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

const MAX_BATCH_SIZE = 50;

interface BatchItem {
  label: string;
  type: string;
  canonical_key?: string;
  metadata?: Record<string, unknown>;
  occurred_at?: string;
  access_class?: string;
  principals?: string[];
  attributes?: { key: string; value: unknown; data_type?: string; sort_order?: number; source?: string; access_class?: string; principals?: string[] }[];
}

interface BatchRequest {
  items: BatchItem[];
  source?: string;
  // Default access class for every item that doesn't set its own.
  access_class?: string;
  principals?: string[];
}

const PUBLIC_CLASS_ID = "00000000-0000-0000-0000-000000000001";

function principalsForClass(key?: string): string[] {
  if (!key || key === "public") return [PUBLIC_CLASS_ID];
  if (key.startsWith("firm:")) return [key.slice(5)];
  if (key.startsWith("user:")) return [key.slice(5)];
  return [];
}

// One embedding API call for the whole batch instead of one per item.
async function getEmbeddings(texts: string[]): Promise<(number[] | null)[]> {
  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey) return texts.map(() => null);

  try {
    const res = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${openaiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "text-embedding-3-small",
        input: texts,
      }),
    });

    if (!res.ok) {
      console.error("OpenAI batch embedding error:", await res.text());
      return texts.map(() => null);
    }

    const data = await res.json();
    const byIndex = new Map<number, number[]>(
      data.data.map((d: { index: number; embedding: number[] }) => [d.index, d.embedding])
    );
    return texts.map((_, i) => byIndex.get(i) ?? null);
  } catch (err) {
    console.error("Batch embedding generation failed:", err);
    return texts.map(() => null);
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

    const body: BatchRequest = await req.json();

    if (!Array.isArray(body.items) || body.items.length === 0) {
      return new Response(
        JSON.stringify({ error: "items array is required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }
    if (body.items.length > MAX_BATCH_SIZE) {
      return new Response(
        JSON.stringify({ error: `batch too large: max ${MAX_BATCH_SIZE} items` }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const embeddingTexts = body.items.map((item) =>
      item.metadata ? `${item.label} ${JSON.stringify(item.metadata)}` : item.label ?? ""
    );
    const embeddings = await getEmbeddings(embeddingTexts);

    const results: Record<string, unknown>[] = [];

    // Sequential on purpose: dedup must see earlier items in the same batch.
    for (let i = 0; i < body.items.length; i++) {
      const item = body.items[i];

      if (!item.label || !item.type) {
        results.push({ index: i, status: "error", error: "label and type are required" });
        continue;
      }

      const itemClass = item.access_class || body.access_class || "public";
      const itemPrincipals = item.principals ?? body.principals ?? principalsForClass(itemClass);

      const { data: result, error: rpcError } = await supabase.rpc(
        "insert_pointer_with_dedup",
        {
          p_label: item.label,
          p_type: item.type,
          p_canonical_key: item.canonical_key || null,
          p_metadata: item.metadata || {},
          p_embedding: embeddings[i] ? JSON.stringify(embeddings[i]) : null,
          p_access_class: itemClass,
          p_acl: itemPrincipals,
        }
      );

      if (rpcError) {
        results.push({ index: i, label: item.label, status: "error", error: rpcError.message });
        continue;
      }

      const entry: Record<string, unknown> = {
        index: i,
        label: item.label,
        status: result.status,
        pointer_id: result.pointer_id,
      };

      if (item.attributes && item.attributes.length > 0 && result.pointer_id) {
        const attrRows = item.attributes.map((attr, j) => ({
          pointer_id: result.pointer_id,
          key: attr.key,
          // Store the value as-is: the client serializes it into the jsonb column,
          // so a JS string "EUR" becomes the jsonb string "EUR". (Previously this
          // JSON.stringify'd strings first, double-encoding them as "\"EUR\"" and
          // breaking exact-match attribute filters.)
          value: attr.value,
          data_type: attr.data_type || "string",
          sort_order: attr.sort_order ?? j,
          source: attr.source || body.source || "batch",
          acl: attr.principals ?? (attr.access_class ? principalsForClass(attr.access_class) : itemPrincipals),
          updated_at: new Date().toISOString(),
        }));

        const { error: attrError } = await supabase
          .from("attributes_kv")
          .upsert(attrRows, { onConflict: "pointer_id,key" });

        if (attrError) entry.attribute_error = attrError.message;
        else if (result.status === "merged") entry.enriched_attributes = attrRows.length;
      }

      if (item.occurred_at && result.pointer_id) {
        const update =
          result.status === "merged"
            ? supabase
                .from("pointers")
                .update({ occurred_at: item.occurred_at })
                .eq("id", result.pointer_id)
                .is("occurred_at", null)
            : supabase
                .from("pointers")
                .update({ occurred_at: item.occurred_at })
                .eq("id", result.pointer_id);

        const { error: occError } = await update;
        if (occError) entry.occurred_at_error = occError.message;
      }

      results.push(entry);
    }

    const summary = {
      total: body.items.length,
      created: results.filter((r) => r.status === "created").length,
      merged: results.filter((r) => r.status === "merged").length,
      pending_review: results.filter((r) => r.status === "pending_review").length,
      errors: results.filter((r) => r.status === "error").length,
    };

    return new Response(
      JSON.stringify({ summary, results }),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
