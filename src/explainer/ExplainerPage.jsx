import { useEffect, useRef, useState } from "react";
import {
  DEMO_REQUESTS,
  crmCreate,
  crmEnrich,
  ingestMemo,
  dupeTypo,
  dupeLookalike,
  askKnowledge,
  runSearch,
  resetDemo,
} from "../lib/liveDemo";
import "./explainer.css";

/* Adds .visible when the element scrolls into view (fires once). */
function Reveal({ children, delay = 0, as: Tag = "div", className = "" }) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Already in view on mount (or no observer support): show immediately.
    const rect = el.getBoundingClientRect();
    if (typeof IntersectionObserver === "undefined" || rect.top < window.innerHeight * 0.95) {
      el.classList.add("visible");
      return;
    }

    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.classList.add("visible");
          obs.disconnect();
        }
      },
      { threshold: 0.18 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  return (
    <Tag ref={ref} className={`xp-reveal ${className}`} style={delay ? { transitionDelay: `${delay}ms` } : undefined}>
      {children}
    </Tag>
  );
}

/* ── Minimal line icons (Attio-style) ─────────────────────────────── */

function Icon({ d, ...props }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {Array.isArray(d) ? d.map((p, i) => <path key={i} d={p} />) : <path d={d} />}
    </svg>
  );
}

const ICONS = {
  card: ["M3 5h18v14H3z", "M7 9h6", "M7 13h10", "M7 17h4"],
  thread: ["M9 15l6-6", "M11 5l1-1a4 4 0 015.7 5.7l-1 1", "M13 19l-1 1a4 4 0 01-5.7-5.7l1-1"],
  tree: ["M12 3v18", "M12 9c-2.5 0-4.5-2-4.5-4.5C10 4.5 12 6 12 9z", "M12 13c2.5 0 5-2 5-5 -3 0-5 2-5 5z", "M12 17c-3 0-5.5-2-5.5-5 3.5 0 5.5 2.5 5.5 5z", "M8 21h8"],
  moon: ["M21 13A8.5 8.5 0 0111 3a8.5 8.5 0 1010 10z"],
  search: ["M11 19a8 8 0 100-16 8 8 0 000 16z", "M21 21l-4.3-4.3"],
  chat: ["M21 12a8 8 0 01-8 8H4l2-3a8 8 0 1115-5z", "M9 11h6"],
  sliders: ["M4 8h10", "M18 8h2", "M14 6v4", "M4 16h2", "M10 16h10", "M8 14v4"],
  id: ["M3 5h18v14H3z", "M7 12a2 2 0 104 0 2 2 0 00-4 0z", "M6 16c.5-1.5 1.7-2 3-2s2.5.5 3 2", "M15 10h4", "M15 14h3"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13", "M10 11v5", "M14 11v5"],
};

/* ── Live-call plumbing ───────────────────────────────────────────── */

function useLive(fn, onWrite) {
  const [state, setState] = useState({ loading: false, result: null, error: null });

  const run = async (...args) => {
    setState({ loading: true, result: null, error: null });
    try {
      const result = await fn(...args);
      setState({ loading: false, result, error: null });
      onWrite?.();
      return result;
    } catch (e) {
      setState({ loading: false, result: null, error: e.message || String(e) });
      return null;
    }
  };

  return { ...state, run };
}

const STATUS_CHIP = {
  created: { cls: "created", label: "created" },
  merged: { cls: "merged", label: "merged" },
  pending_review: { cls: "pending", label: "pending review" },
  clean: { cls: "clean", label: "cleaned" },
};

function StatusChip({ status }) {
  const c = STATUS_CHIP[status] || { cls: "clean", label: status };
  return <span className={`xp-chip ${c.cls}`}>{c.label}</span>;
}

function RawJson({ data }) {
  return (
    <details>
      <summary>Raw response from the live system</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

/* Renders the literal request a button sends — the same object the call
   uses, so the preview can never drift from what actually goes out. */
function RequestPreview({ req, label = "The exact request being sent", note }) {
  return (
    <div className="xp-reqpreview">
      <span className="lab">{label}</span>
      <pre style={{ marginTop: 6 }}>{`POST /functions/v1/${req.fn}\n${JSON.stringify(req.body, null, 2)}`}</pre>
      {note && <p className="xp-reqnote">{note}</p>}
    </div>
  );
}

function LiveError({ error }) {
  return (
    <div className="xp-live-result">
      <div className="xp-chips">
        <span className="xp-chip error">error</span>
        <span style={{ fontSize: 12.5, color: "#fca5a5" }}>{error}</span>
      </div>
    </div>
  );
}

function pct(x) {
  return `${Math.round(Number(x) * 1000) / 10}%`;
}

function shortId(id) {
  return id ? `${String(id).slice(0, 8)}…` : "—";
}

/* ── Hero: the memory at a glance ─────────────────────────────────── */
function HeroGraph() {
  /* Geometry is computed, not eyeballed: hub at (380,150) r=42, four
     satellites r=26 placed symmetrically at (±230,±86) from the hub.
     Edges are trimmed to the circle boundaries (with clearance for the
     ±6px float animation) so the dashes never pierce a node, and each
     edge points along its relationship's real direction. */
  const HUB = { x: 380, y: 150, r: 42 };
  const SAT_R = 26;
  const HUB_GAP = 10; // edge starts this far off the hub's rim
  const SAT_GAP = 14; // and ends this far off the satellite's rim (float headroom)

  const sats = [
    { x: 150, y: 64,  float: "xp-float-a", avatar: "DOC", label: "Series A deck",  rel: "describes",       toHub: true },
    { x: 610, y: 64,  float: "xp-float-b", avatar: "MG",  label: "María García",   rel: "CEO of",          toHub: true },
    { x: 150, y: 236, float: "xp-float-c", avatar: "@",   label: "Email thread",   rel: "12 emails about", toHub: true },
    { x: 610, y: 236, float: "xp-float-a", avatar: "SEC", label: "Cybersecurity",  rel: "operates in",     toHub: false },
  ];

  const edges = sats.map((s) => {
    const dx = s.x - HUB.x, dy = s.y - HUB.y;
    const len = Math.hypot(dx, dy);
    const ux = dx / len, uy = dy / len;
    const hub = { x: HUB.x + ux * (HUB.r + HUB_GAP), y: HUB.y + uy * (HUB.r + HUB_GAP) };
    const sat = { x: s.x - ux * (SAT_R + SAT_GAP), y: s.y - uy * (SAT_R + SAT_GAP) };
    // arrow follows the relationship: satellite -> hub, except "operates in"
    const [from, to] = s.toHub ? [sat, hub] : [hub, sat];
    return { from, to, mid: { x: (hub.x + sat.x) / 2, y: (hub.y + sat.y) / 2 }, rel: s.rel };
  });

  return (
    <svg className="xp-herograph" viewBox="0 0 760 300" fill="none" aria-hidden="true">
      <defs>
        <marker id="xp-hero-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1l6 3-6 3" fill="none" stroke="#c8c8cd" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
      </defs>

      {edges.map((e) => (
        <line key={e.rel} className="edge" x1={e.from.x} y1={e.from.y} x2={e.to.x} y2={e.to.y} markerEnd="url(#xp-hero-arrow)" />
      ))}

      {edges.map((e) => (
        <text key={e.rel} className="edge-label" x={e.mid.x} y={e.mid.y} textAnchor="middle" dominantBaseline="central">
          {e.rel}
        </text>
      ))}

      <g className="node">
        <circle cx={HUB.x} cy={HUB.y} r={HUB.r + 9} fill="none" stroke="#e4e4e7" strokeDasharray="2 5" />
        <circle cx={HUB.x} cy={HUB.y} r={HUB.r} fill="#16181d" />
        <text className="node-label" x={HUB.x} y={HUB.y - 2} textAnchor="middle" style={{ fill: "#fff" }}>Acme</text>
        <text className="node-sub" x={HUB.x} y={HUB.y + 14} textAnchor="middle" style={{ fill: "rgba(255,255,255,0.72)" }}>one card</text>
      </g>

      {sats.map((s) => (
        <g key={s.label} className={`node ${s.float}`}>
          <circle cx={s.x} cy={s.y} r={SAT_R} fill="#fafafa" stroke="#e4e4e7" />
          <text className="avatar" x={s.x} y={s.y + 4} textAnchor="middle">{s.avatar}</text>
          <text className="node-label" x={s.x} y={s.y + SAT_R + 18} textAnchor="middle">{s.label}</text>
        </g>
      ))}
    </svg>
  );
}

/* ── Inspiration: where the architecture comes from ───────────────── */

const INSPIRATIONS = [
  {
    cat: "Lakehouse architecture",
    tools: ["Databricks / Delta Lake", "Snowflake", "Apache Iceberg"],
    borrow: (
      <>
        The lakehouse proved that <strong>one storage layer can serve every workload</strong>: raw
        data lands once and is progressively refined into curated, queryable entities — the
        medallion pattern — instead of each tool keeping its own silo.
      </>
    ),
    maps: (
      <>Our <strong>one shared memory</strong>: raw arrivals → recognized cards → curated trees, no copies.</>
    ),
  },
  {
    cat: "Vector databases",
    tools: ["pgvector", "Pinecone", "Weaviate", "Qdrant"],
    borrow: (
      <>
        Embeddings as a <strong>first-class index</strong>: approximate-nearest-neighbor structures
        (HNSW) make searching by meaning as cheap as a key lookup — synonyms and paraphrases land
        where exact text never could.
      </>
    ),
    maps: (
      <>Every <strong>card and chunk carries an embedding</strong>, indexed with pgvector HNSW inside Postgres.</>
    ),
  },
  {
    cat: "Search engines",
    tools: ["Elasticsearch / OpenSearch", "Postgres FTS"],
    borrow: (
      <>
        Hybrid ranking: <strong>lexical relevance plus fuzzy matching</strong>, combined into one
        score — so a human query lands on the right record even when the spelling or phrasing
        doesn’t.
      </>
    ),
    maps: (
      <>Our <strong>search contract</strong> blends full-text rank, trigram similarity and embedding distance in one query.</>
    ),
  },
  {
    cat: "Graph databases",
    tools: ["Neo4j", "Amazon Neptune"],
    borrow: (
      <>
        Relationships as <strong>first-class records</strong> — typed, weighted, traversable in a
        single hop — rather than foreign keys an application has to reassemble at read time.
      </>
    ),
    maps: (
      <>Our <strong>threads</strong>: every edge stores type, <strong>why</strong> and weight, and traversal is one indexed lookup.</>
    ),
  },
  {
    cat: "Graph + RAG frameworks",
    tools: ["Microsoft GraphRAG", "LlamaIndex", "LangChain"],
    borrow: (
      <>
        The retrieval-augmented-generation playbook — chunk, embed, retrieve by meaning — plus
        GraphRAG’s key move: <strong>cluster the graph into communities and let an LLM name
        them</strong>, so retrieval can reason over themes.
      </>
    ),
    maps: (
      <>Our <strong>document pipeline</strong> and <strong>forest regrow</strong> — with clusters learned from how your team navigates, not only from the text.</>
    ),
  },
  {
    cat: "Agent memory layers",
    tools: ["Letta / MemGPT", "Zep", "Mem0"],
    borrow: (
      <>
        The agent-memory frameworks treat memory as a <strong>living layer</strong>: entities
        extracted from every interaction, and consolidation that runs while the agent is idle —
        “sleep-time compute”.
      </>
    ),
    maps: (
      <>Our <strong>night cycle</strong>, and why agents log their paths as first-class users of the memory.</>
    ),
  },
];

function InspirationSection() {
  return (
    <section className="xp-section" id="inspiration">
      <Reveal>
        <div className="xp-eyebrow">Introduction · Where this comes from</div>
        <h2 className="xp-h2">Nothing here is invented. The mix is.</h2>
        <p className="xp-lead">
          Every piece of this architecture is a proven pattern from production data
          infrastructure — lakehouses, vector and graph databases, search engines, retrieval
          frameworks. What’s new is composing them on <strong>one shared memory</strong> instead
          of six disconnected systems.
        </p>
      </Reveal>
      <div className="xp-inspo-grid">
        {INSPIRATIONS.map((item, i) => (
          <Reveal key={item.cat} delay={(i % 3) * 90} className="xp-inspo">
            <span className="cat">{item.cat}</span>
            <div className="toolchips">
              {item.tools.map((t) => (
                <span key={t} className="toolchip">{t}</span>
              ))}
            </div>
            <p className="borrow">{item.borrow}</p>
            <p className="maps">{item.maps}</p>
          </Reveal>
        ))}
      </div>
      <Reveal delay={200}>
        <div className="xp-novelty">
          <span className="badge"><Icon d={ICONS.tree} /></span>
          <div>
            <h3>The one ingredient none of them have</h3>
            <p>
              In every platform above, the <strong>structure is fixed</strong> — someone designs the
              pipeline, the schema, the ontology. Here, the organization itself is{" "}
              <strong>learned from usage</strong>: the same shared memory grows different trees for
              different teams, and regrows them as the way you work changes. That’s the experiment
              this PoC exists to test.
            </p>
          </div>
        </div>
      </Reveal>
    </section>
  );
}

/* ── CRM: animated card + real ingestion ──────────────────────────── */
function CrmDemo({ onWrite }) {
  const create = useLive(crmCreate, onWrite);
  const enrich = useLive(crmEnrich, onWrite);
  const [step, setStep] = useState(0); // 0 = idle, 1 = created, 2 = enriched

  const rows =
    step >= 2
      ? [
          { k: "Revenue", v: "$2M", cls: "changed" },
          { k: "HQ", v: "Lisbon", cls: "" },
          { k: "Stage", v: "Series A", cls: "added" },
        ]
      : [
          { k: "Revenue", v: "$1M", cls: "" },
          { k: "HQ", v: "Lisbon", cls: "" },
        ];

  // The structured CRM record, read from the exact request being sent —
  // the card can never show a value the call doesn't carry.
  const affinity = (step >= 2 ? DEMO_REQUESTS.crmEnrich : DEMO_REQUESTS.crmCreate)
    .body.attributes.find((a) => a.key === "Affinity").value;

  const loading = create.loading || enrich.loading;
  const lastResult = enrich.result || create.result;
  const lastError = enrich.error || create.error;

  return (
    <div className="xp-stage">
      <div className="xp-crm-card" style={{ opacity: step === 0 ? 0.45 : 1, transition: "opacity 0.4s ease" }}>
        <div className="xp-crm-head">
          <div className="xp-crm-logo">A</div>
          <div>
            <div className="xp-crm-name">Aurora Robotics</div>
            <div className="xp-crm-sub">company · one card, always</div>
          </div>
        </div>
        <div className="xp-crm-rows">
          {step === 0 ? (
            <div className="xp-crm-row"><span className="k" style={{ color: "#b3b8c2" }}>not in memory yet</span></div>
          ) : (
            <>
              {rows.map((r) => (
                <div key={r.k} className={`xp-crm-row ${r.cls}`}>
                  <span className="k">{r.k}</span>
                  <span className="v">{r.v}</span>
                </div>
              ))}
              <div className="xp-crm-json">
                <div className="head">
                  <span className="k">Affinity</span>
                  <span className="tag">one attribute · whole record</span>
                </div>
                {Object.entries(affinity).map(([k, v]) => (
                  <div key={k} className={`sub ${step >= 2 && (k === "funnel_stage" || k === "ic_date") ? "changed" : ""}`}>
                    <span className="sk">{k}</span>
                    <span className="sv">{v}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="xp-live">
        <div className="xp-live-head"><span className="xp-live-dot" /> Live — these buttons write to the real system</div>
        <div className="xp-live-actions">
          <button
            className="xp-livebtn go"
            disabled={loading}
            onClick={async () => {
              const r = await create.run();
              if (r) setStep(1);
            }}
          >
            {create.loading && <span className="xp-spin" />}1 · Ingest Aurora Robotics
          </button>
          <button
            className="xp-livebtn"
            disabled={loading || step === 0}
            onClick={async () => {
              const r = await enrich.run();
              if (r) setStep(2);
            }}
          >
            {enrich.loading && <span className="xp-spin" />}2 · New intel arrives — re-ingest
          </button>
        </div>

        <RequestPreview
          req={step === 0 ? DEMO_REQUESTS.crmCreate : DEMO_REQUESTS.crmEnrich}
          label={step === 0 ? "What button 1 actually sends" : "What button 2 actually sends"}
          note={
            step === 0
              ? "Note the canonical_key — the company's official ID inside the memory — and the Affinity attribute: a whole CRM record carried as one structured value, next to flat facts like Revenue."
              : "Same canonical_key, new values: Revenue changed, Stage is new — and inside the Affinity record, the deal moved up the funnel to Investment Committee. The system resolves the rest."
          }
        />

        {lastError && <LiveError error={lastError} />}
        {!lastError && lastResult && (
          <div className="xp-live-result">
            <div className="xp-chips">
              <StatusChip status={lastResult.status} />
              <span style={{ fontSize: 12, color: "#9aa3b5" }}>card id {shortId(lastResult.pointer_id)}</span>
            </div>
            <ul className="xp-facts">
              {lastResult.status === "created" && (
                <li>
                  <strong>New card created.</strong> Aurora Robotics is now in memory with 3
                  attributes — two flat facts and one structured record (the Affinity JSON), stored
                  side by side on the same card.
                </li>
              )}
              {lastResult.status === "merged" && (
                <>
                  <li>
                    Recognized as the <strong>same company</strong>{" "}
                    {lastResult.duplicates?.[0] && (
                      <>— matched by <span className="mono">{lastResult.duplicates[0].match_method}</span> at{" "}
                      <strong>{pct(lastResult.duplicates[0].similarity)}</strong></>
                    )}
                  </li>
                  <li>
                    <strong>{lastResult.enriched_attributes ?? 0} attributes enriched</strong> on the existing card —
                    Revenue updated, Stage added, and the Affinity record advanced to{" "}
                    <strong>Investment Committee</strong>. No duplicate created.
                  </li>
                </>
              )}
            </ul>
            <RawJson data={lastResult} />
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Documents: pipeline + real ingestion ─────────────────────────── */
function DocFlow({ onWrite }) {
  const memo = useLive(ingestMemo, onWrite);
  const r = memo.result;

  return (
    <div className="xp-stage">
      <div className="xp-docflow">
        <div className="xp-docstep">
          <div className="num">1</div>
          <div>
            <h4>It gets a fingerprint</h4>
            <p>
              Each document is identified by its own content. The same deck can arrive by email
              today and by upload tomorrow — it is remembered <strong>once</strong>.
            </p>
            {r?.canonical_key && <span className="xp-hashchip">{r.canonical_key.slice(0, 14)}…{r.canonical_key.slice(-6)}</span>}
          </div>
        </div>
        <div className="xp-docstep">
          <div className="num">2</div>
          <div>
            <h4>It is split into readable pieces</h4>
            <p>
              The text is divided along its natural sections, so a question can land on the exact
              paragraph — and the pieces still reassemble into the full document.
            </p>
            <div className="xp-chunkrow">
              <span className="xp-chunk">Company Overview</span>
              <span className="xp-chunk">Financials</span>
              <span className="xp-chunk">Team</span>
            </div>
          </div>
        </div>
        <div className="xp-docstep">
          <div className="num">3</div>
          <div>
            <h4>It ties itself to who it talks about</h4>
            <p>
              The memo links to Aurora Robotics’ card with a reason attached:{" "}
              <em>“describes this company.”</em> Open the company later and the memo is simply there.
            </p>
          </div>
        </div>
      </div>

      <div className="xp-live">
        <div className="xp-live-head"><span className="xp-live-dot" /> Live — ingest a real memo, twice</div>
        <div className="xp-live-actions">
          <button className="xp-livebtn go" disabled={memo.loading} onClick={() => memo.run()}>
            {memo.loading && <span className="xp-spin" />}
            {r ? "Send the exact same memo again" : "Ingest the Aurora memo"}
          </button>
        </div>

        <RequestPreview
          req={DEMO_REQUESTS.memo}
          label="What this button actually sends"
          note="The content field is the whole memo — the fingerprint is computed from it server-side. The link block is what ties the document to the company."
        />

        {memo.error && <LiveError error={memo.error} />}
        {!memo.error && r && (
          <div className="xp-live-result">
            <div className="xp-chips">
              <StatusChip status={r.status} />
              <span style={{ fontSize: 12, color: "#9aa3b5" }}>document id {shortId(r.pointer_id)}</span>
            </div>
            <ul className="xp-facts">
              {r.status === "created" ? (
                <>
                  <li>Fingerprinted as <span className="mono">{r.canonical_key.slice(0, 18)}…</span></li>
                  <li><strong>{r.chunks_inserted} readable pieces</strong> stored, each searchable by meaning.</li>
                  {r.link?.status === "created" && (
                    <li>Linked to Aurora Robotics — <span className="mono">{r.link.relationship_type}</span>.</li>
                  )}
                </>
              ) : (
                <>
                  <li>
                    <strong>Recognized by its fingerprint.</strong> Same content → same document. Nothing was stored
                    twice ({r.chunks_inserted} new pieces).
                  </li>
                  {r.link?.status === "already_linked" && <li>The link to Aurora Robotics already exists — not duplicated either.</li>}
                </>
              )}
            </ul>
            <RawJson data={r} />
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Relationships hub diagram ────────────────────────────────────── */
function HubDiagram() {
  return (
    <div className="xp-stage">
      <svg className="xp-hub" viewBox="0 0 460 330" fill="none" aria-hidden="true">
        <line className="spoke" x1="230" y1="165" x2="92" y2="62" />
        <line className="spoke" x1="230" y1="165" x2="372" y2="62" />
        <line className="spoke" x1="230" y1="165" x2="78" y2="266" />
        <line className="spoke" x1="230" y1="165" x2="384" y2="266" />

        <text className="spoke-label" x="128" y="112">describes</text>
        <text className="spoke-label" x="296" y="110">works at</text>
        <text className="spoke-label" x="122" y="232">about</text>
        <text className="spoke-label" x="298" y="230">sector</text>

        <g className="node">
          <circle cx="230" cy="165" r="52" fill="#7c3aed" />
          <text className="hub-label" x="230" y="162" textAnchor="middle">Acme</text>
          <text className="hub-sub" x="230" y="180" textAnchor="middle">THE MEETING POINT</text>
        </g>

        <g className="xp-float-a">
          <circle cx="92" cy="62" r="24" fill="#fafafa" stroke="#e4e4e7" />
          <text className="avatar" x="92" y="66" textAnchor="middle">DOC</text>
          <text className="sat-label" x="92" y="100" textAnchor="middle">deck</text>
        </g>
        <g className="xp-float-b">
          <circle cx="372" cy="62" r="24" fill="#fafafa" stroke="#e4e4e7" />
          <text className="avatar" x="372" y="66" textAnchor="middle">MG</text>
          <text className="sat-label" x="372" y="100" textAnchor="middle">María</text>
        </g>
        <g className="xp-float-c">
          <circle cx="78" cy="266" r="24" fill="#fafafa" stroke="#e4e4e7" />
          <text className="avatar" x="78" y="270" textAnchor="middle">@</text>
          <text className="sat-label" x="78" y="303" textAnchor="middle">emails</text>
        </g>
        <g className="xp-float-b">
          <circle cx="384" cy="266" r="24" fill="#fafafa" stroke="#e4e4e7" />
          <text className="avatar" x="384" y="270" textAnchor="middle">SEC</text>
          <text className="sat-label" x="384" y="303" textAnchor="middle">cyber</text>
        </g>
      </svg>
    </div>
  );
}

/* ── How links are created: edge examples ─────────────────────────── */

function EdgeExample({ from, fromSub, rel, to, toSub, why }) {
  return (
    <div className="xp-edge">
      <div className="xp-edge-row">
        <span className="xp-node">
          {from}
          <em>{fromSub}</em>
        </span>
        <span className="xp-edge-rel">
          <span className="rel">{rel}</span>
          <span className="arrow">⟶</span>
        </span>
        <span className="xp-node">
          {to}
          <em>{toSub}</em>
        </span>
      </div>
      <div className="xp-edge-why">
        <strong>why:</strong> “{why}”
      </div>
    </div>
  );
}

function Tech({ steps, code, codeLabel = "The actual logic, verbatim" }) {
  return (
    <details className="xp-tech">
      <summary>Technical detail — exact mechanics, from the deployed code</summary>
      <ol className="xp-tech-steps">
        {steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
      {code && (
        <>
          <span className="lab">{codeLabel}</span>
          <pre>{code}</pre>
        </>
      )}
    </details>
  );
}

/* A narrated real-world walkthrough: who triggers it, the stage-by-stage
   lifecycle, and the literal operation that executes. Kept consistent with
   DEMO_REQUESTS / the deployed SQL so it can never drift from the system. */
function Lifecycle({ scenario, stages, op, opLabel = "The operation that actually executes" }) {
  return (
    <div className="xp-lifecycle">
      <span className="lab">Real use case — the full lifecycle</span>
      <p className="scenario">{scenario}</p>
      <ol className="stages">
        {stages.map((s, i) => (
          <li key={i}>
            <span className="stage">{s.t}</span>
            <span className="what">{s.d}</span>
          </li>
        ))}
      </ol>
      {op && (
        <>
          <span className="lab op">{opLabel}</span>
          <pre>{op}</pre>
        </>
      )}
    </div>
  );
}

function LinksSection() {
  return (
    <section className="xp-section">
      <Reveal>
        <div className="xp-eyebrow accent-violet">Under the hood · Links</div>
        <h2 className="xp-h2">How a link actually gets created</h2>
        <p className="xp-lead">
          Nobody draws these threads by hand. Every link in the memory is created by one of four
          mechanisms — and every one of them stores a <strong>reason</strong> you can read back
          later. Each card below has a technical-detail drawer with the exact mechanics, taken
          from the deployed code.
        </p>
      </Reveal>

      <div className="xp-mechs">
        <Reveal delay={0} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">1</span>
            <h3>Declared — the source says so</h3>
          </div>
          <p>
            When something arrives <strong>with context</strong>, the link is written directly. The
            memo you ingested above carried a <code>link</code> block in its request — that one
            field became this thread, instantly:
          </p>
          <div className="xp-edges">
            <EdgeExample
              from="Overview Memo"
              fromSub="document"
              rel="describes"
              to="Aurora Robotics"
              toSub="company"
              why="Demo memo describing Aurora Robotics"
            />
          </div>
          <Lifecycle
            scenario={
              <>
                An analyst finishes the <strong>Aurora overview memo</strong> and drops it into the
                data room. The upload tool knows which company the memo belongs to, so the
                ingestion request carries the link in its own body — nothing is inferred.
              </>
            }
            stages={[
              {
                t: "Arrival",
                d: <>The memo hits <code>POST /functions/v1/ingest-document</code> with a <code>link</code> block naming the target, the relationship and the reason.</>,
              },
              {
                t: "Resolve",
                d: <><code>target_canonical_key: "demo:aurora-robotics"</code> is looked up on the unique index and lands on Aurora’s card — no scoring, no model, the first waterfall match wins.</>,
              },
              {
                t: "Write",
                d: <>One row goes into <code>edges</code>: source (the memo), target (Aurora), <code>describes</code>, the why, weight 1.0.</>,
              },
              {
                t: "Guard",
                d: <>The analyst re-uploads the memo next week — the database’s uniqueness constraint answers <code>already_linked</code>. A second row is impossible by construction.</>,
              },
              {
                t: "Visible",
                d: <>Anyone opening Aurora’s card now finds the memo among its threads, with the stored reason readable: <em>“Demo memo describing Aurora Robotics.”</em></>,
              },
            ]}
            op={`POST /functions/v1/ingest-document
{
  "title": "Aurora Robotics — Overview Memo",
  "content": "...",
  "link": {
    "target_canonical_key": "demo:aurora-robotics",
    "relationship_type":    "describes",
    "why": "Demo memo describing Aurora Robotics"
  }
}`}
          />
          <Tech
            steps={[
              <>
                <strong>Resolve the target</strong> through a three-step waterfall:{" "}
                <code>target_id</code> (a direct UUID) → <code>target_canonical_key</code> (lookup
                on the unique index) → <code>target_label</code> (exact name match). The first
                match wins; declared links never use probabilistic matching.
              </>,
              <>
                <strong>Insert one row</strong> into <code>edges</code> with the five fields:
                source, target, <code>relationship_type</code>, <code>why</code>, <code>weight</code>.
              </>,
              <>
                <strong>Uniqueness is enforced by the database</strong> on (source, target, type) —
                declaring the same link twice returns <code>already_linked</code>, it can never
                create a second row. You saw this when you re-sent the memo.
              </>,
            ]}
            code={`INSERT INTO edges (source_id, target_id, relationship_type, why, weight)
VALUES (:memo_id, :aurora_id, 'describes',
        'Demo memo describing Aurora Robotics', 1.0);
-- unique (source_id, target_id, relationship_type)
--   second attempt -> 409 already_linked, never a duplicate row`}
          />
        </Reveal>

        <Reveal delay={90} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">2</span>
            <h3>Recognized — the system works it out</h3>
          </div>
          <p>
            Most things arrive <strong>without</strong> context. An email lands from{" "}
            <code>maria@acme.com</code> with the subject “Series A follow-up”. The ingestion reads
            the signals, resolves each one against memory (the same duplicate engine you challenged
            above), and writes one link per recognized signal:
          </p>
          <div className="xp-edges">
            <EdgeExample
              from="Series A follow-up"
              fromSub="email"
              rel="sent_by"
              to="María García"
              toSub="person"
              why="From: header — maria@acme.com"
            />
            <EdgeExample
              from="Series A follow-up"
              fromSub="email"
              rel="about"
              to="Acme Corp"
              toSub="company"
              why="Sender domain acme.com matches the company’s domain"
            />
            <EdgeExample
              from="María García"
              fromSub="person"
              rel="works_at"
              to="Acme Corp"
              toSub="company"
              why="Email address on the company’s domain"
            />
          </div>
          <p style={{ margin: "14px 0 0" }}>
            If María wasn’t in memory yet, her card is created first — link creation and duplicate
            handling are <strong>the same machinery</strong>, which is why a typo in her name can’t
            produce a second María.
          </p>
          <Lifecycle
            scenario={
              <>
                The <strong>03:00 nightly fetch</strong> pulls María’s email “Series A follow-up”
                from the shared inbox. Nobody tagged it, nobody will — the message carries nothing
                but its own headers and body.
              </>
            }
            stages={[
              {
                t: "Signals",
                d: <>The ingestion reads <code>From: maria@acme.com</code> → candidate <em>“María García” / person</em>; the sender domain → candidate <em>“acme.com” / company</em>.</>,
              },
              {
                t: "Embed",
                d: <>Each candidate label gets its embedding in the Edge Function, so the next step can compare by meaning as well as spelling.</>,
              },
              {
                t: "Score",
                d: <><code>check_duplicates()</code> compares each candidate against every same-type card — <code>GREATEST(</code>trigram<code>, </code>cosine<code>)</code>. María’s existing card comes back at ≈ 95%.</>,
              },
              {
                t: "Decide",
                d: <>95% ≥ the 0.80 merge threshold → the email resolves to the <strong>existing</strong> María. No new card, no second María — ever.</>,
              },
              {
                t: "Write",
                d: <>Three edges are inserted — <code>sent_by</code>, <code>about</code>, <code>works_at</code> — each with <code>why</code> set to the evidence that resolved it, so the link is auditable later.</>,
              },
              {
                t: "Morning",
                d: <>Before anyone opens a laptop, the email already sits on Acme’s card, threaded to María — filed by the system, not by a person.</>,
              },
            ]}
            op={`-- per candidate signal, inside check_duplicates():
SELECT GREATEST(similarity(p.label, 'María García'),
                1.0 - (p.embedding <=> :emb)) AS score
FROM pointers p WHERE p.type = 'person'
ORDER BY score DESC LIMIT 10;          -- → 0.95, merge

-- then, one edge per recognized signal:
INSERT INTO edges (source_id, target_id, relationship_type, why, weight)
VALUES (:email_id, :maria_id, 'sent_by',
        'From: header — maria@acme.com', 1.0);`}
          />
          <Tech
            steps={[
              <>
                <strong>Extract signals</strong> from the arriving item: the <code>From:</code>{" "}
                header, the sender’s domain, names mentioned in the body. Each signal becomes a
                candidate (label, type) pair — “María García” / person, “acme.com” / company.
              </>,
              <>
                <strong>Embed the label</strong> in the Edge Function (text-embedding-3-small,
                1,536 dimensions) so the candidate can be compared by meaning, not just spelling.
              </>,
              <>
                <strong>Score against memory</strong> inside Postgres: an exact{" "}
                <code>canonical_key</code> hit short-circuits at 100%. Otherwise every existing card{" "}
                <strong>of the same type</strong> is scored two ways — spelling similarity (trigram
                comparison of three-character fragments, GiST-indexed) and meaning similarity
                (embedding cosine, HNSW-indexed) — and the final score is the{" "}
                <strong>greater of the two</strong>. Trigram matching catches typos that embedding
                similarity misses (“Robotiks”); embeddings catch synonyms that no spelling
                comparison can see (“Alphabet” ≈ “Google”).
              </>,
              <>
                <strong>Decide by threshold</strong> — the cutoffs live in <code>system_config</code>,
                tunable without redeploying: ≥ 0.80 merge into the existing card · 0.40–0.80 write a{" "}
                <code>duplicate_flags</code> row for human review · &lt; 0.40 create a new card. The
                passport rule overrides: differing canonical keys force review at any score.
              </>,
              <>
                <strong>Only then write the edge</strong>, with <code>why</code> set to the evidence
                that resolved it — so every recognized link is auditable later.
              </>,
            ]}
            code={`-- the actual scoring inside check_duplicates()
SELECT GREATEST(
  similarity(p.label, :incoming_label),        -- pg_trgm, GiST index
  1.0 - (p.embedding <=> :incoming_embedding)  -- cosine, HNSW index
) AS score
FROM pointers p
WHERE p.type = :incoming_type                  -- companies never match people
ORDER BY score DESC LIMIT 10;

-- >= 0.80 merge | 0.40-0.80 human review | < 0.40 new card
-- (thresholds read from system_config at call time)`}
          />
        </Reveal>

        <Reveal delay={180} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">3</span>
            <h3>Converged — same fingerprint, same thing</h3>
          </div>
          <p>
            María attached <code>deck_v3.pdf</code> to her email. Someone on your team also uploaded
            it to the data room. Both copies hash to the <strong>same fingerprint</strong>, so they
            become one document — and the system discovers a link nobody asked for:
          </p>
          <div className="xp-edges">
            <EdgeExample
              from="Series A follow-up"
              fromSub="email"
              rel="attached"
              to="deck_v3.pdf"
              toSub="document · one copy"
              why="Attachment hash equals the document’s fingerprint"
            />
          </div>
          <Lifecycle
            scenario={
              <>
                Last week an associate uploaded <strong>deck_v3.pdf</strong> to the data room.
                Tonight María’s email arrives carrying the same file as an attachment — different
                route, different filename casing, same bytes.
              </>
            }
            stages={[
              {
                t: "Fingerprint",
                d: <>The attachment is ingested like any document: <code>sha256(content)</code> becomes its <code>canonical_key</code> — <code>doc:4b4999…</code>. Identity comes from the bytes, not the filename.</>,
              },
              {
                t: "Collide",
                d: <>That hash already exists — the unique index hits last week’s upload, and <code>check_duplicates()</code> returns <code>exact_canonical</code> at 100%.</>,
              },
              {
                t: "Merge",
                d: <>The copy merges into the existing document: <code>chunks_inserted: 0</code>, nothing stored twice, nothing re-embedded.</>,
              },
              {
                t: "Link",
                d: <>The email simply links to the pointer its attachment resolved to. No similarity score was ever involved — zero false positives by construction.</>,
              },
              {
                t: "Discovery",
                d: <>The data-room upload and the email thread are now connected <strong>through the one document</strong> — a link nobody declared and nobody had to notice.</>,
              },
            ]}
            op={`POST /functions/v1/ingest-document        // the attachment, as-is
{ "title": "deck_v3.pdf", "content": "..." }

-> { "status": "merged",                   // recognized by fingerprint
     "canonical_key": "doc:4b4999…",
     "chunks_inserted": 0 }                // nothing stored twice
-- the email then links to that resolved pointer_id`}
          />
          <Tech
            steps={[
              <>
                <strong>Fingerprint on arrival</strong>: the ingest function computes{" "}
                <code>sha256(content)</code> and stores it as the document’s{" "}
                <code>canonical_key</code> — <code>doc:4b4999…</code>. Identity comes from the
                bytes, not the filename.
              </>,
              <>
                <strong>The unique index does the discovery</strong>: when the second copy arrives,
                its hash hits the existing key, the dedup engine returns{" "}
                <code>exact_canonical</code> at 100%, and the copy merges — chunks are skipped
                (<code>chunks_inserted: 0</code>), exactly what you saw when re-sending the memo.
              </>,
              <>
                <strong>The link requires no inference</strong>: the email simply links to whatever
                pointer its attachment resolved to. No similarity score is involved — zero false
                positives by construction.
              </>,
              <>
                <strong>Deliberate limit</strong>: only byte-identical files converge. Deck v2 is a
                different document on purpose — connecting versions (<code>version_of</code> via
                embedding similarity between document vectors) is the designed extension, kept
                human-reviewed because “almost the same file” is a judgment call.
              </>,
            ]}
            code={`const canonicalKey = \`doc:\${sha256(content)}\`;   // in the Edge Function

-- pointers.canonical_key has a partial unique index:
--   second copy -> check_duplicates() -> 'exact_canonical' @ 1.0 -> merged
--   email then links to the resolved pointer_id it already had`}
          />
        </Reveal>

        <Reveal delay={240} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">4</span>
            <h3>Strengthened — your team’s behavior draws its own links</h3>
          </div>
          <p>
            The three mechanisms above write <strong>global, factual</strong> links. The fourth kind
            is private to each team: when people — or agents — keep visiting the same things
            together, the system records it as a weighted connection that no document ever declared:
          </p>
          <div className="xp-edges">
            <EdgeExample
              from="Acme Corp"
              fromSub="company"
              rel="co_access · 6.5"
              to="EU AI Act"
              toSub="regulation"
              why="Visited together in 9 research sessions this month — your team’s pattern, invisible to other tenants"
            />
          </div>
          <Lifecycle
            scenario={
              <>
                For two weeks, three analysts working the <strong>Acme deal</strong> keep opening
                the same things in the same research sessions: Acme’s card, then the EU AI Act,
                then the deck. Nobody files anything — they’re just working.
              </>
            }
            stages={[
              {
                t: "Paths",
                d: <>Each session’s visited cards form a path. After 30 idle seconds it flushes to <code>query_paths</code> — with an <code>agent_id</code> when the visitor was an agent, not a person.</>,
              },
              {
                t: "Weights",
                d: <>Every pair in a path scores <code>1 / distance</code> — neighbors 1.0, two-apart 0.5 — accumulated per tenant into <code>tenant_coaccess</code>. (Acme, EU AI Act) climbs a little with every session.</>,
              },
              {
                t: "Threshold",
                d: <>Around the ninth session the pair crosses weight 2.0 — enough signal to be trusted as structure, not coincidence.</>,
              },
              {
                t: "Nightly",
                d: <>The night cycle runs Union-Find over all heavy pairs: the cluster becomes a branch, an LLM names it from its members, and Jaccard &gt; 0.3 maps it onto the existing tree — the forest evolves, it doesn’t reset.</>,
              },
              {
                t: "Morning",
                d: <>Acme and the EU AI Act now share a branch, joined by a <code>co_access · 6.5</code> edge whose why reads like a sentence — a link drawn purely from how your team works, invisible to every other tenant.</>,
              },
            ]}
            op={`path:  [acme, eu-ai-act, deck_v3]        // one session, flushed
pairs: (acme, eu-ai-act) +1.0  (acme, deck_v3) +0.5
       -> tenant_coaccess.weight  ...session after session...

nightly: weight >= 2.0 -> Union-Find -> branch
         -> LLM names it -> Jaccard > 0.3 keeps continuity`}
          />
          <Tech
            steps={[
              <>
                <strong>Paths, not clicks</strong>: every pointer you open joins the current
                session’s path; after 30 idle seconds the path is flushed to{" "}
                <code>query_paths</code> — with an <code>agent_id</code> when the visitor is an
                agent rather than a person.
              </>,
              <>
                <strong>Proximity becomes weight</strong>: each pair in a path scores{" "}
                <code>1 / distance</code> — neighbors get 1.0, two-apart 0.5 — accumulated per
                tenant into <code>tenant_coaccess</code>, incrementally via a cursor so nothing is
                recounted.
              </>,
              <>
                <strong>Nightly, structure</strong>: pairs above weight 2.0 feed Union-Find
                clustering — connected components become branches, branches merge greedily into at
                most 12 trees, and an LLM names each cluster from its members’ labels.
              </>,
              <>
                <strong>Evolution, not reset</strong>: new branches are matched to old ones by
                member overlap (Jaccard &gt; 0.3) so the forest visibly <em>evolves</em>; a
                guard skips the whole recompute when there’s too little new signal to trust.
              </>,
            ]}
            code={`path: [acme, eu-ai-act, deck_v3, maria]
pairs: (acme, eu-ai-act) +1.0   (acme, deck_v3) +0.5   ...
       -> tenant_coaccess.weight accumulates, per tenant

nightly: weight >= 2.0 -> Union-Find -> branches
         -> greedy merge to <= 12 trees -> LLM names clusters
         -> Jaccard > 0.3 maps old structure to new (no amnesia)`}
          />
        </Reveal>
      </div>

      <Reveal delay={220}>
        <div className="xp-anatomy">
          <span className="lab">Every link stores</span>
          <span className="field">source</span>
          <span className="field">target</span>
          <span className="field">relationship_type</span>
          <span className="field">why</span>
          <span className="field">weight</span>
          <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
            — and the weight grows as your team actually uses the connection.
          </span>
        </div>
      </Reveal>
    </section>
  );
}

/* ── Retrieval: the five methods, with exact mechanics ────────────── */

function RetrievalExample({ ask, get }) {
  return (
    <div className="xp-rexample">
      <span className="lab">Worked example</span>
      <div className="row">
        <span className="dir">The request</span>
        <span className="val">{ask}</span>
      </div>
      <div className="row">
        <span className="dir">The result</span>
        <span className="val">{get}</span>
      </div>
    </div>
  );
}

function RetrievalSection() {
  return (
    <section className="xp-section">
      <Reveal>
        <div className="xp-eyebrow accent-blue">Under the hood · Retrieval</div>
        <h2 className="xp-h2">How an answer is found</h2>
        <p className="xp-lead">
          Five retrieval methods operate on the same memory. They share one design rule:{" "}
          <strong>deterministic where possible, explainable where not</strong>. The fast paths are
          pure SQL — repeatable and free. The language model is used in exactly one place, and even
          there it must show its plan. Each card below has a drawer with the exact mechanics, taken
          from the deployed code.
        </p>
      </Reveal>

      <div className="xp-mechs">
        <Reveal delay={0} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">1</span>
            <h3>Instant search — as you type</h3>
          </div>
          <p>
            Every keystroke in the search bar queries the database directly. Two text matchers run
            inside Postgres and return ranked cards in milliseconds — <strong>no language model,
            no embedding call</strong>, and therefore no latency and no per-query cost.
          </p>
          <RetrievalExample
            ask={<>Typing <code>auro</code> — four letters, mid-word.</>}
            get={<><strong>Aurora Robotics</strong> · company, ranked first. Trigram matching lands the partial word before you finish typing, and the result arrives with its place in your team’s trees.</>}
          />
          <Lifecycle
            scenario={
              <>
                An analyst is <strong>on a live call</strong> — the founder just mentioned a
                comparable company. She needs Aurora’s card before the sentence ends, so she types
                <code>auro</code> into the search bar.
              </>
            }
            stages={[
              {
                t: "Keystroke",
                d: <>Every keystroke fires the query as typed — <code>a</code>, <code>au</code>, <code>aur</code>, <code>auro</code>. Responses that arrive after a newer keystroke are discarded client-side, so results never flicker backwards.</>,
              },
              {
                t: "Match",
                d: <>Inside Postgres, full-text search and trigram similarity run together over indexed columns — <code>auro</code> matches mid-word, a typo would too.</>,
              },
              {
                t: "Frame",
                d: <>Each hit comes back with its position in the team’s trees, so she sees not just <em>Aurora Robotics</em> but where it lives in the structure she already navigates.</>,
              },
              {
                t: "Render",
                d: <>Ranked cards in milliseconds. No model was called, no embedding computed — the marginal cost of her search is $0, however many times she does this today.</>,
              },
            ]}
            op={`supabase.rpc("search_hierarchy_aware", {
  p_query:       "auro",     // the text, exactly as typed
  p_tenant_id:   tenantId,   // framed in her team's trees
  p_embedding:   null,       // no model on the hot path
  p_type_filter: null,
  p_limit:       15,
})`}
          />
          <Tech
            steps={[
              <>
                <strong>One function call</strong>: the text, exactly as typed, goes to the{" "}
                <code>search_hierarchy_aware</code> function. The client discards any response that
                arrives after a newer keystroke, so results never flicker backwards.
              </>,
              <>
                <strong>Two matchers run together</strong>: full-text search (word-level matching
                with stemming, so “deployments” finds “deployment”) and trigram similarity
                (comparing three-character fragments — robust to typos and partial words).
              </>,
              <>
                <strong>Hierarchy-aware results</strong>: each match returns with its position in
                your team’s trees, so the result is framed in the structure you already navigate.
              </>,
              <>
                <strong>Deterministic by construction</strong>: pure SQL over indexed columns. The
                same text always returns the same cards, and the marginal cost of a query is zero.
              </>,
            ]}
            code={`supabase.rpc("search_hierarchy_aware", {
  p_query:       "aurora",   // the text, exactly as typed
  p_tenant_id:   tenantId,   // results framed in your team's trees
  p_embedding:   null,       // no model call on the hot path
  p_type_filter: null,
  p_limit:       15,
})`}
          />
        </Reveal>

        <Reveal delay={90} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">2</span>
            <h3>Filtered search — the contract</h3>
          </div>
          <p>
            Dashboards, scheduled reports and automations call <code>search_pointers</code> — a
            fixed contract of filters with a guaranteed ordering. The same request returns the{" "}
            <strong>same answer, byte for byte</strong>, which is what makes the output safe to
            build reports on.
          </p>
          <RetrievalExample
            ask={<>A weekly report calls: type <code>company</code> · attribute <code>Stage = "Series A"</code> · this quarter’s date window.</>}
            get={<>The same ordered list on every run — <strong>Aurora Robotics</strong> first, then its peers by relevance and date. Run it twice: byte-identical, until the data itself changes.</>}
          />
          <Lifecycle
            scenario={
              <>
                Every <strong>Monday at 08:00</strong> a scheduled job builds the Series A pipeline
                review that lands in the partners’ inboxes. No human types anything — the job has
                been sending the identical request for months.
              </>
            }
            stages={[
              {
                t: "Trigger",
                d: <>The cron fires and assembles its fixed request: type <code>company</code>, attribute <code>Stage = "Series A"</code>, this quarter’s date window.</>,
              },
              {
                t: "Narrow",
                d: <>Structured filters cut the candidate set first — wrong types, wrong stages and out-of-window rows never reach scoring.</>,
              },
              {
                t: "Rank",
                d: <>What remains is scored three ways and summed — words (<code>ts_rank</code>), spelling (trigram), meaning (cosine). Terms not in play contribute exactly zero.</>,
              },
              {
                t: "Order",
                d: <>Relevance, then event date, then id — a total ordering with no possible ties, so page 2 next Monday starts exactly where page 1 ended.</>,
              },
              {
                t: "Deliver",
                d: <>The JSON is <strong>byte-identical</strong> to last week’s unless the data itself changed — which is precisely what lets the report diff “what’s new this week” with confidence.</>,
              },
            ]}
            op={`supabase.rpc("search_pointers", {
  p_types:        ["company"],
  p_attr_filters: { "Stage": "Series A" },
  p_date_from:    "2026-04-01",
  p_date_to:      "2026-06-30",
  p_limit:        100,
})   // same request -> same bytes, every run`}
          />
          <Tech
            steps={[
              <>
                <strong>Structured filters narrow first</strong>: entity type (companies only,
                documents only), a date window (using the event date, falling back to creation
                date), and exact attribute matches (for example, <code>Stage = "Series A"</code>).
              </>,
              <>
                <strong>Relevance is scored three ways and summed</strong>: full-text rank
                (<code>ts_rank</code> — how well the words match), trigram similarity on the label
                (how close the spelling is), and, when an embedding is supplied, cosine similarity
                (how close the meaning is). Any term not in play contributes zero.
              </>,
              <>
                <strong>Ordering is total and deterministic</strong>: relevance, then event date,
                then id as the final tie-break. Because no two rows can ever tie completely,
                pagination is stable and every run of the same request is reproducible.
              </>,
              <>
                <strong>Bounded by design</strong>: page size is clamped to 1–100 and the response
                always reports the total match count, so callers can page through results without
                surprises.
              </>,
            ]}
            code={`-- the actual relevance score inside search_pointers()
COALESCE(ts_rank(p.search_text, v_tsquery), 0)        -- words match
  + COALESCE(similarity(p.label, p_query_text), 0)    -- spelling is close
  + COALESCE(1 - (p.embedding <=> p_embedding), 0)    -- meaning is close

ORDER BY rank DESC NULLS LAST, event_time DESC, id
-- total ordering: same request -> same answer, every time`}
          />
        </Reveal>

        <Reveal delay={180} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">3</span>
            <h3>Semantic search — by meaning, not words</h3>
          </div>
          <p>
            An embedding is a list of 1,536 numbers that places a piece of text in a space where{" "}
            <strong>distance means difference in meaning</strong>. “Warehouse automation” and
            “logistics robots” share almost no words — but their embeddings sit close together, so
            a search for one finds the other.
          </p>
          <RetrievalExample
            ask={<>Searching <code>logistics robots</code>.</>}
            get={<><strong>Aurora Robotics</strong> — its memo says “autonomous warehouse robots”. Not one word in common with the query, but the embeddings sit close, so it ranks on top.</>}
          />
          <Lifecycle
            scenario={
              <>
                A partner heard a pitch yesterday about <strong>“logistics robots”</strong> and
                wants to know if the firm has seen anything similar. He searches that exact
                phrase — which appears in no card, no memo, no email anywhere in memory.
              </>
            }
            stages={[
              {
                t: "Embed",
                d: <>The query text is embedded once — 1,536 numbers placing “logistics robots” in meaning-space. This is the only model cost of the whole search.</>,
              },
              {
                t: "Neighbor",
                d: <>The pgvector HNSW index walks straight to the nearest stored vectors — no row scan. Every card and chunk vector was already written at ingest, so nothing else is computed now.</>,
              },
              {
                t: "Score",
                d: <><code>1 - (embedding &lt;=&gt; query)</code> turns distance into a similarity score and merges it into the ranking alongside any text terms in play.</>,
              },
              {
                t: "Land",
                d: <>Aurora’s memo chunk — <em>“autonomous warehouse robots for mid-size logistics operators”</em> — sits close in meaning-space and surfaces first. Zero words in common with the query; the partner finds the company anyway.</>,
              },
            ]}
            op={`supabase.rpc("search_pointers", {
  p_query_text: "logistics robots",
  p_embedding:  embed("logistics robots"),  // 1,536-dim, one call
})
-- inside: 1 - (p.embedding <=> p_embedding) joins the rank;
-- card + chunk vectors were written at ingest, reused here`}
          />
          <Tech
            steps={[
              <>
                <strong>Embedded at write time, not query time</strong>: every card label and every
                document chunk gets its vector (text-embedding-3-small) the moment it is ingested.
                Queries only pay for one small embedding — their own.
              </>,
              <>
                <strong>Indexed for speed</strong>: vectors live in Postgres under a pgvector HNSW
                index — a graph structure that finds the nearest neighbors of a query vector
                without scanning every row, keeping semantic lookup as fast as a key lookup.
              </>,
              <>
                <strong>Scored by cosine similarity</strong>:{" "}
                <code>1 - (embedding &lt;=&gt; query)</code>, where <code>&lt;=&gt;</code> is the
                cosine-distance operator, computed inside the index, and a score of 1.0 means
                identical meaning.
              </>,
              <>
                <strong>Three places it applies</strong>: as the optional meaning term in{" "}
                <code>search_pointers</code>; inside the dedup engine, where it catches synonyms
                that spelling-based matching misses; and in the agent’s deep search, where the
                question itself is embedded.
              </>,
            ]}
            code={`-- meaning similarity, computed inside the HNSW index
1 - (p.embedding <=> :query_embedding)   -- 1.0 = same meaning

-- written once at ingest, reused on every query:
--   pointers.embedding         (one per card)
--   document_chunks.embedding  (one per paragraph-level chunk)`}
          />
        </Reveal>

        <Reveal delay={240} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">4</span>
            <h3>Agent search — a plan, then the contract</h3>
          </div>
          <p>
            A question in plain language goes to the <code>query-knowledge</code> function. The
            agent does not browse the memory freely — it <strong>compiles the question into the
            same filtered search</strong> a system would send, and returns its plan alongside the
            answer so the reasoning is auditable.
          </p>
          <RetrievalExample
            ask={<>Asking <code>Which companies are in cybersecurity?</code> — plain language, no filters.</>}
            get={<>The plan it compiled (<code>{`{ types: ["company"], text: "cybersecurity" }`}</code>), the matching cards with their attributes, and a composed answer naming each company — with the cards it drew from cited.</>}
          />
          <Lifecycle
            scenario={
              <>
                An associate preparing for Monday’s pipeline meeting asks the assistant{" "}
                <strong>“Which companies are in cybersecurity?”</strong> — plain language, no
                filters, no knowledge of the schema. She needs an answer she can repeat in the
                meeting and defend if questioned.
              </>
            }
            stages={[
              {
                t: "Ask",
                d: <>Her words go to <code>POST /functions/v1/query-knowledge</code> — nothing else. No filters, no types, no SQL.</>,
              },
              {
                t: "Plan",
                d: <>One model call compiles the question into the same filtered-search contract a system would send — <code>{`{ types: ["company"], text: "cybersecurity" }`}</code>. The plan is kept, not discarded.</>,
              },
              {
                t: "Execute",
                d: <>The plan runs against three layers of memory: card labels (text and meaning), attributes (exact facts), and document chunks (paragraph-level content).</>,
              },
              {
                t: "Traverse",
                d: <>From the matched cards, edges pull connected context — sectors, people, memos — each hop carrying its stored <code>why</code>.</>,
              },
              {
                t: "Compose",
                d: <>A second model call writes the answer strictly from the retrieved results, citing the cards it used. If memory doesn’t contain it, the answer says so — it never invents.</>,
              },
              {
                t: "Audit",
                d: <>The response carries <code>plan</code>, <code>results</code> and <code>answer</code> side by side. When a partner asks “where did that come from?”, she can show exactly how the question was interpreted — total cost ≈ $0.0004.</>,
              },
            ]}
            op={`POST /functions/v1/query-knowledge
{ "query": "Which companies are in cybersecurity?",
  "mode": "answer" }

-> { "plan": {...},      // how it read the question
     "results": [...],   // the cards it found
     "answer": "...",    // composed only from those
     "result_count": 3 }`}
          />
          <Tech
            steps={[
              <>
                <strong>Plan</strong>: a language model parses the question into a structured
                plan — which entity types, which filters, which search text. The plan is returned
                in the response, so you can always see how the question was interpreted.
              </>,
              <>
                <strong>Execute</strong>: the plan runs against three layers of the memory — card
                labels (text and meaning), attributes (exact facts like revenue or stage), and
                document chunks (paragraph-level content).
              </>,
              <>
                <strong>Traverse</strong>: from the matched cards, the agent follows edges to pull
                connected context — the company a memo describes, the people behind a company —
                each hop carrying its stored <code>why</code>.
              </>,
              <>
                <strong>Compose</strong>: a second model call writes the answer strictly from the
                retrieved results, citing the cards it used. The model never answers from its own
                knowledge — if the memory doesn’t contain it, the answer says so.
              </>,
              <>
                <strong>Cost envelope</strong>: one query embedding plus two small model calls —
                about $0.0004 per question.
              </>,
            ]}
            code={`POST /functions/v1/query-knowledge
{ "query": "Which companies are in cybersecurity?", "mode": "answer" }

-> {
  "plan":    { "steps": [...] },  // how the question was interpreted
  "results": [...],               // the cards, with their attributes
  "answer":  "...",               // composed only from those results
  "result_count": 3
}`}
          />
        </Reveal>

        <Reveal delay={300} className="xp-mech">
          <div className="xp-mech-head">
            <span className="mech-num">5</span>
            <h3>Graph &amp; chunk retrieval — finishing the answer</h3>
          </div>
          <p>
            Retrieval rarely ends at the matched card. Two final mechanisms complete an answer:
            following threads to <strong>connected context</strong>, and descending into documents
            to return <strong>the exact paragraph</strong> rather than “see the PDF”.
          </p>
          <RetrievalExample
            ask={<>Asking <code>What revenue did Aurora report?</code></>}
            get={<>The exact Financials paragraph from the overview memo — <strong>“Revenue reached $2M with a pipeline of 14 pilot deployments…”</strong> — plus the thread that connects it: memo → <em>describes</em> → Aurora Robotics.</>}
          />
          <Lifecycle
            scenario={
              <>
                During diligence someone asks <strong>“What revenue did Aurora report?”</strong>.
                The answer exists nowhere as a card or attribute — it lives in one paragraph of a
                ten-page memo that nobody wants to reopen and skim.
              </>
            }
            stages={[
              {
                t: "Match",
                d: <>The question’s embedding lands on the memo’s <em>Financials</em> chunk — chunks carry their own vectors, so the hit is the paragraph itself, not the whole document.</>,
              },
              {
                t: "Ascend",
                d: <>The chunk’s parent pointer identifies the full memo — both granularities were written by the same ingestion, so paragraph and document are never out of sync.</>,
              },
              {
                t: "Traverse",
                d: <>One indexed read of <code>edges</code> follows memo → <em>describes</em> → Aurora Robotics, the stored <code>why</code> riding along — no inference, just a lookup.</>,
              },
              {
                t: "Return",
                d: <>The answer is the exact paragraph — <em>“Revenue reached $2M with a pipeline of 14 pilot deployments…”</em> — grounded by the thread that ties it to Aurora. Not “see the PDF”.</>,
              },
            ]}
            op={`-- the chunk that answers, then its surroundings: two reads
SELECT heading, content FROM document_chunks
ORDER BY embedding <=> :question_embedding LIMIT 3;

SELECT e.relationship_type, e.why, p.label
FROM edges e JOIN pointers p ON p.id = e.target_id
WHERE e.source_id = :memo_id;   -- describes -> Aurora Robotics`}
          />
          <Tech
            steps={[
              <>
                <strong>Neighbors are one indexed lookup away</strong>: edges are stored by source
                and target, each with its <code>relationship_type</code>, <code>why</code> and{" "}
                <code>weight</code> — so expanding a card into its surroundings requires no
                inference, only a read.
              </>,
              <>
                <strong>Documents are split at paragraph boundaries</strong>, with section headings
                preserved on each chunk. Chunks never overlap, so concatenating them by sequence
                reconstructs the original document exactly.
              </>,
              <>
                <strong>Each chunk carries its own embedding</strong>: a question matches the
                specific paragraph that answers it, and the chunk’s parent pointer links back to
                the full document — both granularities from one ingestion.
              </>,
            ]}
            code={`-- everything connected to a card: one read, no inference
SELECT e.relationship_type, e.why, e.weight, p.label, p.type
FROM edges e JOIN pointers p ON p.id = e.target_id
WHERE e.source_id = :card_id;

-- chunk rows, written once at ingest:
--   (pointer_id, sequence, heading, content, embedding)
--   concatenate by sequence -> the original document, exactly`}
          />
        </Reveal>
      </div>
    </section>
  );
}

/* ── Duplicates: slider + real dedup engine ───────────────────────── */
function DupeSlider({ onWrite }) {
  const [sim, setSim] = useState(91);
  const [challenge, setChallenge] = useState("typo");
  const typo = useLive(dupeTypo, onWrite);
  const lookalike = useLive(dupeLookalike, onWrite);

  const zone =
    sim >= 80
      ? {
          cls: "merge",
          title: "Same thing — merged automatically",
          desc: "The new facts update the existing card. Nothing is duplicated, nothing is lost.",
        }
      : sim >= 40
      ? {
          cls: "review",
          title: "Maybe — a human decides",
          desc: "Both cards are kept and flagged side by side for review. Your team confirms or separates them in one click.",
        }
      : {
          cls: "create",
          title: "Different — a new card is created",
          desc: "Low resemblance means a genuinely new entity. It gets its own card, cleanly.",
        };

  const loading = typo.loading || lookalike.loading;
  const lastResult = lookalike.result || typo.result;
  const lastError = lookalike.error || typo.error;
  const lastWasLookalike = !!lookalike.result;
  const dupe = lastResult?.duplicates?.[0];

  return (
    <div className="xp-stage">
      <div className="xp-dupe">
        <div className="xp-dupe-cards">
          <div className="xp-dupe-chip">
            Acme Corp
            <span className="sub">already in memory</span>
          </div>
          <span className="xp-dupe-vs">VS</span>
          <div className="xp-dupe-chip">
            “Acme Corporation”
            <span className="sub">just arrived</span>
          </div>
        </div>

        <div className="xp-dupe-sliderwrap">
          <input
            type="range"
            min="0"
            max="100"
            value={sim}
            onChange={(e) => setSim(Number(e.target.value))}
            aria-label="Resemblance between the two names"
          />
          <div className="xp-dupe-scale">
            <span>0% · nothing alike</span>
            <span>drag me</span>
            <span>100% · identical</span>
          </div>
        </div>

        <div className={`xp-dupe-outcome ${zone.cls}`}>
          <div className="pct">{sim}% alike</div>
          <div className="title">{zone.title}</div>
          <div className="desc">{zone.desc}</div>
        </div>

        <div className="xp-passport">
          <span className="badge"><Icon d={ICONS.id} /></span>
          <span>
            <strong>The passport rule.</strong> If two cards carry different official IDs — a
            document’s fingerprint, a company’s domain — they are <strong>never merged
            automatically</strong>, no matter how similar their names look. They go to human review
            instead.
          </span>
        </div>

        <div className="xp-live">
          <div className="xp-live-head"><span className="xp-live-dot" /> Live — challenge the real dedup engine</div>
          <div className="xp-live-actions">
            <button
              className="xp-livebtn go"
              disabled={loading}
              onClick={() => { setChallenge("typo"); typo.run(); }}
            >
              {typo.loading && <span className="xp-spin" />}Send a typo: “Aurora Robotiks”
            </button>
            <button
              className="xp-livebtn"
              disabled={loading}
              onClick={() => { setChallenge("lookalike"); lookalike.run(); }}
            >
              {lookalike.loading && <span className="xp-spin" />}Send a lookalike with its own ID
            </button>
          </div>

          <RequestPreview
            req={challenge === "typo" ? DEMO_REQUESTS.dupeTypo : DEMO_REQUESTS.dupeLookalike}
            label={challenge === "typo" ? "What the typo button actually sends" : "What the lookalike button actually sends"}
            note={
              challenge === "typo"
                ? "No canonical_key, misspelled name — the engine has only resemblance to go on."
                : "Nearly the same name, but its own canonical_key — watch the passport rule intervene."
            }
          />

          {lastError && <LiveError error={lastError} />}
          {!lastError && lastResult && (
            <div className="xp-live-result">
              <div className="xp-chips">
                <StatusChip status={lastResult.status} />
                {dupe && (
                  <span style={{ fontSize: 12, color: "#9aa3b5" }}>
                    {pct(dupe.similarity)} alike · method <span style={{ color: "#c0c7d6" }}>{dupe.match_method}</span>
                  </span>
                )}
              </div>
              <ul className="xp-facts">
                {lastResult.status === "merged" && dupe && (
                  <li>
                    The engine measured <strong>{pct(dupe.similarity)}</strong> resemblance to{" "}
                    <strong>{dupe.label}</strong> and merged them — the typo never became a second card.
                  </li>
                )}
                {lastResult.status === "pending_review" && dupe && (
                  <li>
                    <strong>{pct(dupe.similarity)}</strong> alike — high enough to merge, <strong>but it carries its
                    own ID</strong>, so the passport rule parked it for human review instead.
                  </li>
                )}
                {lastResult.status === "created" && (
                  <li>No close match in memory{lastWasLookalike ? "" : " yet"} — a clean new card was created. (Run the CRM example above first to see a merge.)</li>
                )}
                {lastResult.status === "merged" && !dupe && <li>Recognized and merged into the existing card.</li>}
              </ul>
              <RawJson data={lastResult} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Two doors: real agent + real deterministic search ────────────── */

const SEARCH_TYPES = ["company", "person", "sector", "geography", "regulation", "document", "any"];

function formatEventDate(iso) {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return null;
  }
}

function TwoDoorsLive() {
  const [question, setQuestion] = useState("Which companies are in cybersecurity?");
  const [searchText, setSearchText] = useState("security");
  const [searchType, setSearchType] = useState("company");
  const [prevRun, setPrevRun] = useState(null); // { key, json } of the previous run
  const [identical, setIdentical] = useState(false);
  const ask = useLive(askKnowledge);
  const search = useLive(runSearch);

  const runSystemSearch = async () => {
    const res = await search.run({ type: searchType, queryText: searchText });
    if (!res) return;
    const key = JSON.stringify(res.params);
    const json = JSON.stringify(res.data);
    setIdentical(prevRun !== null && prevRun.key === key && prevRun.json === json);
    setPrevRun({ key, json });
  };

  return (
    <div className="xp-doors">
      <Reveal delay={0} className="xp-door">
        <h3><span className="door-icon"><Icon d={ICONS.chat} /></span>Ask like a person</h3>
        <p>
          An assistant translates your question into a precise lookup, searches by meaning as well
          as by words, and explains where each answer came from.
        </p>
        <div className="xp-live" style={{ marginTop: 0 }}>
          <div className="xp-live-head"><span className="xp-live-dot" /> Live — the real agent answers</div>
          <div className="xp-live-actions">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !ask.loading && ask.run(question)}
              placeholder="Ask anything about the knowledge graph…"
            />
            <button className="xp-livebtn go" disabled={ask.loading || !question.trim()} onClick={() => ask.run(question)}>
              {ask.loading && <span className="xp-spin" />}Ask
            </button>
          </div>
          <RequestPreview
            req={DEMO_REQUESTS.ask(question.trim() || "…")}
            label="What pressing Ask actually sends"
            note="Just your words — the agent turns them into the same kind of filtered query the system door sends, and shows you its plan."
          />
          {ask.loading && (
            <div className="xp-live-result" style={{ fontSize: 12.5, color: "#9aa3b5" }}>
              Planning the lookup · searching cards, attributes and chunks · composing the answer…
            </div>
          )}
          {ask.error && <LiveError error={ask.error} />}
          {!ask.error && ask.result && (
            <div className="xp-live-result">
              <div className="xp-chips">
                <span className="xp-chip merged">{ask.result.result_count} results</span>
                <span style={{ fontSize: 12, color: "#9aa3b5" }}>
                  plan: {ask.result.plan?.steps?.map((s) => s.action).join(" → ") || "search"}
                </span>
              </div>
              {ask.result.answer && <div className="answer">{ask.result.answer}</div>}
              <RawJson data={ask.result} />
            </div>
          )}
        </div>
      </Reveal>

      <Reveal delay={120} className="xp-door">
        <h3><span className="door-icon"><Icon d={ICONS.sliders} /></span>Ask like a system</h3>
        <p>
          Dashboards, weekly reports and automations don’t phrase questions — they fill a{" "}
          <strong>form with filters</strong> and call <code className="xp-inlinecode">search_pointers</code>.
          Same form, same answer, every single time.
        </p>
        <div className="xp-live" style={{ marginTop: 0 }}>
          <div className="xp-live-head"><span className="xp-live-dot" /> Live — fill the form, call the contract</div>

          <div className="xp-form">
            <label className="xp-formfield">
              <span className="lab">What kind of thing</span>
              <select value={searchType} onChange={(e) => setSearchType(e.target.value)}>
                {SEARCH_TYPES.map((t) => (
                  <option key={t} value={t}>{t === "any" ? "any type" : t}</option>
                ))}
              </select>
            </label>
            <label className="xp-formfield grow">
              <span className="lab">Words to match (optional — empty = newest first)</span>
              <input
                type="text"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !search.loading && runSystemSearch()}
                placeholder="e.g. security, payments, Madrid…"
              />
            </label>
            <button className="xp-livebtn go" disabled={search.loading} onClick={runSystemSearch}>
              {search.loading && <span className="xp-spin" />}Run
            </button>
          </div>

          <div className="xp-reqpreview">
            <span className="lab">The exact request being sent</span>
            <pre style={{ marginTop: 6 }}>{`search_pointers(
  p_types:      ${searchType === "any" ? "null  — every kind" : `["${searchType}"]`},
  p_query_text: ${searchText.trim() ? `"${searchText.trim()}"` : "null  — no text filter"},
  p_limit:      5
)`}</pre>
          </div>

          {search.error && <LiveError error={search.error} />}
          {!search.error && search.result && (
            <div className="xp-live-result">
              <div className="xp-chips">
                <span className="xp-chip created">{search.result.data.total} matches</span>
                <span style={{ fontSize: 12, color: "#9aa3b5" }}>
                  showing {search.result.data.results?.length ?? 0} · ordered by relevance, then date, then id
                </span>
                {identical && <span className="xp-chip merged">✓ identical to previous run</span>}
              </div>
              <div className="xp-resultrows">
                {(search.result.data.results || []).map((p, i) => (
                  <div key={p.id} className="xp-resultrow rich">
                    <div className="rowtop">
                      <span className="name">
                        <span className="rankn">#{i + 1}</span> {p.label}
                      </span>
                      <span className="meta">
                        {p.rank != null && <>relevance {Math.round(p.rank * 100) / 100} · </>}
                        {formatEventDate(p.event_time)}
                      </span>
                    </div>
                    <div className="rowattrs">
                      <span className="typechip">{p.type}</span>
                      {(p.attributes || []).slice(0, 4).map((a) => (
                        <span key={a.key} className="attrchip">
                          {a.key}: {typeof a.value === "string" ? a.value : JSON.stringify(a.value)}
                        </span>
                      ))}
                      <span className="idchip">id {shortId(p.id)}</span>
                    </div>
                  </div>
                ))}
              </div>
              <p className="xp-livehint">
                Press <strong>Run</strong> again without changing the form — the system proves the
                answer is repeatable. Change a filter and the request (and only then the answer)
                changes.
              </p>
              <RawJson data={search.result.data} />
            </div>
          )}
        </div>
      </Reveal>
    </div>
  );
}

/* ── Cost estimation ──────────────────────────────────────────────── */

function CostSection() {
  return (
    <section className="xp-section">
      <Reveal>
        <div className="xp-eyebrow accent-green">Running costs</div>
        <h2 className="xp-h2">What this costs to run</h2>
        <p className="xp-lead">
          The whole system runs on a <strong>flat Supabase plan</strong> plus pay-per-use AI calls.
          The AI part is nearly free because the heavy lifting — search, deduplication, clustering —
          happens inside the database, not inside a language model.
        </p>
      </Reveal>

      <div className="xp-cost-grid">
        <Reveal delay={0} className="xp-cost">
          <span className="scenario">Today · this PoC</span>
          <div className="price">$0<small>/month</small></div>
          <div className="pricesub">Supabase Free plan + pennies of OpenAI</div>
          <ul>
            <li><span>Function calls (500K included)</span><span className="amt">&lt;1% used</span></li>
            <li><span>Database (500 MB included)</span><span className="amt">~20 MB</span></li>
            <li><span>File storage (1 GB included)</span><span className="amt">0 GB</span></li>
            <li><span>Everything you clicked today</span><span className="amt">≈ $0.01</span></li>
          </ul>
        </Reveal>

        <Reveal delay={90} className="xp-cost featured">
          <span className="scenario">Team rollout · daily use</span>
          <div className="price">≈ $30<small>/month</small></div>
          <div className="pricesub">Supabase Pro $25 + ≈ $5 of OpenAI</div>
          <ul>
            <li><span>1,000 emails ingested nightly</span><span className="amt">≈ $0.30/mo</span></li>
            <li><span>50 documents per week</span><span className="amt">≈ $0.06/mo</span></li>
            <li><span>200 agent questions per day</span><span className="amt">≈ $2.40/mo</span></li>
            <li><span>Function calls (2M included)</span><span className="amt">~3% used</span></li>
            <li><span>Database (8 GB included)</span><span className="amt">~2 GB</span></li>
            <li><span>Files (100 GB included)</span><span className="amt">~10 GB</span></li>
          </ul>
        </Reveal>

        <Reveal delay={180} className="xp-cost">
          <span className="scenario">Scale · 10 tenants</span>
          <div className="price">≈ $80<small>/month</small></div>
          <div className="pricesub">Pro plan + disk overage + ≈ $45 OpenAI</div>
          <ul>
            <li><span>10,000 emails nightly</span><span className="amt">≈ $3/mo</span></li>
            <li><span>2,000 agent questions per day</span><span className="amt">≈ $24/mo</span></li>
            <li><span>Database ~12 GB (+$0.125/GB over 8)</span><span className="amt">+$0.50</span></li>
            <li><span>Files ~50 GB</span><span className="amt">included</span></li>
            <li><span>Function calls</span><span className="amt">~20% used</span></li>
          </ul>
        </Reveal>
      </div>

      <Reveal delay={220}>
        <div className="xp-unittable">
          <div className="ut-head">
            <span>One action</span>
            <span>What actually runs</span>
            <span style={{ textAlign: "right" }}>Cost</span>
          </div>
          <div className="ut-row">
            <span className="act">Add a company card</span>
            <span className="how">1 function call + a tiny embedding (~20 tokens)</span>
            <span className="amt">≈ $0.000001</span>
          </div>
          <div className="ut-row">
            <span className="act">Ingest a 10-page deck</span>
            <span className="how">1 call + embeddings for the document and every chunk (~14K tokens)</span>
            <span className="amt">≈ $0.0003</span>
          </div>
          <div className="ut-row">
            <span className="act">A night of 1,000 emails</span>
            <span className="how">20 batch calls + ~400K embedding tokens</span>
            <span className="amt">≈ $0.01</span>
          </div>
          <div className="ut-row">
            <span className="act">One agent question</span>
            <span className="how">1 embedding + 2 small LLM calls (plan + answer)</span>
            <span className="amt">≈ $0.0004</span>
          </div>
          <div className="ut-row">
            <span className="act">Nightly forest regrow</span>
            <span className="how">1 call + LLM naming of new branches</span>
            <span className="amt">≈ $0.0005</span>
          </div>
          <div className="ut-row">
            <span className="act">A precise search</span>
            <span className="how">Pure SQL inside the database — no AI involved</span>
            <span className="amt free">$0</span>
          </div>
        </div>
      </Reveal>

      <Reveal delay={260}>
        <p className="xp-cost-note">
          <strong>Where the numbers come from:</strong> Supabase pricing as published June 2026 —
          Pro $25/mo includes 2M function calls (then $2/M), 8 GB database (then $0.125/GB), 100 GB
          file storage (then $0.0213/GB). OpenAI rates for the deployed models:
          text-embedding-3-small at $0.02 per 1M tokens, gpt-4o-mini at $0.15/$0.60 per 1M tokens
          in/out. Estimates rounded up.
        </p>
      </Reveal>
    </section>
  );
}

/* ── Cleanup pill ─────────────────────────────────────────────────── */
function CleanupPill({ visible, onCleaned }) {
  const reset = useLive(resetDemo);
  const [done, setDone] = useState(null);

  if (!visible && done === null) return null;

  return (
    <button
      className="xp-cleanup"
      disabled={reset.loading}
      onClick={async () => {
        const r = await reset.run();
        if (r) {
          setDone(r.pointers_deleted);
          onCleaned?.();
          setTimeout(() => setDone(null), 4000);
        }
      }}
    >
      {reset.loading ? <span className="xp-spin" /> : <Icon d={ICONS.trash} />}
      {done !== null ? `Demo data removed` : "Clean up demo data"}
      {done !== null && <span className="count">{done} cards</span>}
    </button>
  );
}

/* ── Page ─────────────────────────────────────────────────────────── */
export default function ExplainerPage({ onEnterForest, onRunDemo }) {
  const [dirty, setDirty] = useState(false);
  const markDirty = () => setDirty(true);

  return (
    <div className="xp-root">
      <header className="xp-topbar">
        <div className="brand">
          <span className="logomark">K</span>
          Memory Layer
        </div>
        <nav>
          <button className="xp-btn ghost" style={{ padding: "9px 18px", fontSize: 13 }} onClick={onRunDemo}>
            Watch it grow
          </button>
        </nav>
      </header>

      {/* HERO */}
      <section className="xp-hero">
        <Reveal>
          <div className="xp-eyebrow">A proposal for the firm’s memory layer</div>
          <h1>
            One memory.
            <br />
            <em>Everything connected.</em>
          </h1>
          <p className="xp-lead">
            Every company, person, deck and email your team touches — remembered{" "}
            <strong>once</strong>, connected with a <strong>reason</strong>, and organized around
            how you actually work. Every example below runs against the <strong>live system</strong>.
          </p>
          <div className="xp-cta-row">
            <a className="xp-btn ghost" href="#inspiration" style={{ textDecoration: "none", display: "inline-block" }}>
              How it works ↓
            </a>
          </div>
        </Reveal>
        <Reveal delay={150}>
          <HeroGraph />
        </Reveal>
      </section>

      {/* INTRODUCTION: WHERE THIS COMES FROM */}
      <InspirationSection />

      {/* BUILDING BLOCKS */}
      <section className="xp-section" id="blocks">
        <Reveal>
          <div className="xp-eyebrow">The whole idea, in three pieces</div>
          <h2 className="xp-h2">Cards, threads, and trees</h2>
          <p className="xp-lead">
            Underneath everything there is just one simple structure. If you understand these three
            pieces, you understand the entire system.
          </p>
        </Reveal>
        <div className="xp-blocks">
          <Reveal delay={0} className="xp-block">
            <div className="xp-block-icon green"><Icon d={ICONS.card} /></div>
            <h3>One card per real thing</h3>
            <p>
              Acme Corp gets exactly <strong>one card</strong> — no matter how many decks, emails or
              notes mention it. The card carries its facts: revenue, stage, headquarters.
            </p>
          </Reveal>
          <Reveal delay={100} className="xp-block">
            <div className="xp-block-icon violet"><Icon d={ICONS.thread} /></div>
            <h3>Every link keeps its why</h3>
            <p>
              Cards connect with threads that <strong>remember the reason</strong>: “María is the
              CEO”, “this deck describes Acme”, “these emails are about the deal”.
            </p>
          </Reveal>
          <Reveal delay={200} className="xp-block">
            <div className="xp-block-icon blue"><Icon d={ICONS.tree} /></div>
            <h3>Shelves that arrange themselves</h3>
            <p>
              There is no fixed folder tree. The more your team navigates, the more the forest{" "}
              <strong>reorganizes around how you think</strong> — different teams, different trees,
              same memory.
            </p>
          </Reveal>
        </div>
      </section>

      {/* USE CASE: CRM */}
      <section className="xp-section">
        <div className="xp-usecase">
          <Reveal>
            <div className="xp-eyebrow accent-green">Use case · CRM</div>
            <h2 className="xp-h2">Update, never duplicate</h2>
            <p className="xp-lead">
              When new information arrives about a company you already know, the system recognizes
              it and <strong>updates the card</strong>. It never creates a second “Aurora”. Press
              the two buttons in order and watch the real engine respond.
            </p>
            <ul className="xp-points">
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>Always the same shape.</strong> A company card always shows its fields in
                  the same order — dashboards and reports can rely on it.
                </span>
              </li>
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>Structured and unstructured, side by side.</strong> A flat fact like{" "}
                  <em>Revenue</em> and a whole CRM record — name, URL, who introduced the deal,
                  where it sits in the funnel — live as attributes on the same card. The{" "}
                  <em>Affinity</em> attribute below carries the entire record as one JSON value.
                </span>
              </li>
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>Editable, with provenance.</strong> Every fact remembers where it came
                  from and when it was last touched — the Affinity record arrives tagged{" "}
                  <code className="xp-inlinecode">source: "affinity"</code>.
                </span>
              </li>
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>Fed automatically.</strong> Decks and emails enrich the card overnight —
                  nobody retypes data.
                </span>
              </li>
            </ul>
          </Reveal>
          <Reveal delay={120}>
            <CrmDemo onWrite={markDirty} />
          </Reveal>
        </div>
      </section>

      {/* USE CASE: DOCUMENTS */}
      <section className="xp-section">
        <div className="xp-usecase flip">
          <Reveal>
            <div className="xp-eyebrow accent-blue">Use case · Documents</div>
            <h2 className="xp-h2">Documents become memory</h2>
            <p className="xp-lead">
              Drop in a deck, a memo, a report. Three things happen — automatically. Ingest the
              sample memo and check the response; then send the <strong>exact same memo again</strong>{" "}
              and watch it be recognized instead of duplicated.
            </p>
            <ul className="xp-points">
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>Whole or in pieces.</strong> Ask a question and get the exact paragraph;
                  ask for the document and get it back complete.
                </span>
              </li>
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>No double-uploads.</strong> The fingerprint means the same file is never
                  stored — or counted — twice.
                </span>
              </li>
            </ul>
          </Reveal>
          <Reveal delay={120}>
            <DocFlow onWrite={markDirty} />
          </Reveal>
        </div>
      </section>

      {/* USE CASE: RELATIONSHIPS */}
      <section className="xp-section">
        <div className="xp-usecase">
          <Reveal>
            <div className="xp-eyebrow accent-violet">Use case · Relationships</div>
            <h2 className="xp-h2">Everything meets at the entity</h2>
            <p className="xp-lead">
              A deck and an email never link to each other directly — they both point at{" "}
              <strong>Acme</strong>. That single meeting point is why nothing gets lost. An entity
              is <strong>anything worth remembering exactly once</strong> — and whatever its type,
              it is the same kind of card underneath: a label, typed attributes, an embedding, and
              the threads that connect it.
            </p>
            <div className="xp-anatomy" style={{ marginTop: 0 }}>
              <span className="lab">Live in this PoC</span>
              <span className="field">company · Acme Corp</span>
              <span className="field">person · María García</span>
              <span className="field">document · deck_v3.pdf</span>
              <span className="field">email · “Series A follow-up”</span>
              <span className="field">sector · Cybersecurity</span>
              <span className="field">geography · Madrid</span>
              <span className="field">regulation · EU AI Act</span>
            </div>
            <div className="xp-anatomy" style={{ marginTop: 10, marginBottom: 22 }}>
              <span className="lab">And the type system is open</span>
              <span className="field">deal</span>
              <span className="field">investment round</span>
              <span className="field">fund</span>
              <span className="field">LP</span>
              <span className="field">term sheet</span>
              <span className="field">contract</span>
              <span className="field">board seat</span>
              <span className="field">meeting</span>
              <span className="field">note</span>
              <span className="field">task</span>
              <span className="field">team</span>
              <span className="field">technology</span>
              <span className="field">product</span>
              <span className="field">market</span>
              <span className="field">event</span>
              <span className="field">news item</span>
              <span className="field">data source</span>
              <span className="field">agent</span>
              <span className="field">metric series</span>
              <span className="field">thesis</span>
              <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
                — a type earns its place when its attributes or retrieval behavior genuinely
                differ; otherwise it’s an attribute on an existing card.
              </span>
            </div>
            <ul className="xp-points">
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>Open Acme, see everything.</strong> The deck, the email threads, the
                  people, the sector — one view, ordered by time.
                </span>
              </li>
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>Connections write themselves.</strong> “maría@acme.com” is enough for an
                  email to find its way to the right card.
                </span>
              </li>
              <li>
                <span className="tick">✓</span>
                <span>
                  <strong>You already created one.</strong> The memo you ingested above linked
                  itself to Aurora Robotics — that thread is live in the system right now.
                </span>
              </li>
            </ul>
          </Reveal>
          <Reveal delay={120}>
            <HubDiagram />
          </Reveal>
        </div>
      </section>

      {/* HOW LINKS ARE CREATED */}
      <LinksSection />

      {/* USE CASE: DUPLICATES */}
      <section className="xp-section">
        <Reveal>
          <div className="xp-eyebrow accent-amber">Use case · Duplicates</div>
          <h2 className="xp-h2">What happens when two things look alike</h2>
          <p className="xp-lead">
            “Acme Corp”, “Acme Corporation”, “ACME”. Duplicates are what quietly kill most CRMs.
            Here, every new arrival is compared against memory and handled by{" "}
            <strong>how confident the match is</strong> — drag the slider to see the rules, then
            challenge the real engine below.
          </p>
        </Reveal>
        <Reveal delay={120}>
          <DupeSlider onWrite={markDirty} />
        </Reveal>
      </section>

      {/* NIGHT CYCLE */}
      <section className="xp-night">
        <div className="xp-section">
          <Reveal>
            <div className="xp-eyebrow">The night cycle</div>
            <h2 className="xp-h2">While you sleep, the forest tends itself</h2>
            <p className="xp-lead">
              Memory shouldn’t depend on someone remembering to file things. Every night, a quiet
              cycle runs end to end:
            </p>
          </Reveal>
          <div className="xp-nightsteps">
            <Reveal delay={0} className="xp-nightstep">
              <span className="glyph"><Icon d={ICONS.moon} /></span>
              <span className="time">03:00</span>
              <h4>Fetch</h4>
              <p>New emails and documents from the day are collected.</p>
            </Reveal>
            <Reveal delay={90} className="xp-nightstep">
              <span className="glyph"><Icon d={ICONS.search} /></span>
              <h4>Recognize</h4>
              <p>Names are matched against memory — known things enrich their cards, lookalikes are flagged for the morning.</p>
            </Reveal>
            <Reveal delay={180} className="xp-nightstep">
              <span className="glyph"><Icon d={ICONS.thread} /></span>
              <h4>Connect</h4>
              <p>New threads are drawn: this deck describes that company, this email involves that person.</p>
            </Reveal>
            <Reveal delay={270} className="xp-nightstep">
              <span className="glyph"><Icon d={ICONS.tree} /></span>
              <h4>Regrow</h4>
              <p>When enough has changed, the trees reorganize to match how the team actually worked — never on thin evidence.</p>
            </Reveal>
          </div>
          <Reveal delay={200}>
            <div className="xp-night-note">
              <span className="dot" /> Scheduled and running on the live system — nightly at 03:00 UTC.
            </div>
          </Reveal>
        </div>
      </section>

      {/* TWO DOORS */}
      <section className="xp-section">
        <Reveal>
          <div className="xp-eyebrow">Getting answers out</div>
          <h2 className="xp-h2">One memory, two doors</h2>
          <p className="xp-lead">
            People ask in plain language. Systems ask the exact same way every time. Both doors open
            onto the same memory — try them, they’re real.
          </p>
        </Reveal>
        <TwoDoorsLive />
        <Reveal delay={180}>
          <p className="xp-doors-note">
            Same engine underneath — the assistant <strong>fills in the same contract</strong> a
            system would call directly. The section below opens that engine up.
          </p>
        </Reveal>
      </section>

      {/* RETRIEVAL DEEP-DIVE */}
      <RetrievalSection />

      {/* COSTS */}
      <CostSection />

      {/* FOOTER CTA */}
      <section className="xp-footer">
        <Reveal>
          <h2>This isn’t a slide. It’s running.</h2>
          <p>
            Everything you just pressed wrote to — and read from — the live system. Step into the
            forest and find what you created.
          </p>
          <div className="xp-cta-row">
            <button className="xp-btn primary" onClick={onEnterForest}>
              Enter the live forest →
            </button>
            <button className="xp-btn ghost" onClick={onRunDemo}>
              Watch a forest grow from scratch
            </button>
          </div>
        </Reveal>
      </section>

      <CleanupPill visible={dirty} onCleaned={() => setDirty(false)} />
    </div>
  );
}
