import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

// Ingests the PUBLIC-within-firm communication graph for one email thread.
// Each thread becomes an 'event' pointer (occurred_at = last activity); every
// real participant is run through insert_pointer_with_dedup as a 'person', and
// edges record who contacted whom:
//   sender  --emailed--> event
//   event   --to-->      recipient (person)
//   event   --cc-->      cc recipient (person)
// Everything is tagged with the caller-supplied access_class (= "firm:<tenant>",
// granted to the tenant), so it is visible firm-wide but isolated from other
// firms. The email BODY/SUBJECT are NOT handled here — they are ingested
// separately (privately) via ingest-document. Canonical keys are pre-namespaced
// by the caller (person::<tenant>::email, event:<tenant>:...), so two firms
// never share nodes.

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

const PUBLIC_CLASS_ID = "00000000-0000-0000-0000-000000000001";

interface Participant {
  canonical_key: string;       // person::<tenant>::<email>
  label: string;               // display name (or email)
  role: "from" | "to" | "cc";
}

interface EmailEvent {
  label: string;               // subject-free, e.g. "Email: Alice -> Bob"
  canonical_key: string;       // event:<tenant>:gmailthread:<hash>
  occurred_at?: string;        // ISO; last activity in the thread
  metadata?: Record<string, unknown>;
}

interface EmailRequest {
  tenant_id: string;
  participants: Participant[];
  event: EmailEvent;
  access_class: string;        // "firm:<tenant_id>" — must already exist
  source?: string;
}

async function classResolver(supabase: ReturnType<typeof createClient>) {
  const { data } = await supabase.from("access_classes").select("id,key");
  const idByKey: Record<string, string> = {};
  (data || []).forEach((c: { id: string; key: string }) => { idByKey[c.key] = c.id; });
  return (key?: string) => idByKey[key || "public"] || PUBLIC_CLASS_ID;
}

async function getEmbeddings(texts: string[]): Promise<(number[] | null)[]> {
  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey || texts.length === 0) return texts.map(() => null);
  try {
    const res = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: { "Authorization": `Bearer ${openaiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: "text-embedding-3-small", input: texts }),
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
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  const started = Date.now();

  try {
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    const body: EmailRequest = await req.json();
    if (!body.tenant_id) return json({ error: "tenant_id is required" }, 400);
    if (!body.event?.label || !body.event?.canonical_key) {
      return json({ error: "event.label and event.canonical_key are required" }, 400);
    }
    if (!Array.isArray(body.participants)) {
      return json({ error: "participants array is required" }, 400);
    }

    // Fail closed: never silently publish a firm's graph as public.
    const reqClass = body.access_class || "public";
    const resolveClass = await classResolver(supabase);
    const classId = resolveClass(reqClass);
    if (reqClass !== "public" && classId === PUBLIC_CLASS_ID) {
      return json(
        { error: `access_class '${reqClass}' does not exist; refusing to fall back to public` },
        400
      );
    }

    // ── 1. Resolve every distinct participant as a person entity ──
    // Deduped by canonical_key (a person may appear in several roles across a
    // thread; the entity is created once, edges are created per role below).
    const byKey = new Map<string, Participant>();
    for (const p of body.participants) {
      if (p?.canonical_key && !byKey.has(p.canonical_key)) byKey.set(p.canonical_key, p);
    }
    const people = [...byKey.values()];
    const peopleEmb = await getEmbeddings(people.map((p) => p.label));
    const idByKey = new Map<string, string>();
    const entityResults: Record<string, unknown>[] = [];

    for (let i = 0; i < people.length; i++) {
      const p = people[i];
      const { data: r, error } = await supabase.rpc("insert_pointer_with_dedup", {
        p_label: p.label,
        p_type: "person",
        p_canonical_key: p.canonical_key,
        p_metadata: {},
        p_embedding: peopleEmb[i] ? JSON.stringify(peopleEmb[i]) : null,
        p_access_class: reqClass,
      });
      if (error || !r?.pointer_id) {
        entityResults.push({ label: p.label, status: "error", error: error?.message || "no id" });
        continue;
      }
      idByKey.set(p.canonical_key, r.pointer_id);
      entityResults.push({ label: p.label, status: r.status, pointer_id: r.pointer_id });
    }

    // ── 2. The event pointer ──
    const [eventEmb] = await getEmbeddings([body.event.label]);
    const { data: er, error: eErr } = await supabase.rpc("insert_pointer_with_dedup", {
      p_label: body.event.label,
      p_type: "event",
      p_canonical_key: body.event.canonical_key,
      p_metadata: { event_type: "email", ...(body.event.metadata || {}) },
      p_embedding: eventEmb ? JSON.stringify(eventEmb) : null,
      p_access_class: reqClass,
    });
    if (eErr || !er?.pointer_id) {
      return json({ error: `event: ${eErr?.message || "no id"}` }, 500);
    }
    const eventId = er.pointer_id as string;

    if (body.event.occurred_at) {
      const occUpdate = er.status === "merged"
        ? supabase.from("pointers").update({ occurred_at: body.event.occurred_at })
            .eq("id", eventId).is("occurred_at", null)
        : supabase.from("pointers").update({ occurred_at: body.event.occurred_at })
            .eq("id", eventId);
      await occUpdate;
    }

    // ── 3. Participant edges (who contacted whom) ──
    const REL: Record<string, { rel: string; dir: "p2e" | "e2p" }> = {
      from: { rel: "emailed", dir: "p2e" },
      to: { rel: "to", dir: "e2p" },
      cc: { rel: "cc", dir: "e2p" },
    };
    // Iterate ALL participant entries (not the deduped set) so a person who
    // both sent and received in the thread gets both edges. Duplicate (source,
    // target, relationship_type) rows collapse via the upsert below.
    const edgeRows: Record<string, unknown>[] = [];
    for (const p of body.participants) {
      const pid = idByKey.get(p.canonical_key);
      const spec = REL[p.role];
      if (!pid || !spec || pid === eventId) continue;
      edgeRows.push(
        spec.dir === "p2e"
          ? { source_id: pid, target_id: eventId, relationship_type: spec.rel,
              why: `${p.label} sent this email`, access_class_id: classId }
          : { source_id: eventId, target_id: pid, relationship_type: spec.rel,
              why: `${p.label} was a ${p.role} recipient`, access_class_id: classId }
      );
    }

    let edgeError: string | undefined;
    if (edgeRows.length > 0) {
      const { error: edgeErr } = await supabase
        .from("edges")
        .upsert(edgeRows, { onConflict: "source_id,target_id,relationship_type", ignoreDuplicates: true });
      if (edgeErr) edgeError = edgeErr.message;
    }

    return json({
      source_type: "email",
      status: er.status,
      pointer_id: eventId,
      occurred_at: body.event.occurred_at || null,
      entities: entityResults,
      edges: edgeRows.length,
      edge_error: edgeError,
      duration_ms: Date.now() - started,
    }, 200);
  } catch (err) {
    return json({ error: (err as Error).message }, 500);
  }

  function json(payload: unknown, status: number) {
    return new Response(JSON.stringify(payload), {
      status, headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
