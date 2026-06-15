import { useEffect, useRef } from "react";
import "./explainer.css";
import "./research.css";

/* ── Reveal: adds .visible when scrolled into view (fires once) ────── */
function Reveal({ children, delay = 0, as: Tag = "div", className = "" }) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
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
      { threshold: 0.14 }
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

function Icon({ d, ...props }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {Array.isArray(d) ? d.map((p, i) => <path key={i} d={p} />) : <path d={d} />}
    </svg>
  );
}

const ICONS = {
  tenants: ["M3 7l9-4 9 4-9 4-9-4z", "M3 12l9 4 9-4", "M3 17l9 4 9-4"],
  brain: ["M9 4a3 3 0 00-3 3 3 3 0 00-1 5.8A3 3 0 008 18a2.5 2.5 0 004 0V4.5A2 2 0 009 4z", "M15 4a3 3 0 013 3 3 3 0 011 5.8A3 3 0 0116 18a2.5 2.5 0 01-4 0"],
  ingest: ["M4 5h16", "M7 5v6a5 5 0 005 5 5 5 0 005-5V5", "M12 16v5", "M9 21h6"],
  storage: ["M4 5h6v6H4z", "M14 5h6v6h-6z", "M4 15h6v4H4z", "M14 15h6v4h-6z"],
  graph: ["M6 7a2 2 0 100-4 2 2 0 000 4z", "M18 7a2 2 0 100-4 2 2 0 000 4z", "M12 21a2 2 0 100-4 2 2 0 000 4z", "M7 6l4 11", "M17 6l-4 11", "M8 5h8"],
  log: ["M5 4h14v16H5z", "M8 8h8", "M8 12h8", "M8 16h5"],
  shield: ["M12 3l8 3v5c0 4.5-3 8-8 10-5-2-8-5.5-8-10V6z", "M9 12l2 2 4-4"],
  layers: ["M12 3l9 5-9 5-9-5 9-5z", "M3 13l9 5 9-5"],
};

/* The single source of truth. Every use case below is one object in this
   array, and every object is rendered through the SAME component — so the
   structure (Theory → Practical examples → Cost) can never drift between
   sections. Content distilled from memoria_research.md. */
const USE_CASES = [
  {
    id: "multitenancy",
    n: 1,
    accent: "green",
    icon: ICONS.tenants,
    eyebrow: "Use case · Multi-tenant isolation",
    title: "Keeping every client's memory apart",
    tagline: (
      <>
        How one platform serves many firms without a single byte leaking across them — the
        first priority of the whole design.
      </>
    ),
    theory: {
      summary: (
        <>
          Isolation lives on a spectrum of three canonical patterns. The industry default for
          high-scale SaaS is the <strong>pool</strong> model: one shared database where{" "}
          <strong>PostgreSQL Row-Level Security</strong> filters every row by tenant — the same gate
          enforced for the table owner itself.
        </>
      ),
      points: [
        <><strong>Silo</strong> — a database per tenant. Physical isolation, high cost; reserved for regulated or enterprise clients.</>,
        <><strong>Bridge</strong> — a schema per tenant. Strong logical isolation, but migrating N schemas costs N times as much.</>,
        <><strong>Pool</strong> — shared schema, <code>tenant_id</code> on every row, RLS policies. Cheapest, scales to many small tenants.</>,
        <>Vector stores <strong>break the analogy</strong>: filtering an HNSW index by <code>tenant_id</code> silently degrades recall. The fix is <strong>tenant-per-shard / per-namespace</strong> (Weaviate, Pinecone, Qdrant).</>,
      ],
      tension: (
        <>
          Vector multi-tenancy at <strong>medium scale (1K–10K tenants)</strong> is a tooling dead
          zone — pgvector falls short, dedicated clusters are overkill.
        </>
      ),
    },
    examples: [
      { src: "PostgreSQL RLS", how: <>The canonical pattern: <code>SET LOCAL app.current_tenant</code> per request, <code>FORCE ROW LEVEL SECURITY</code> on every multi-tenant table — exactly what our <code>memory-mcp-server</code> does.</> },
      { src: "Weaviate / Pinecone", how: <>A dedicated vector index per tenant; cold tenants offload to object storage and reload on demand.</> },
      { src: "Our memory", how: <>Pool + RLS today (pgvector with a partition per tenant); an adapter seam leaves the door open to a tenant-per-shard store at scale, with no refactor.</> },
    ],
    cost: {
      headline: "Near-zero per tenant",
      sub: "RLS runs inside the database — no extra service, no per-query AI",
      rows: [
        { label: "Row-Level Security enforcement", how: "A predicate appended to every query, in-database", amt: "$0" },
        { label: "Pool model (shared DB)", how: "One Postgres instance amortized across all tenants", amt: "shared" },
        { label: "Silo model (DB per tenant)", how: "Full instance + backups per client", amt: "high" },
        { label: "Per-tenant restore (pool)", how: "Point-in-time recovery + extraction — the hidden cost", amt: "ops-heavy" },
      ],
      note: "The pool model is the cheapest to run but the most expensive to restore one tenant from — budget for logical per-tenant backups before you need them.",
    },
  },
  {
    id: "agentic-memory",
    n: 2,
    accent: "violet",
    icon: ICONS.brain,
    eyebrow: "Use case · Agentic memory",
    title: "Memory that learns as agents work",
    tagline: (
      <>
        Beyond fetching documents — a living layer that accumulates experience, preferences and
        decisions, modeled on how human memory is organized.
      </>
    ),
    theory: {
      summary: (
        <>
          The field converges on a <strong>cognitive taxonomy</strong> — working, episodic, semantic
          and procedural memory — fed by an <strong>asynchronous, LLM-driven extraction</strong>{" "}
          process that distills conversations into structured long-term records.
        </>
      ),
      points: [
        <><strong>Working</strong> (the active context) · <strong>episodic</strong> (events with time) · <strong>semantic</strong> (abstracted facts) · <strong>procedural</strong> (how to do things).</>,
        <>Two production paradigms: <strong>Mem0</strong> (dual-store vector + knowledge graph) and <strong>Zep / Graphiti</strong> (a <strong>bi-temporal</strong> knowledge graph — when it happened vs when we learned it).</>,
        <><strong>RAG ≠ agent memory.</strong> RAG fetches external documents once; agent memory maintains evolving state. Keep them conceptually separate.</>,
        <>Pragmatic advice: start with short- and long-term memory only; add episodic/procedural when value justifies the complexity.</>,
      ],
      tension: (
        <>
          Mem0 and Zep publish <strong>contradictory benchmarks</strong> — no clear winner. And
          curated (LLM-extracted) vs raw memory has no consensus; hybrid is the pragmatic bet.
        </>
      ),
    },
    examples: [
      { src: "Mem0 / Zep / Letta", how: <>Entities extracted from each interaction; consolidation runs while the agent is idle — "sleep-time compute".</> },
      { src: "Bi-temporal model", how: <>Reconstruct "what the system knew on day X" — real auditability for operational decisions.</> },
      { src: "Our memory", how: <>The extraction pipeline is just a <strong>Run</strong> (observable, versioned); the backend stays swappable behind an adapter — we never marry one vendor. Our night cycle ≈ idle consolidation.</> },
    ],
    cost: {
      headline: "Pennies, batched overnight",
      sub: "Extraction is LLM work, but small, async and batchable",
      rows: [
        { label: "Extract memory from one event", how: "1 small LLM call (gpt-4o-mini) + 1 embedding", amt: "≈ $0.0004" },
        { label: "Embedding a fact", how: "~20 tokens at $0.02 / 1M", amt: "≈ $0.000001" },
        { label: "Nightly consolidation", how: "Runs while idle — no user-facing latency", amt: "batched" },
        { label: "Reading a memory back", how: "Vector / graph lookup, in-database", amt: "$0" },
      ],
      note: "Because extraction is asynchronous, its cost never sits on the critical path — the agent answers from already-distilled memory.",
    },
  },
  {
    id: "ingestion",
    n: 3,
    accent: "blue",
    icon: ICONS.ingest,
    eyebrow: "Use case · Heterogeneous ingestion",
    title: "Pulling in ERPs, CRMs and everything else",
    tagline: (
      <>
        Many sources, many shapes, one memory — captured continuously and refined in layers
        without ever losing the raw original.
      </>
    ),
    theory: {
      summary: (
        <>
          Two patterns dominate: the <strong>medallion architecture</strong> (bronze → silver → gold)
          as a logical organization, and <strong>log-based Change Data Capture</strong> (Debezium)
          as the capture mechanism that reads a source's write-ahead log with minimal impact.
        </>
      ),
      points: [
        <><strong>Bronze</strong> raw &amp; immutable · <strong>silver</strong> cleaned &amp; conformed · <strong>gold</strong> business-ready products.</>,
        <>Four capture methods: <strong>log-based</strong> (default) · trigger-based · timestamp-based (misses deletes) · snapshot-diff (last resort).</>,
        <>A <strong>schema registry</strong> handles the chronic problem — source schemas drift; reject incompatible messages early.</>,
        <>Structural limit: medallion's multi-hop delay <strong>can't feed real-time agent decisions</strong> — agents read the operational store, not gold.</>,
      ],
      tension: (
        <>
          When to migrate from lakehouse/medallion to an operational store is open; so is{" "}
          <strong>schema evolution over already-vectorized data</strong> (re-embedding 10M chunks is
          costly).
        </>
      ),
    },
    examples: [
      { src: "Debezium + Kafka/Redpanda", how: <>Log-based CDC publishes change events to a streaming bus — directly compatible with our single bus.</> },
      { src: "Connectors", how: <>A Salesforce or SAP connector is just a Connection + Trigger + Component; what's ingested and where it lands is declarative YAML.</> },
      { src: "Our memory", how: <>Every CDC event carries <code>tenant_id</code> from the bronze layer onward — there is never a raw bucket without a tenant. Redpanda partitions by tenant.</> },
    ],
    cost: {
      headline: "Mostly storage + streaming",
      sub: "Capture is cheap; the bill is the bus and the bronze tier",
      rows: [
        { label: "Bronze raw storage", how: "Object storage, immutable, compresses well", amt: "low /GB" },
        { label: "CDC capture (log-based)", how: "Reads the WAL — negligible load on the source", amt: "minimal" },
        { label: "Streaming bus retention", how: "Redpanda/Kafka holds events for replay", amt: "scales w/ volume" },
        { label: "Silver/gold transforms", how: "Periodic compute, not per-event", amt: "batched" },
      ],
      note: "Bronze is cheap object storage; the real lever is bus retention and how long you keep replayable history.",
    },
  },
  {
    id: "layered-storage",
    n: 4,
    accent: "blue",
    icon: ICONS.storage,
    eyebrow: "Use case · Layered storage",
    title: "The right store for each kind of work",
    tagline: (
      <>
        One memory is not one technology. Split storage by <strong>workload</strong>, not by data
        type — metadata, blobs, vectors, text, graph and events each have a different profile.
      </>
    ),
    theory: {
      summary: (
        <>
          The consolidated rule: <strong>separate stores by workload characteristics</strong>.
          Metadata is OLTP (frequent, small, latency-sensitive); content is the opposite (large,
          bandwidth-heavy, latency-tolerant). The 2026 RAG default adds{" "}
          <strong>hybrid search + reranking</strong>.
        </>
      ),
      points: [
        <>Metadata in Postgres (with RLS); binary content in S3-compatible object storage, referenced by URI.</>,
        <>Retrieval pipeline: <strong>dense + sparse (BM25)</strong> → Reciprocal Rank Fusion → <strong>cross-encoder rerank</strong> → top-K.</>,
        <>Specialized stores: pgvector → Weaviate at scale · Postgres FTS → Elasticsearch · Neo4j for graph · DuckDB → BigQuery for OLAP.</>,
        <>The cache layer almost everyone designs late: <strong>embedding cache</strong>, retrieval cache, LLM-response cache.</>,
      ],
      tension: (
        <>
          Retrieval caching in agentic systems splits the field — "always fresh" vs "cache
          aggressively". Decide case by case, scoped per tenant with short TTLs.
        </>
      ),
    },
    examples: [
      { src: "Metadata vs content", how: <>"All contracts for client X" only needs the searchable metadata — never drag the heavyweight files through the query.</> },
      { src: "Hybrid + rerank", how: <>BM25 + dense retrieval beats either alone; a cross-encoder reranker sharpens precision.</> },
      { src: "Our memory", how: <>Every store sits behind the <code>memory-mcp-server</code>; store-agnostic adapters keep the memory portable. The retrieval pipeline is a declarative composition, not a "RAG service".</> },
    ],
    cost: {
      headline: "Cheap blobs, paid RAM, optional rerank",
      sub: "Each store's cost matches its workload",
      rows: [
        { label: "Object storage (content)", how: "Pennies per GB, lifecycle tiering hot→cold", amt: "low /GB" },
        { label: "Vector index", how: "Lives in RAM — the real cost is memory footprint", amt: "RAM-bound" },
        { label: "Cross-encoder rerank", how: "Per-query model call — adds latency + cost", amt: "≈ $0.001 /query" },
        { label: "Embedding cache hit", how: "Skips recomputation entirely", amt: "$0" },
        { label: "Full-text / SQL search", how: "Pure in-database", amt: "$0" },
      ],
      note: "Reranking is the one place to spend deliberately — turn it on where precision pays, cache embeddings everywhere to avoid recompute.",
    },
  },
  {
    id: "knowledge-graph",
    n: 5,
    accent: "violet",
    icon: ICONS.graph,
    eyebrow: "Use case · Knowledge graph",
    title: "Relationships as first-class records",
    tagline: (
      <>
        Typed, weighted, traversable connections — with an ontology designed up front and duplicate
        entities resolved, or the graph becomes noise.
      </>
    ),
    theory: {
      summary: (
        <>
          Choose the backend by need: <strong>property graphs</strong> (Neo4j) for enterprise,{" "}
          <strong>triple stores</strong> (RDF) for formal ontologies, <strong>temporal KGs</strong>{" "}
          (Graphiti) for agentic memory with explicit time. But the step people skip — and that
          breaks everything — is <strong>ontology design before writing a single node</strong>.
        </>
      ),
      points: [
        <>Define entities → relationships → attributes → validate on a small instance → add indexes &amp; constraints <em>early</em>.</>,
        <><strong>Entity resolution</strong> is the chronic problem: "Acme Corp", "ACME Corp.", "acme-corp" must collapse to one node. Methods range deterministic → probabilistic → ML → LLM-driven.</>,
        <>Multi-tenancy in KGs is a <strong>gray zone</strong>: graph-per-tenant (clean, costly), tenant-aware properties (RLS-like), or sub-graph isolation.</>,
      ],
      tension: (
        <>
          There is <strong>no standard pattern</strong> for multi-tenant knowledge graphs — every
          implementation invents its own.
        </>
      ),
    },
    examples: [
      { src: "Ontology", how: <>For PE/VC + SMEs: Tenant, User, Deal, Company, Person, Document, Process, Run — with bi-temporal <code>PARTICIPATED_IN</code> edges where Graphiti shines.</> },
      { src: "Entity resolution", how: <>The same machinery that prevents duplicate cards: trigram + embedding scoring with thresholds, escalating to human review.</> },
      { src: "Our memory", how: <>Cypher schema constraints are declarative artifacts (YAML-adjacent). Tenant-aware properties + <code>tenant_id</code> injected into every query by the <code>memory-mcp-server</code> preserve isolation without a graph per tenant.</> },
    ],
    cost: {
      headline: "Hosting + the ER you choose",
      sub: "The graph is cheap to query; resolving entities is where you spend",
      rows: [
        { label: "Graph database hosting", how: "Property-graph instance (Neo4j/FalkorDB)", amt: "flat /mo" },
        { label: "Indexes & constraints", how: "Mandatory, but cheap to maintain", amt: "≈ $0" },
        { label: "Deterministic / trigram ER", how: "In-database scoring", amt: "$0" },
        { label: "LLM-driven entity resolution", how: "1 LLM call per ambiguous pair — the expensive path", amt: "≈ $0.0005 /pair" },
        { label: "Graph traversal", how: "One indexed hop", amt: "$0" },
      ],
      note: "Keep entity resolution deterministic by default; reserve the LLM for genuinely ambiguous cases, where it's worth the call.",
    },
  },
  {
    id: "event-log",
    n: 6,
    accent: "amber",
    icon: ICONS.log,
    eyebrow: "Use case · Event log",
    title: "An append-only history you can replay",
    tagline: (
      <>
        Atomic writes to the database and the bus at once, and a durable log that lets you
        reconstruct exactly what happened — without paying for full event sourcing.
      </>
    ),
    theory: {
      summary: (
        <>
          The <strong>outbox pattern</strong> solves atomicity: write the business row and an{" "}
          <code>event_log</code> row in the <strong>same transaction</strong>, then a separate
          process publishes to the bus. The difference between outbox, event sourcing and CDC is{" "}
          <strong>intent</strong>, not format.
        </>
      ),
      points: [
        <><strong>Outbox + projections</strong> — the database is canonical, the log notifies.</>,
        <><strong>Event sourcing</strong> — the log <em>is</em> canonical; state is rebuilt from it. Powerful, but a steep learning curve and hard to query.</>,
        <><strong>CDC</strong> — the database is canonical; an external process derives the log.</>,
        <>Pragmatic choice: outbox for internal events + CDC for external sources. Full event sourcing rarely pays off in modern SaaS.</>,
      ],
      tension: (
        <>
          Event sourcing <em>pure</em> vs outbox-with-projections is a real fork — most teams
          over-reach for sourcing and pay the query/replay complexity tax.
        </>
      ),
    },
    examples: [
      { src: "Outbox transaction", how: <>One <code>BEGIN…COMMIT</code> inserts both the order and its <code>OrderCreated</code> event — they can't diverge.</> },
      { src: "Replay", how: <>Persist bus events in <code>event_log</code> so the history of logical units can be rebuilt on demand.</> },
      { src: "Our memory", how: <>Outbox guarantees write-storage + write-event atomicity. We apply replay to <strong>logical units</strong>, not business entities — auditability without the cost of pure event sourcing.</> },
    ],
    cost: {
      headline: "Append-only, so cheap but growing",
      sub: "Writes are trivial; the cost is retention over time",
      rows: [
        { label: "Outbox write", how: "One extra INSERT inside an existing transaction", amt: "≈ $0" },
        { label: "event_log storage", how: "Append-only rows, grows monotonically", amt: "low, accruing" },
        { label: "Bus publish", how: "Background process, batched", amt: "minimal" },
        { label: "Replay a history", how: "Occasional read + recompute", amt: "on-demand" },
      ],
      note: "The only growing line is log retention — partition by time and archive cold segments to object storage to keep it flat.",
    },
  },
  {
    id: "access-control",
    n: 7,
    accent: "green",
    icon: ICONS.shield,
    eyebrow: "Use case · Access control",
    title: "Who sees what, enforced in one place",
    tagline: (
      <>
        Agents reach the memory through a mediated server that checks identity, propagates tenant
        context, and filters results to the caller's clearance — never all-or-nothing.
      </>
    ),
    theory: {
      summary: (
        <>
          The consolidated MCP pattern is a <strong>centralized gateway</strong> for routing and
          allowlisting, with <strong>fine-grained authorization at the layer server</strong>. One
          broad token that grants the whole toolset is the documented anti-pattern.
        </>
      ),
      points: [
        <>The <strong>gateway</strong> routes and allowlists — it holds <strong>no layer semantics</strong>.</>,
        <>The <strong>layer server</strong> validates the user belongs to the tenant, computes effective permissions, sets <code>SET LOCAL app.current_tenant_id</code>, then filters.</>,
        <><strong>Permission inheritance</strong>: the agent acts with the invoking user's clearance, enforced server-side — not in the agent, not in the gateway.</>,
      ],
      tension: (
        <>
          Mostly settled — the OWASP MCP Top 10 and industry guidance now align. The open edge is
          delegation depth: how far a chain of agents may carry an inherited clearance.
        </>
      ),
    },
    examples: [
      { src: "Context propagation", how: <>An agent call carries <code>{`{tenant_id, invoking_user_id, security_groups}`}</code>; the server validates, scopes RLS, and returns only what the user may see.</> },
      { src: "Gateway vs server", how: <>Gateway = basic auth + routing; layer server = fine-grained RBAC — exactly the split the industry recommends.</> },
      { src: "Our memory", how: <>Access classes (public / confidential / restricted) on every record; RLS filters to clearance <em>inside the database</em>, so restricted rows never enter the ranking or the counts. Already live in this PoC.</> },
    ],
    cost: {
      headline: "Effectively free",
      sub: "Authorization is in-process and in-database — no AI, no extra service",
      rows: [
        { label: "Identity / tenant validation", how: "In-process check on each call", amt: "$0" },
        { label: "Permission computation", how: "Union of security groups, cached", amt: "$0" },
        { label: "RLS clearance filter", how: "Predicate inside the same query", amt: "$0" },
        { label: "Gateway routing", how: "Allowlist + forward", amt: "negligible" },
      ],
      note: "Security here costs essentially nothing to run because it's enforced where the data already lives — the database — not in a separate paid layer.",
    },
  },
];

/* ── Hero: the six-subsystem memory at a glance ───────────────────── */
function MemoryDiagram() {
  const stores = [
    { x: 70, label: "Relational", sub: "Postgres · RLS" },
    { x: 188, label: "Object", sub: "S3-compatible" },
    { x: 306, label: "Vector", sub: "pgvector→shard" },
    { x: 424, label: "Graph", sub: "property KG" },
    { x: 542, label: "Event log", sub: "append-only" },
    { x: 660, label: "Agentic", sub: "curated view" },
  ];
  const HUB_Y = 64;
  const STORE_Y = 190;
  return (
    <svg className="rp-diagram" viewBox="0 0 760 290" fill="none" aria-hidden="true">
      <defs>
        <marker id="rp-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M1 1l6 3-6 3" fill="none" stroke="#c8c8cd" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
      </defs>

      {stores.map((s) => (
        <line key={`l-${s.x}`} className="rp-edge" x1={380} y1={HUB_Y + 26} x2={s.x} y2={STORE_Y - 30} markerEnd="url(#rp-arrow)" />
      ))}

      {/* the mediating server */}
      <g>
        <rect x={250} y={HUB_Y - 26} width={260} height={52} rx={12} fill="#16181d" />
        <text x={380} y={HUB_Y - 3} textAnchor="middle" className="rp-hub-label">memory-mcp-server</text>
        <text x={380} y={HUB_Y + 14} textAnchor="middle" className="rp-hub-sub">auth · RLS · RBAC · one service layer</text>
      </g>

      {stores.map((s) => (
        <g key={s.label}>
          <rect x={s.x - 54} y={STORE_Y - 30} width={108} height={60} rx={10} fill="#fafafa" stroke="#e4e4e7" />
          <text x={s.x} y={STORE_Y - 4} textAnchor="middle" className="rp-store-label">{s.label}</text>
          <text x={s.x} y={STORE_Y + 14} textAnchor="middle" className="rp-store-sub">{s.sub}</text>
        </g>
      ))}

      {/* ingestion lane */}
      <text x={380} y={262} textAnchor="middle" className="rp-lane">Ingestion: CDC / Triggers / Components → bus (Redpanda) → bronze → silver / gold</text>
    </svg>
  );
}

/* ── The uniform renderer: every use case goes through this ────────── */
function UseCase({ uc }) {
  return (
    <section className="xp-section">
      <Reveal>
        <div className={`xp-eyebrow accent-${uc.accent}`}>{uc.eyebrow}</div>
        <div className="rp-uc-head">
          <span className={`rp-uc-icon ${uc.accent}`}><Icon d={uc.icon} /></span>
          <div>
            <h2 className="xp-h2" style={{ marginBottom: 6 }}>{uc.title}</h2>
            <p className="xp-lead" style={{ marginBottom: 0 }}>{uc.tagline}</p>
          </div>
        </div>
      </Reveal>

      <div className="rp-uc-grid">
        {/* 1 · Theoretical approach */}
        <Reveal delay={0} className={`rp-panel theory accent-${uc.accent}`}>
          <span className="rp-panel-lab">1 · Theoretical approach</span>
          <p className="rp-panel-summary">{uc.theory.summary}</p>
          <ul className="rp-points">
            {uc.theory.points.map((p, i) => (
              <li key={i}><span className="rp-tick" />{p}</li>
            ))}
          </ul>
          <div className="rp-tension">
            <span className="lab">Where consensus breaks</span>
            <p>{uc.theory.tension}</p>
          </div>
        </Reveal>

        {/* 2 · Practical examples */}
        <Reveal delay={90} className={`rp-panel examples accent-${uc.accent}`}>
          <span className="rp-panel-lab">2 · Practical examples</span>
          <div className="rp-examples">
            {uc.examples.map((ex, i) => (
              <div key={i} className="rp-example">
                <span className="src">{ex.src}</span>
                <span className="how">{ex.how}</span>
              </div>
            ))}
          </div>
        </Reveal>

        {/* 3 · Cost */}
        <Reveal delay={180} className={`rp-panel cost accent-${uc.accent}`}>
          <span className="rp-panel-lab">3 · What it costs</span>
          <div className="rp-cost-headline">
            {uc.cost.headline}
            <small>{uc.cost.sub}</small>
          </div>
          <div className="rp-costtable">
            {uc.cost.rows.map((r, i) => (
              <div key={i} className="rp-cost-row">
                <span className="cl">
                  <span className="lbl">{r.label}</span>
                  <span className="how">{r.how}</span>
                </span>
                <span className={`amt ${r.amt === "$0" ? "free" : ""}`}>{r.amt}</span>
              </div>
            ))}
          </div>
          <p className="rp-cost-note">{uc.cost.note}</p>
        </Reveal>
      </div>
    </section>
  );
}

/* ── Page ─────────────────────────────────────────────────────────── */
export default function ResearchPage({ onBack, onEnterForest }) {
  return (
    <div className="xp-root rp-root">
      <header className="xp-topbar">
        <div className="brand">
          <span className="logomark">K</span>
          Memory Layer · Industry research
        </div>
        <nav>
          <button className="xp-btn ghost" style={{ padding: "9px 18px", fontSize: 13 }} onClick={onBack}>
            ← How it works
          </button>
        </nav>
      </header>

      {/* HERO */}
      <section className="xp-hero">
        <Reveal>
          <div className="xp-eyebrow">The studied use cases · state of the art, 2026</div>
          <h1>
            Seven use cases.
            <br />
            <em>One structure each.</em>
          </h1>
          <p className="xp-lead">
            What the industry considers best practice for a multi-tenant memory layer — distilled
            into seven use cases. Every one is explained the same way:{" "}
            <strong>the theoretical approach</strong>, <strong>practical examples</strong>, and{" "}
            <strong>what it costs to run</strong> — then mapped to this system.
          </p>
          <div className="xp-cta-row">
            <a className="xp-btn ghost" href="#multitenancy" style={{ textDecoration: "none", display: "inline-block" }}>
              Start reading ↓
            </a>
          </div>
        </Reveal>
        <Reveal delay={150}>
          <MemoryDiagram />
        </Reveal>
      </section>

      {/* STRUCTURE LEGEND + INDEX */}
      <section className="xp-section">
        <Reveal>
          <div className="xp-eyebrow">How to read this page</div>
          <h2 className="xp-h2">The same three lenses, every time</h2>
          <p className="xp-lead">
            Memory is not one thing — it's a set of sub-systems with very different workloads. To
            compare them fairly, each use case below is broken down through the identical structure.
          </p>
        </Reveal>
        <div className="rp-legend">
          <Reveal delay={0} className="rp-legend-card">
            <span className="num">1</span>
            <h3>Theoretical approach</h3>
            <p>The dominant industry pattern, the alternatives, and the honest note on where consensus breaks.</p>
          </Reveal>
          <Reveal delay={90} className="rp-legend-card">
            <span className="num">2</span>
            <h3>Practical examples</h3>
            <p>Real tools that implement it, and how the pattern maps onto this memory layer.</p>
          </Reveal>
          <Reveal delay={180} className="rp-legend-card">
            <span className="num">3</span>
            <h3>What it costs</h3>
            <p>The cost drivers, with concrete numbers where they exist — and what's effectively free.</p>
          </Reveal>
        </div>
        <Reveal delay={120}>
          <div className="rp-index">
            {USE_CASES.map((uc) => (
              <a key={uc.id} href={`#${uc.id}`} className={`rp-index-item accent-${uc.accent}`}>
                <span className="rp-index-icon"><Icon d={uc.icon} /></span>
                <span className="rp-index-n">{String(uc.n).padStart(2, "0")}</span>
                <span className="rp-index-title">{uc.title}</span>
              </a>
            ))}
          </div>
        </Reveal>
      </section>

      {/* THE SEVEN USE CASES — uniform */}
      {USE_CASES.map((uc) => (
        <div key={uc.id} id={uc.id}>
          <UseCase uc={uc} />
        </div>
      ))}

      {/* CLOSING NOTE */}
      <section className="xp-section">
        <Reveal>
          <div className="xp-eyebrow accent-amber">A note on honesty</div>
          <h2 className="xp-h2">Where the industry has no answer yet</h2>
          <p className="xp-lead">
            Each use case above flags its own open tension. Taken together, the unsolved problems of
            2026 are worth naming plainly — these are the places to decide with data, not intuition.
          </p>
        </Reveal>
        <div className="xp-anatomy" style={{ marginTop: 0 }}>
          <span className="lab">Open questions</span>
          <span className="field">vector multi-tenancy at 1K–10K tenants</span>
          <span className="field">Mem0 vs Zep vs roll-your-own</span>
          <span className="field">multi-tenant knowledge graphs</span>
          <span className="field">retrieval caching for agents</span>
          <span className="field">curated vs raw agent memory</span>
          <span className="field">lakehouse → operational store migration</span>
          <span className="field">schema evolution over vectorized data</span>
        </div>
      </section>

      {/* FOOTER CTA */}
      <section className="xp-footer">
        <Reveal>
          <h2>From research to a running system.</h2>
          <p>
            Every pattern above is already shaping this memory layer. See how it works end to end,
            or step into the live forest.
          </p>
          <div className="xp-cta-row">
            <button className="xp-btn primary" onClick={onBack}>
              ← Back to how it works
            </button>
            {onEnterForest && (
              <button className="xp-btn ghost" onClick={onEnterForest}>
                Enter the live forest →
              </button>
            )}
          </div>
        </Reveal>
      </section>
    </div>
  );
}
