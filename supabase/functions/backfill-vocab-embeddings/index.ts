import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

Deno.serve(async (req: Request) => {
  const corsHeaders = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type" };
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

  const supabase = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey) return new Response(JSON.stringify({ error: "OPENAI_API_KEY not set" }), { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } });

  const { data: vocab } = await supabase.from("schema_vocabulary").select("id, term, description").is("embedding", null);
  if (!vocab?.length) return new Response(JSON.stringify({ message: "All vocab already embedded", count: 0 }), { headers: { ...corsHeaders, "Content-Type": "application/json" } });

  let backfilled = 0;
  // Batch in groups of 20
  for (let i = 0; i < vocab.length; i += 20) {
    const batch = vocab.slice(i, i + 20);
    const texts = batch.map(v => `${v.term}: ${v.description || v.term}`);
    const res = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: { "Authorization": `Bearer ${openaiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: "text-embedding-3-small", input: texts }),
    });
    if (!res.ok) continue;
    const data = await res.json();
    for (let j = 0; j < batch.length; j++) {
      const embedding = data.data[j].embedding;
      await supabase.from("schema_vocabulary").update({ embedding: JSON.stringify(embedding) }).eq("id", batch[j].id);
      backfilled++;
    }
  }

  return new Response(JSON.stringify({ message: "Vocab embeddings backfilled", backfilled, total: vocab.length }), { headers: { ...corsHeaders, "Content-Type": "application/json" } });
});
