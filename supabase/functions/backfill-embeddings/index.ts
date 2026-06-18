import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings";
const EMBEDDING_MODEL = "text-embedding-3-small";
const BATCH_SIZE = 20; // OpenAI supports up to 2048 inputs, but keep batches small for reliability

interface Pointer {
  id: string;
  label: string;
  metadata: Record<string, unknown>;
}

async function getOpenAIEmbeddings(
  texts: string[],
  apiKey: string
): Promise<number[][]> {
  const response = await fetch(OPENAI_EMBEDDING_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      input: texts,
      model: EMBEDDING_MODEL,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(
      `OpenAI API error (${response.status}): ${errorBody}`
    );
  }

  const data = await response.json();
  // OpenAI returns embeddings sorted by index
  return data.data
    .sort((a: { index: number }, b: { index: number }) => a.index - b.index)
    .map((item: { embedding: number[] }) => item.embedding);
}

function buildEmbeddingInput(pointer: Pointer): string {
  return `${pointer.label} ${JSON.stringify(pointer.metadata)}`;
}

Deno.serve(async (req: Request) => {
  // Only allow POST
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    // Get OpenAI API key from environment (set via Supabase secrets / vault)
    const openaiApiKey = Deno.env.get("OPENAI_API_KEY");
    if (!openaiApiKey) {
      return new Response(
        JSON.stringify({
          error:
            "OPENAI_API_KEY secret is not set. Please add it via: supabase secrets set OPENAI_API_KEY=sk-...",
        }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    // Initialize Supabase client with service role key for admin access
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, supabaseServiceKey);

    // 1. Fetch all pointers with NULL embedding
    const { data: pointers, error: fetchError } = await supabase
      .from("pointers")
      .select("id, label, metadata")
      .is("embedding", null);

    if (fetchError) {
      throw new Error(`Failed to fetch pointers: ${fetchError.message}`);
    }

    if (!pointers || pointers.length === 0) {
      return new Response(
        JSON.stringify({
          message: "No pointers with NULL embedding found. Nothing to backfill.",
          backfilled: 0,
        }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // 2. Process in batches
    let totalBackfilled = 0;
    const errors: string[] = [];

    for (let i = 0; i < pointers.length; i += BATCH_SIZE) {
      const batch = pointers.slice(i, i + BATCH_SIZE) as Pointer[];
      const texts = batch.map(buildEmbeddingInput);

      try {
        const embeddings = await getOpenAIEmbeddings(texts, openaiApiKey);

        // 3. Update each pointer with its embedding
        for (let j = 0; j < batch.length; j++) {
          const pointer = batch[j];
          const embedding = embeddings[j];

          // pgvector expects a JSON array string for the vector column
          const embeddingStr = `[${embedding.join(",")}]`;

          const { error: updateError } = await supabase
            .from("pointers")
            .update({ embedding: embeddingStr } as any)
            .eq("id", pointer.id);

          if (updateError) {
            errors.push(
              `Failed to update pointer ${pointer.id} (${pointer.label}): ${updateError.message}`
            );
          } else {
            totalBackfilled++;
          }
        }
      } catch (batchError) {
        errors.push(
          `Batch ${Math.floor(i / BATCH_SIZE) + 1} failed: ${
            batchError instanceof Error ? batchError.message : String(batchError)
          }`
        );
      }
    }

    return new Response(
      JSON.stringify({
        message: `Backfill complete.`,
        total_null: pointers.length,
        backfilled: totalBackfilled,
        failed: pointers.length - totalBackfilled,
        errors: errors.length > 0 ? errors : undefined,
      }),
      {
        headers: { "Content-Type": "application/json" },
      }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({
        error: err instanceof Error ? err.message : String(err),
      }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
});
