import { createClient } from "@supabase/supabase-js";
import { supabase } from "./supabase";

/**
 * Live, executable examples for the explainer page. Every call hits the real
 * deployed backend. All created entities are namespaced — canonical_key
 * "demo:*" or "(demo)" in the label — so the demo-reset Edge Function can
 * wipe them without ever touching real knowledge-graph data.
 *
 * DEMO_REQUESTS is the single source of truth: the UI renders these exact
 * objects as "the request being sent", and the exec functions send them.
 */

async function invoke(name, body) {
  if (!supabase) throw new Error("Supabase client not configured (.env.local missing)");
  const { data, error } = await supabase.functions.invoke(name, { body });
  if (error) throw new Error(error.message || "Edge Function call failed");
  return data;
}

const MEMO_CONTENT = `# Company Overview

Aurora Robotics builds autonomous warehouse robots for mid-size logistics operators in Southern Europe.

# Financials

Revenue reached $2M with a pipeline of 14 pilot deployments. Gross margins improve with each hardware revision.

# Team

Founded by two robotics PhDs from IST Lisbon; 18 employees across engineering and field operations.`;

export const DEMO_REQUESTS = {
  crmCreate: {
    fn: "insert-pointer",
    body: {
      label: "Aurora Robotics (demo)",
      type: "company",
      canonical_key: "demo:aurora-robotics",
      occurred_at: "2026-04-02T00:00:00Z",
      attributes: [
        { key: "Revenue", value: "$1M", sort_order: 1 },
        { key: "HQ", value: "Lisbon", sort_order: 2 },
        {
          // One attribute, one whole CRM record: structured, use-case-specific
          // state lives side by side with flat facts on the same card.
          key: "Affinity",
          data_type: "json",
          source: "affinity",
          sort_order: 4,
          value: {
            name: "Aurora Robotics",
            url: "https://aurorarobotics.eu",
            source: "Intro — María García (Acme Corp)",
            funnel_stage: "Screening",
            owner: "deal-team",
          },
        },
      ],
    },
  },
  crmEnrich: {
    fn: "insert-pointer",
    body: {
      label: "Aurora Robotics (demo)",
      type: "company",
      canonical_key: "demo:aurora-robotics",
      attributes: [
        { key: "Revenue", value: "$2M", sort_order: 1 },
        { key: "Stage", value: "Series A", sort_order: 3 },
        {
          key: "Affinity",
          data_type: "json",
          source: "affinity",
          sort_order: 4,
          value: {
            name: "Aurora Robotics",
            url: "https://aurorarobotics.eu",
            source: "Intro — María García (Acme Corp)",
            funnel_stage: "Investment Committee",
            ic_date: "2026-06-25",
            owner: "deal-team",
          },
        },
      ],
    },
  },
  memo: {
    fn: "ingest-document",
    body: {
      title: "Aurora Robotics — Overview Memo (demo)",
      occurred_at: "2026-05-20T00:00:00Z",
      chunk_size: 300,
      link: {
        target_canonical_key: "demo:aurora-robotics",
        relationship_type: "describes",
        why: "Demo memo describing Aurora Robotics",
      },
      content: MEMO_CONTENT,
    },
  },
  dupeTypo: {
    fn: "insert-pointer",
    body: {
      label: "Aurora Robotiks (demo)",
      type: "company",
    },
  },
  dupeLookalike: {
    fn: "insert-pointer",
    body: {
      label: "Aurora Robotics Labs (demo)",
      type: "company",
      canonical_key: "demo:aurora-labs",
    },
  },
  ask: (query) => ({
    fn: "query-knowledge",
    body: { query, mode: "answer" },
  }),

  // Company Management: one contact's inbox + calendar as a single interaction
  // stream. Demo-namespaced (canonical_key "demo:*", label "(demo)") and public
  // so the explainer reads them back and demo-reset wipes them.
  companyInbox: {
    fn: "ingest-calendar",
    body: {
      owner: { label: "Robin Calloway (demo)", canonical_key: "demo:person-robin" },
      access_class: "public",
      source: "gmail",
      events: [
        {
          title: "Intro — warehouse automation pilot",
          start: "2026-05-09T08:12:00Z",
          event_type: "email",
          from: "robin@heliosdyn.example",
          notes: "Robin asks for a scoped pilot across two Helios distribution centres.",
          canonical_key: "demo:evt-email-1",
          company: "Helios Dynamics (demo)",
        },
        {
          title: "Re: Pilot rollout timeline",
          start: "2026-05-12T14:48:00Z",
          event_type: "email",
          from: "robin@heliosdyn.example",
          notes: "Wants to confirm dates before the budget review.",
          canonical_key: "demo:evt-email-2",
          company: "Helios Dynamics (demo)",
        },
      ],
    },
  },
  companyCalendar: {
    fn: "ingest-calendar",
    body: {
      owner: { label: "Robin Calloway (demo)", canonical_key: "demo:person-robin" },
      access_class: "public",
      source: "google-calendar",
      events: [
        {
          title: "Discovery call — Helios Dynamics",
          start: "2026-05-14T15:00:00Z",
          end: "2026-05-14T15:45:00Z",
          event_type: "meeting",
          location: "Zoom",
          notes: "Walked through the pilot scope and success metrics.",
          canonical_key: "demo:evt-mtg-1",
          company: "Helios Dynamics (demo)",
        },
        {
          title: "Technical deep-dive",
          start: "2026-05-18T10:30:00Z",
          end: "2026-05-18T11:30:00Z",
          event_type: "meeting",
          location: "Helios HQ",
          notes: "Integration with their WMS; security review owners assigned.",
          canonical_key: "demo:evt-mtg-2",
          company: "Helios Dynamics (demo)",
        },
      ],
    },
  },
};

/* ── CRM: create, then re-ingest to watch merge + enrichment ─────── */

export function crmCreate() {
  return invoke(DEMO_REQUESTS.crmCreate.fn, DEMO_REQUESTS.crmCreate.body);
}

export function crmEnrich() {
  return invoke(DEMO_REQUESTS.crmEnrich.fn, DEMO_REQUESTS.crmEnrich.body);
}

/* ── Company Management: a contact's inbox + calendar as one timeline ── */

export function companySyncInbox() {
  return invoke(DEMO_REQUESTS.companyInbox.fn, DEMO_REQUESTS.companyInbox.body);
}

export async function companyConnectCalendar() {
  // Ensure the contact card exists first (idempotent), then add the meetings.
  await companySyncInbox();
  return invoke(DEMO_REQUESTS.companyCalendar.fn, DEMO_REQUESTS.companyCalendar.body);
}

/* ── Documents: real ingestion with fingerprint, chunks, link ────── */

export async function ingestMemo() {
  // Make sure the company card exists so the memo has something to link to
  // (idempotent: if it exists, this merges and changes nothing).
  await crmCreate();
  return invoke(DEMO_REQUESTS.memo.fn, DEMO_REQUESTS.memo.body);
}

/* ── Duplicates: typo merges, lookalike with own ID goes to review ── */

export async function dupeTypo() {
  // The typo only demonstrates a merge if the real card exists to merge into.
  await crmCreate();
  return invoke(DEMO_REQUESTS.dupeTypo.fn, DEMO_REQUESTS.dupeTypo.body);
}

export async function dupeLookalike() {
  await crmCreate();
  return invoke(DEMO_REQUESTS.dupeLookalike.fn, DEMO_REQUESTS.dupeLookalike.body);
}

/* ── Two doors: agent question + deterministic search ────────────── */

export function askKnowledge(query) {
  const req = DEMO_REQUESTS.ask(query);
  return invoke(req.fn, req.body);
}

export async function runSearch({ type = "company", queryText = "", limit = 5 } = {}) {
  if (!supabase) throw new Error("Supabase client not configured (.env.local missing)");
  const params = {
    p_types: type === "any" ? null : [type],
    p_query_text: queryText.trim() ? queryText.trim() : null,
    p_limit: limit,
  };
  const { data, error } = await supabase.rpc("search_pointers", params);
  if (error) throw new Error(error.message);
  return { params, data };
}

/* ── Access control: the same search, two clearances ──────────────────
   The exact same search_pointers request is run as two identities so the
   explainer can show what Row-Level Security lets through. We use dedicated
   non-persisting clients (not the page's shared session) so the two columns are
   always a true Analyst-vs-Partner comparison, whatever the rest of the app is
   signed in as. "Analyst" = anonymous (public class only); "Partner" = the
   seeded demo account granted the confidential + restricted classes. */

const PARTNER_DEMO = { email: "partner@kibo.demo", password: "kibo-partner" };
let _anonClient = null;
let _partnerClient = null;

function makeClient(storageKey) {
  const url = import.meta.env.VITE_SUPABASE_URL;
  const key = import.meta.env.VITE_SUPABASE_ANON_KEY;
  if (!url || !key) throw new Error("Supabase client not configured (.env.local missing)");
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false, storageKey },
  });
}

function anonClient() {
  if (!_anonClient) _anonClient = makeClient("kf-demo-analyst");
  return _anonClient;
}

async function partnerClient() {
  if (_partnerClient) return _partnerClient;
  const c = makeClient("kf-demo-partner");
  const { error } = await c.auth.signInWithPassword(PARTNER_DEMO);
  if (error) throw new Error("Demo Partner sign-in failed: " + error.message);
  _partnerClient = c;
  return c;
}

export async function runSearchClearances({ type = "any", queryText = "", limit = 8 } = {}) {
  const params = {
    p_types: type === "any" ? null : [type],
    p_query_text: queryText.trim() ? queryText.trim() : null,
    p_limit: limit,
  };
  const pc = await partnerClient();
  const [analyst, partner] = await Promise.all([
    anonClient().rpc("search_pointers", params),
    pc.rpc("search_pointers", params),
  ]);
  if (analyst.error) throw new Error(analyst.error.message);
  if (partner.error) throw new Error(partner.error.message);
  return { params, analyst: analyst.data, partner: partner.data };
}

/* ── Cleanup ──────────────────────────────────────────────────────── */

export function resetDemo() {
  return invoke("demo-reset", {});
}
