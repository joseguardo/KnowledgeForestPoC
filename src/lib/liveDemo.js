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
};

/* ── CRM: create, then re-ingest to watch merge + enrichment ─────── */

export function crmCreate() {
  return invoke(DEMO_REQUESTS.crmCreate.fn, DEMO_REQUESTS.crmCreate.body);
}

export function crmEnrich() {
  return invoke(DEMO_REQUESTS.crmEnrich.fn, DEMO_REQUESTS.crmEnrich.body);
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

/* ── Cleanup ──────────────────────────────────────────────────────── */

export function resetDemo() {
  return invoke("demo-reset", {});
}
