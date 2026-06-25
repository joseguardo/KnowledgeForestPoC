import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

const DEFAULT_CHUNK_SIZE = 1200;
const MAX_CONTENT_LENGTH = 500_000;

interface IngestDocumentRequest {
  title: string;
  content: string;
  occurred_at?: string;
  metadata?: Record<string, unknown>;
  chunk_size?: number;
  // Access class for the document, its chunks and the link edge. Translated to
  // acl[]; `principals` overrides with an explicit set (e.g. body participants).
  access_class?: string;
  principals?: string[];
  // Optional namespace folded into the content hash so byte-identical content in
  // different scopes (e.g. two firms/tenants) does NOT collapse to one pointer.
  canonical_key_namespace?: string;
  link?: {
    target_id?: string;
    target_canonical_key?: string;
    target_label?: string;
    relationship_type?: string;
    why?: string;
  };
}

const PUBLIC_CLASS_ID = "00000000-0000-0000-0000-000000000001";

function principalsForClass(key?: string): string[] {
  if (!key || key === "public") return [PUBLIC_CLASS_ID];
  if (key.startsWith("firm:")) return [key.slice(5)];
  if (key.startsWith("user:")) return [key.slice(5)];
  return [];
}

async function sha256(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Non-overlapping chunks on paragraph boundaries, so concatenating
// chunks by sequence reconstructs the document. Markdown headings are
// captured as chunk context.
function chunkContent(content: string, chunkSize: number): { content: string; heading: string | null }[] {
  const paragraphs = content.split(/\n\n+/).map((p) => p.trim()).filter(Boolean);
  const chunks: { content: string; heading: string | null }[] = [];
  let current: string[] = [];
  let currentLen = 0;
  let currentHeading: string | null = null;
  let lastHeading: string | null = null;

  const flush = () => {
    if (current.length > 0) {
      chunks.push({ content: current.join("\n\n"), heading: currentHeading });
      current = [];
      currentLen = 0;
    }
  };

  for (const para of paragraphs) {
    const headingMatch = para.match(/^#{1,6}\s+(.+)$/m);
    if (headingMatch) lastHeading = headingMatch[1].trim();

    if (currentLen > 0 && currentLen + para.length > chunkSize) flush();
    if (current.length === 0) currentHeading = lastHeading;
    current.push(para);
    currentLen += para.length + 2;
  }
  flush();

  return chunks;
}

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
        input: texts.map((t) => t.slice(0, 8000)),
      }),
    });

    if (!res.ok) {
      console.error("OpenAI embedding error:", await res.text());
      return texts.map(() => null);
    }

    const data = await res.json();
    const byIndex = new Map<number, number[]>(
      data.data.map((d: { index: number; embedding: number[] }) => [d.index, d.embedding])
    );
    return texts.map((_, i) => byIndex.get(i) ?? null);
  } catch (err) {
    console.error("Embedding generation failed:", err);
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

    const body: IngestDocumentRequest = await req.json();

    if (!body.title || !body.content) {
      return new Response(
        JSON.stringify({ error: "title and content are required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }
    if (body.content.length > MAX_CONTENT_LENGTH) {
      return new Response(
        JSON.stringify({ error: `content too large: max ${MAX_CONTENT_LENGTH} chars` }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Content hash as canonical key: byte-identical documents dedup to one
    // pointer no matter how they arrive (upload, email attachment, re-run). An
    // optional namespace keeps identical content in separate scopes (e.g. two
    // tenants) from collapsing into one shared pointer.
    const canonicalKey = `doc:${await sha256((body.canonical_key_namespace || "") + body.content)}`;
    const chunks = chunkContent(body.content, body.chunk_size ?? DEFAULT_CHUNK_SIZE);

    const embeddings = await getEmbeddings([
      `${body.title}\n${body.content.slice(0, 4000)}`,
      ...chunks.map((c) => c.content),
    ]);
    const docEmbedding = embeddings[0];
    const chunkEmbeddings = embeddings.slice(1);

    const docClass = body.access_class || "public";
    // Visibility is the acl: principals override, else translated from the class.
    // Fail-closed by construction — an unknown class yields [] (visible to no one).
    const docPrincipals = body.principals ?? principalsForClass(docClass);

    const { data: result, error: rpcError } = await supabase.rpc(
      "insert_pointer_with_dedup",
      {
        p_label: body.title,
        p_type: "document",
        p_canonical_key: canonicalKey,
        p_metadata: { ...(body.metadata || {}), char_count: body.content.length, chunk_count: chunks.length },
        p_embedding: docEmbedding ? JSON.stringify(docEmbedding) : null,
        p_access_class: docClass,
        p_acl: docPrincipals,
      }
    );

    if (rpcError) {
      return new Response(
        JSON.stringify({ error: rpcError.message }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const response: Record<string, unknown> = {
      status: result.status,
      pointer_id: result.pointer_id,
      canonical_key: canonicalKey,
      chunks_total: chunks.length,
      chunks_inserted: 0,
    };

    // On merge the same content hash already has its chunks; don't duplicate.
    if (result.status === "created" || result.status === "pending_review") {
      const chunkRows = chunks.map((c, i) => ({
        pointer_id: result.pointer_id,
        sequence: i,
        content: c.content,
        heading: c.heading,
        embedding: chunkEmbeddings[i] ? JSON.stringify(chunkEmbeddings[i]) : null,
        acl: docPrincipals,
        metadata: {},
      }));

      const { error: chunkError } = await supabase.from("document_chunks").insert(chunkRows);
      if (chunkError) response.chunk_error = chunkError.message;
      else response.chunks_inserted = chunkRows.length;
    }

    if (body.occurred_at && result.pointer_id) {
      const update =
        result.status === "merged"
          ? supabase.from("pointers").update({ occurred_at: body.occurred_at })
              .eq("id", result.pointer_id).is("occurred_at", null)
          : supabase.from("pointers").update({ occurred_at: body.occurred_at })
              .eq("id", result.pointer_id);
      const { error: occError } = await update;
      if (occError) response.occurred_at_error = occError.message;
    }

    // Optional edge: document -> entity (e.g. the company a deck describes)
    if (body.link && result.pointer_id) {
      let targetId = body.link.target_id || null;

      if (!targetId && body.link.target_canonical_key) {
        const { data } = await supabase.from("pointers").select("id")
          .eq("canonical_key", body.link.target_canonical_key).maybeSingle();
        targetId = data?.id || null;
      }
      if (!targetId && body.link.target_label) {
        const { data } = await supabase.from("pointers").select("id")
          .eq("label", body.link.target_label).limit(1).maybeSingle();
        targetId = data?.id || null;
      }

      if (!targetId) {
        response.link = { status: "target_not_found" };
      } else {
        const { data: edge, error: edgeError } = await supabase
          .from("edges")
          .insert({
            source_id: result.pointer_id,
            target_id: targetId,
            relationship_type: body.link.relationship_type || "describes",
            why: body.link.why || `Document "${body.title}" describes this entity`,
            payload: {},
            weight: 1.0,
            acl: docPrincipals,
          })
          .select("id, relationship_type, target_id")
          .single();

        if (edgeError) {
          response.link =
            edgeError.code === "23505"
              ? { status: "already_linked", target_id: targetId }
              : { status: "error", error: edgeError.message };
        } else {
          response.link = { status: "created", ...edge };
        }
      }
    }

    return new Response(
      JSON.stringify(response),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
