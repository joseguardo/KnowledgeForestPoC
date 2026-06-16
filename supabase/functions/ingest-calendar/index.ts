import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

// Ingests one person's calendar into the memory layer (Affinity-style).
// Each meeting becomes an 'event' pointer (occurred_at = start time); the
// owner and every attendee/company are run through insert_pointer_with_dedup
// so meetings auto-link to people already in the forest. Edges:
//   owner  --attended-->     event
//   event  --attended_by-->  attendee (person)
//   event  --regarding-->    company

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

const PUBLIC_CLASS_ID = "00000000-0000-0000-0000-000000000001";
const MAX_EVENTS = 100;

interface Entity {
  label: string;
  canonical_key?: string;
  type?: string; // 'person' (default) | 'company'
}

interface CalEvent {
  title: string;
  start: string;          // ISO datetime → occurred_at
  end?: string;
  location?: string;
  notes?: string;
  event_type?: string;    // 'meeting' (default) | 'email' | …
  from?: string;          // sender, for emails
  canonical_key?: string; // override (else event:<owner>:<start>)
  attendees?: Entity[];   // people in the meeting
  company?: string;       // company the meeting is about (by label)
}

interface CalRequest {
  owner: Entity;          // whose calendar this is
  events: CalEvent[];
  access_class?: string;  // default class for everything created
  source?: string;
}

async function classResolver(supabase: ReturnType<typeof createClient>) {
  const { data } = await supabase.from("access_classes").select("id,key");
  const idByKey: Record<string, string> = {};
  (data || []).forEach((c: { id: string; key: string }) => { idByKey[c.key] = c.id; });
  return (key?: string) => idByKey[key || "public"] || PUBLIC_CLASS_ID;
}

// One embedding API call for a list of texts; nulls if no key / on failure.
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

    const body: CalRequest = await req.json();
    if (!body.owner?.label) {
      return json({ error: "owner.label is required" }, 400);
    }
    if (!Array.isArray(body.events) || body.events.length === 0) {
      return json({ error: "events array is required" }, 400);
    }
    if (body.events.length > MAX_EVENTS) {
      return json({ error: `too many events: max ${MAX_EVENTS}` }, 400);
    }

    const defaultClass = body.access_class || "confidential";
    const resolveClass = await classResolver(supabase);
    const edgeClassId = resolveClass(defaultClass);

    // ── 1. Resolve every distinct entity (owner + attendees + companies) ──
    // Keyed by "type:label" so the same person across meetings is inserted once.
    const entities = new Map<string, Entity>();
    const keyOf = (e: Entity) => `${e.type || "person"}::${e.label}`;
    const addEntity = (e: Entity) => { if (e?.label) entities.set(keyOf(e), { ...e, type: e.type || "person" }); };

    addEntity({ ...body.owner, type: "person" });
    for (const ev of body.events) {
      (ev.attendees || []).forEach((a) => addEntity({ ...a, type: a.type || "person" }));
      if (ev.company) addEntity({ label: ev.company, type: "company" });
    }

    const entityList = [...entities.values()];
    const entityEmb = await getEmbeddings(entityList.map((e) => e.label));
    const idByKey = new Map<string, string>();
    const entityResults: Record<string, unknown>[] = [];

    for (let i = 0; i < entityList.length; i++) {
      const e = entityList[i];
      const { data: r, error } = await supabase.rpc("insert_pointer_with_dedup", {
        p_label: e.label,
        p_type: e.type,
        p_canonical_key: e.canonical_key || null,
        p_metadata: {},
        p_embedding: entityEmb[i] ? JSON.stringify(entityEmb[i]) : null,
        p_access_class: defaultClass,
      });
      if (error || !r?.pointer_id) {
        entityResults.push({ label: e.label, status: "error", error: error?.message || "no id" });
        continue;
      }
      idByKey.set(keyOf(e), r.pointer_id);
      entityResults.push({ label: e.label, type: e.type, status: r.status, pointer_id: r.pointer_id });
    }

    const ownerId = idByKey.get(`person::${body.owner.label}`);

    // ── 2. One event pointer per meeting + edges to participants ──
    const eventEmb = await getEmbeddings(
      body.events.map((ev) => `${ev.title} ${ev.notes || ""}`.trim())
    );

    const results: Record<string, unknown>[] = [];
    const errors: string[] = [];

    for (let i = 0; i < body.events.length; i++) {
      const ev = body.events[i];
      if (!ev.title || !ev.start) {
        const msg = `event #${i}: title and start are required`;
        errors.push(msg);
        results.push({ index: i, status: "error", error: msg });
        continue;
      }

      const canonicalKey = ev.canonical_key || `event:${body.owner.label}:${ev.start}`;
      const { data: r, error } = await supabase.rpc("insert_pointer_with_dedup", {
        p_label: ev.title,
        p_type: "event",
        p_canonical_key: canonicalKey,
        p_metadata: {
          event_type: ev.event_type || "meeting",
          location: ev.location || null,
          notes: ev.notes || null,
          end: ev.end || null,
          from: ev.from || null,
        },
        p_embedding: eventEmb[i] ? JSON.stringify(eventEmb[i]) : null,
        p_access_class: defaultClass,
      });

      if (error || !r?.pointer_id) {
        const msg = `event #${i} (${ev.title}): ${error?.message || "no id"}`;
        errors.push(msg);
        results.push({ index: i, label: ev.title, status: "error", error: msg });
        continue;
      }

      const eventId = r.pointer_id as string;

      // occurred_at = meeting start (don't clobber an existing value on merge).
      const occUpdate = r.status === "merged"
        ? supabase.from("pointers").update({ occurred_at: ev.start }).eq("id", eventId).is("occurred_at", null)
        : supabase.from("pointers").update({ occurred_at: ev.start }).eq("id", eventId);
      await occUpdate;

      // Build edges: owner attended; event attended_by each person; event regarding company.
      const edgeRows: Record<string, unknown>[] = [];
      if (ownerId) {
        edgeRows.push({
          source_id: ownerId, target_id: eventId, relationship_type: "attended",
          why: `${body.owner.label} attended this meeting`, access_class_id: edgeClassId,
        });
      }
      for (const a of ev.attendees || []) {
        const aid = idByKey.get(`${a.type || "person"}::${a.label}`);
        if (aid && aid !== eventId) {
          edgeRows.push({
            source_id: eventId, target_id: aid, relationship_type: "attended_by",
            why: `${a.label} was in this meeting`, access_class_id: edgeClassId,
          });
        }
      }
      if (ev.company) {
        const cid = idByKey.get(`company::${ev.company}`);
        if (cid) {
          edgeRows.push({
            source_id: eventId, target_id: cid, relationship_type: "regarding",
            why: `Meeting about ${ev.company}`, access_class_id: edgeClassId,
          });
        }
      }

      const entry: Record<string, unknown> = {
        index: i, label: ev.title, status: r.status, pointer_id: eventId,
        occurred_at: ev.start, edges: edgeRows.length,
      };

      if (edgeRows.length > 0) {
        const { error: edgeErr } = await supabase
          .from("edges")
          .upsert(edgeRows, { onConflict: "source_id,target_id,relationship_type", ignoreDuplicates: true });
        if (edgeErr) entry.edge_error = edgeErr.message;
      }

      results.push(entry);
    }

    return json({
      source_type: "calendar",
      owner: { label: body.owner.label, pointer_id: ownerId },
      items_produced: results.filter((r) => r.status !== "error").length,
      entities: entityResults,
      results,
      errors,
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
