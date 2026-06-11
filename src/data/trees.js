import * as THREE from "three";

// Each TREE is a *category*. Each branch is an *instance* in that category.
// Leaves are properties of that instance. Cross-links connect branches across trees.
export const TREES = [
  // ── Domain trees ──────────────────────────────────────────────
  {
    id: "sectors",
    label: "SECTOR TREE",
    subtitle: "Sectors",
    type: "entity",
    pos: [-22, 0, -7],
    branches: [
      { id: "sector:cyber",   name: "Cybersecurity",      leaves: ["Market: $180B", "CAGR: 12%", "Conf: high"], links: [{ id: "sector:ai-infra", why: "AI powers next-gen threat detection; cybersecurity protects AI infrastructure" }] },
      { id: "sector:fintech", name: "Fintech",            leaves: ["Market: $310B", "CAGR: 9%", "Conf: med"], links: [{ id: "sector:consumer", why: "Fintech serves consumer markets via payments and neobanks" }] },
      { id: "sector:biotech", name: "Biotech",            leaves: ["Market: $497B", "CAGR: 14%", "Conf: high"], links: [{ id: "sector:consumer", why: "Biotech consumer health products drive direct-to-consumer growth" }] },
      { id: "sector:consumer",name: "Consumer Tech",      leaves: ["Market: $1.2T", "CAGR: 6%"] },
      { id: "sector:ai-infra",name: "AI Infrastructure",  leaves: ["Market: $82B", "CAGR: 38%"] },
    ],
  },
  {
    id: "companies",
    label: "COMPANY TREE",
    subtitle: "Companies",
    type: "entity",
    pos: [0, 0, -16],
    branches: [
      { id: "company:crowdstrike", name: "CrowdStrike", leaves: ["Rev: $3.06B", "PE: 7.8", "CEO: Kurtz"], links: [{ id: "sector:cyber", why: "Primary sector — endpoint security market leader" }, { id: "company:wiz", why: "Direct competitor in cloud security; both compete for enterprise CISO budgets" }] },
      { id: "company:wiz",         name: "Wiz",         leaves: ["Rev: $500M", "PE: 8.5", "CEO: Rappaport"], links: [{ id: "sector:cyber", why: "Primary sector — cloud-native security platform" }] },
      { id: "company:apple",       name: "Apple",       leaves: ["Rev: $383B", "PE: 9.1", "CEO: Cook"], links: [{ id: "sector:consumer", why: "Primary sector — consumer hardware and services" }] },
      { id: "company:stripe",      name: "Stripe",      leaves: ["Rev: $14.4B", "PE: 8.2", "CEO: Collison"], links: [{ id: "sector:fintech", why: "Primary sector — payments infrastructure" }] },
      { id: "company:nvidia",      name: "NVIDIA",      leaves: ["Rev: $60B", "PE: 9.4", "CEO: Huang"], links: [{ id: "sector:ai-infra", why: "Primary sector — dominant GPU supplier for AI training" }] },
      { id: "company:moderna",     name: "Moderna",     leaves: ["Rev: $6.8B", "PE: 6.2", "CEO: Bancel"], links: [{ id: "sector:biotech", why: "Primary sector — mRNA therapeutics pioneer" }] },
      { id: "company:factorial",   name: "Factorial",   leaves: ["Rev: €80M", "Stage: Series C", "HQ: Barcelona"], links: [{ id: "sector:fintech", why: "HR/fintech SaaS platform" }] },
      { id: "company:jobandtalent",name: "Jobandtalent", leaves: ["Rev: €200M", "Stage: Series E", "HQ: Madrid"], links: [{ id: "sector:consumer", why: "Workforce marketplace" }, { id: "geo:spain", why: "HQ Madrid" }] },
      { id: "company:clarity-ai",  name: "Clarity AI",  leaves: ["Rev: €30M", "Stage: Series B", "HQ: Madrid"], links: [{ id: "sector:ai-infra", why: "AI-powered sustainability analytics" }] },
      { id: "company:seedtag",     name: "Seedtag",     leaves: ["Rev: €100M", "Stage: Growth", "HQ: Madrid"], links: [{ id: "sector:consumer", why: "Contextual AI advertising for brands" }, { id: "sector:ai-infra", why: "AI-native ad platform" }] },
    ],
  },
  {
    id: "people",
    label: "PEOPLE TREE",
    subtitle: "People",
    type: "entity",
    pos: [22, 0, -7],
    branches: [
      { id: "person:kurtz",    name: "George Kurtz",    leaves: ["CEO CrowdStrike", "Austin, TX"], links: [{ id: "company:crowdstrike", why: "Founder & CEO since 2011" }, { id: "person:huang", why: "Strategic partner — CrowdStrike uses NVIDIA GPUs for AI-driven threat detection" }] },
      { id: "person:cook",     name: "Tim Cook",        leaves: ["CEO Apple", "Cupertino"],         links: [{ id: "company:apple", why: "CEO since 2011, succeeded Steve Jobs" }, { id: "person:collison", why: "Apple Pay partnership — Stripe powers Apple's payment processing" }, { id: "person:huang", why: "Silicon Valley peers; both lead hardware-centric platforms" }] },
      { id: "person:collison", name: "Patrick Collison",leaves: ["CEO Stripe", "SF"],               links: [{ id: "company:stripe", why: "Co-founder & CEO since 2010" }] },
      { id: "person:huang",    name: "Jensen Huang",    leaves: ["CEO NVIDIA", "Santa Clara"],      links: [{ id: "company:nvidia", why: "Co-founder & CEO since 1993" }] },
    ],
  },
  {
    id: "geographies",
    label: "GEOGRAPHY TREE",
    subtitle: "Geographies",
    type: "entity",
    pos: [-32, 0, -18],
    branches: [
      { id: "geo:spain", name: "Spain", leaves: ["GDP: $1.4T", "VC 2024: €2.1B", "Hub: Madrid/Barcelona"], links: [{ id: "company:factorial", why: "HQ Barcelona" }, { id: "company:seedtag", why: "HQ Madrid" }] },
      { id: "geo:europe", name: "Europe", leaves: ["GDP: $18.3T", "VC 2024: €52B", "Hubs: London/Berlin/Paris"], links: [{ id: "reg:gdpr", why: "GDPR is the defining regulatory framework" }] },
      { id: "geo:us", name: "United States", leaves: ["GDP: $27T", "VC 2024: $170B", "Hubs: SF/NYC/Austin"], links: [{ id: "company:crowdstrike", why: "HQ Austin, TX" }, { id: "company:stripe", why: "HQ San Francisco" }, { id: "company:nvidia", why: "HQ Santa Clara" }, { id: "reg:sec", why: "SEC regulates US capital markets" }] },
      { id: "geo:latam", name: "Latin America", leaves: ["GDP: $5.7T", "VC 2024: $4.2B", "Hubs: Sao Paulo/Mexico City"], links: [{ id: "sector:fintech", why: "Fintech is the dominant VC sector in LatAm" }] },
    ],
  },
  {
    id: "regulation",
    label: "REGULATION TREE",
    subtitle: "Regulation",
    type: "entity",
    pos: [22, 0, -22],
    branches: [
      { id: "reg:gdpr", name: "GDPR", leaves: ["Scope: EU data protection", "Enacted: 2018", "Max fine: 4% global rev"], links: [{ id: "geo:europe", why: "Applies across all EU/EEA member states" }, { id: "sector:cyber", why: "Drives demand for data protection and security tools" }, { id: "company:crowdstrike", why: "GDPR compliance is a sales driver for endpoint security" }] },
      { id: "reg:sec", name: "SEC Regulations", leaves: ["Scope: US securities", "Key: Reg D, Reg S", "Impact: fund formation rules"], links: [{ id: "geo:us", why: "Governs US capital markets and fund registration" }, { id: "sector:fintech", why: "Regulates fintech companies offering securities services" }] },
      { id: "reg:eu-ai-act", name: "EU AI Act", leaves: ["Scope: AI risk classification", "Enacted: 2024", "Phases: 2025-2027"], links: [{ id: "geo:europe", why: "First comprehensive AI regulation globally" }, { id: "sector:ai-infra", why: "Directly regulates AI model providers and deployers" }, { id: "agent:research", why: "AI agents must comply with transparency requirements" }] },
      { id: "reg:mifid", name: "MiFID II", leaves: ["Scope: EU financial markets", "Enacted: 2018", "Focus: investor protection"], links: [{ id: "sector:fintech", why: "Governs fintech firms offering investment services in EU" }, { id: "geo:europe", why: "Applies across EU financial services sector" }] },
    ],
  },
  // ── System trees ──────────────────────────────────────────────
  {
    id: "components",
    label: "COMPONENT TREE",
    subtitle: "Components",
    type: "system",
    pos: [-29, 0, 11],
    branches: [
      { id: "comp:orchestrator", name: "Orchestrator", leaves: ["Type: core", "Runtime: Node.js", "Manages agent lifecycle"], links: [{ id: "agent:research", why: "Orchestrator dispatches research agents" }, { id: "flow:sector-scan", why: "Orchestrator executes flow definitions" }, { id: "arch:event-bus", why: "Communicates via the event bus" }] },
      { id: "comp:knowledge-store", name: "Knowledge Store", leaves: ["Type: persistence", "Backend: vector DB", "Stores forest state"], links: [{ id: "arch:data-layer", why: "Part of the data layer architecture" }] },
      { id: "comp:api-gateway", name: "API Gateway", leaves: ["Type: infrastructure", "Auth: OAuth2 + API keys", "Rate limited"], links: [{ id: "tool:web-search", why: "Routes external API calls through the gateway" }, { id: "arch:service-mesh", why: "Entry point for the service mesh" }] },
      { id: "comp:scheduler", name: "Scheduler", leaves: ["Type: core", "Cron + event-driven", "Triggers flows"], links: [{ id: "flow:sector-scan", why: "Triggers scheduled sector scan flows" }] },
    ],
  },
  {
    id: "agents",
    label: "AGENT TREE",
    subtitle: "Agents",
    type: "system",
    pos: [-25, 0, 25],
    branches: [
      { id: "agent:research", name: "Research Agent", leaves: ["Model: Claude", "Context: 200K", "Autonomy: high"], links: [{ id: "skill:web-research", why: "Primary skill — gathers data from web sources" }, { id: "skill:analysis", why: "Analyzes gathered data for investment signals" }] },
      { id: "agent:analyst", name: "Analyst Agent", leaves: ["Model: Claude", "Context: 200K", "Autonomy: medium"], links: [{ id: "skill:analysis", why: "Core skill for financial analysis" }, { id: "skill:report-gen", why: "Generates investment memos and reports" }] },
      { id: "agent:monitor", name: "Monitor Agent", leaves: ["Model: Claude Haiku", "Context: 100K", "Autonomy: low"], links: [{ id: "skill:alerting", why: "Triggers alerts on portfolio events" }] },
      { id: "agent:connector", name: "Connector Agent", leaves: ["Model: Claude Haiku", "Context: 100K", "Autonomy: medium"], links: [{ id: "skill:web-research", why: "Researches network connections" }] },
    ],
  },
  {
    id: "skills",
    label: "SKILL TREE",
    subtitle: "Skills",
    type: "system",
    pos: [-11, 0, 32],
    branches: [
      { id: "skill:web-research", name: "Web Research", leaves: ["Type: retrieval", "Sources: 12 APIs", "Avg latency: 3.2s"], links: [{ id: "tool:web-search", why: "Uses web search tool for information gathering" }, { id: "tool:scraper", why: "Uses scraper tool to extract structured data" }] },
      { id: "skill:analysis", name: "Financial Analysis", leaves: ["Type: reasoning", "Metrics: 24 standard", "Confidence scoring"], links: [{ id: "agent:research", why: "Used by research agent for investment signals" }, { id: "agent:analyst", why: "Core capability of analyst agent" }] },
      { id: "skill:report-gen", name: "Report Generation", leaves: ["Type: generation", "Formats: memo/deck/brief", "Templates: 8"], links: [{ id: "tool:doc-writer", why: "Uses document writer tool for output" }, { id: "bp:prompt-design", why: "Follows prompt design best practices" }] },
      { id: "skill:alerting", name: "Alerting", leaves: ["Type: monitoring", "Channels: Slack/email", "Rules: configurable"], links: [{ id: "tool:notifier", why: "Uses notifier tool to deliver alerts" }] },
    ],
  },
  {
    id: "tools",
    label: "TOOL TREE",
    subtitle: "Tools",
    type: "system",
    pos: [11, 0, 32],
    branches: [
      { id: "tool:web-search", name: "Web Search", leaves: ["API: Brave/Google", "Rate: 100/min", "Cache: 1hr"], links: [{ id: "comp:api-gateway", why: "All external calls routed through API gateway" }] },
      { id: "tool:scraper", name: "Web Scraper", leaves: ["Engine: Playwright", "Formats: HTML/PDF", "Anti-bot: rotating proxies"], links: [{ id: "comp:api-gateway", why: "Scraper requests pass through API gateway" }] },
      { id: "tool:doc-writer", name: "Document Writer", leaves: ["Formats: PDF/DOCX/MD", "Templates: Jinja2", "Versioned"], links: [{ id: "bp:prompt-design", why: "Document templates follow prompt design guidelines" }] },
      { id: "tool:notifier", name: "Notifier", leaves: ["Channels: Slack/Email/Webhook", "Priority levels: 3", "Delivery: guaranteed"], links: [{ id: "comp:scheduler", why: "Scheduler can trigger notifications" }] },
      { id: "tool:db-connector", name: "DB Connector", leaves: ["Protocols: REST/GraphQL/SQL", "Auth: service accounts", "Pooled connections"], links: [{ id: "comp:knowledge-store", why: "Reads/writes to knowledge store" }] },
    ],
  },
  {
    id: "flows",
    label: "FLOW TREE",
    subtitle: "Flows",
    type: "system",
    pos: [25, 0, 25],
    branches: [
      { id: "flow:sector-scan", name: "Sector Scan Flow", leaves: ["Steps: 5", "Avg duration: 4m", "Parallel: yes"], links: [{ id: "agent:research", why: "Research agent executes the scanning step" }, { id: "skill:web-research", why: "Web research skill used in data gathering step" }] },
      { id: "flow:dd-flow", name: "Due Diligence Flow", leaves: ["Steps: 8", "Avg duration: 12m", "Sequential"], links: [{ id: "agent:analyst", why: "Analyst agent performs financial analysis step" }, { id: "skill:analysis", why: "Financial analysis skill used in evaluation step" }, { id: "skill:report-gen", why: "Report generation skill produces final memo" }] },
      { id: "flow:network-map", name: "Network Mapping Flow", leaves: ["Steps: 4", "Avg duration: 6m", "Graph-based"], links: [{ id: "agent:connector", why: "Connector agent maps the network" }] },
      { id: "flow:alert-pipeline", name: "Alert Pipeline Flow", leaves: ["Steps: 3", "Trigger: event-driven", "Real-time"], links: [{ id: "agent:monitor", why: "Monitor agent evaluates alert conditions" }, { id: "skill:alerting", why: "Alerting skill delivers notifications" }, { id: "comp:scheduler", why: "Scheduler triggers periodic alert checks" }] },
    ],
  },
  {
    id: "trees_meta",
    label: "TREES TREE",
    subtitle: "Trees (Meta)",
    type: "system",
    pos: [32, 0, -7],
    branches: [
      { id: "meta:domain-trees", name: "Domain Trees", leaves: ["Count: 5", "Types: entity", "Purpose: business knowledge"], links: [{ id: "meta:system-trees", why: "System trees process and enrich domain tree data" }, { id: "arch:data-layer", why: "Domain trees are the data layer's primary content" }] },
      { id: "meta:system-trees", name: "System Trees", leaves: ["Count: 8", "Types: system", "Purpose: platform capabilities"], links: [{ id: "arch:service-mesh", why: "System trees map to service mesh components" }] },
    ],
  },
  {
    id: "best_practices",
    label: "BEST PRACTICES TREE",
    subtitle: "Best Practices",
    type: "system",
    pos: [-32, 0, 0],
    branches: [
      { id: "bp:prompt-design", name: "Prompt Design", leaves: ["Chain-of-thought", "Few-shot examples", "Structured output"], links: [{ id: "agent:research", why: "Research agent prompts follow these guidelines" }, { id: "agent:analyst", why: "Analyst agent prompts follow these guidelines" }, { id: "skill:report-gen", why: "Report generation uses structured output patterns" }] },
      { id: "bp:data-quality", name: "Data Quality", leaves: ["Dedup before ingest", "Source provenance", "Confidence scoring"], links: [{ id: "comp:knowledge-store", why: "Knowledge store enforces provenance tracking" }] },
      { id: "bp:cost-control", name: "Cost Control", leaves: ["Token budgets per run", "Model tiering", "Cache aggressively"], links: [{ id: "agent:monitor", why: "Monitor uses cheaper Haiku model for cost control" }, { id: "comp:api-gateway", why: "API gateway enforces rate limits and quotas" }] },
      { id: "bp:security", name: "Security Practices", leaves: ["Least privilege", "Audit logging", "Data encryption at rest"], links: [{ id: "reg:gdpr", why: "Security practices ensure GDPR compliance" }, { id: "comp:api-gateway", why: "API gateway handles auth and access control" }] },
    ],
  },
  {
    id: "architecture",
    label: "ARCHITECTURE TREE",
    subtitle: "Architecture",
    type: "system",
    pos: [29, 0, 11],
    branches: [
      { id: "arch:event-bus", name: "Event Bus", leaves: ["Pattern: pub/sub", "Backend: Redis Streams", "Async-first"], links: [{ id: "comp:orchestrator", why: "Orchestrator publishes and subscribes to events" }, { id: "comp:scheduler", why: "Scheduler emits timer events on the bus" }, { id: "arch:service-mesh", why: "Event bus is the backbone of the service mesh" }] },
      { id: "arch:data-layer", name: "Data Layer", leaves: ["Pattern: CQRS", "Read: vector search", "Write: append-only log"], links: [{ id: "comp:knowledge-store", why: "Knowledge store is the primary data layer component" }, { id: "tool:db-connector", why: "DB connector provides data layer access to agents" }] },
      { id: "arch:service-mesh", name: "Service Mesh", leaves: ["Pattern: sidecar proxy", "Discovery: consul", "Tracing: OpenTelemetry"], links: [{ id: "comp:api-gateway", why: "API gateway is the mesh ingress point" }, { id: "comp:orchestrator", why: "Orchestrator is a core mesh service" }] },
      { id: "arch:agent-framework", name: "Agent Framework", leaves: ["Pattern: ReAct loop", "Memory: episodic + semantic", "Tool use: structured"], links: [{ id: "agent:research", why: "Research agent built on this framework" }, { id: "agent:analyst", why: "Analyst agent built on this framework" }, { id: "bp:prompt-design", why: "Framework enforces prompt design best practices" }] },
    ],
  },
];

// Flat lookup: branchId → { tree, branch }
export const BRANCH_INDEX = {};
TREES.forEach((t) => t.branches.forEach((b) => { BRANCH_INDEX[b.id] = { tree: t, branch: b }; }));

// Houses — static data tables that sit on the forest floor
export const HOUSES = [
  {
    id: "house:exec-logs",
    name: "Execution Logs",
    description: "Records of every agent and flow run — status, duration, cost, inputs/outputs.",
    fields: ["run_id", "agent_id", "flow_id", "status", "duration_ms", "cost_usd", "started_at", "finished_at"],
    records: "48.2K",
    pos: [-20, 0, 20],
    relatedTrees: ["agents", "flows", "components"],
  },
  {
    id: "house:prompt-lib",
    name: "Prompt Library",
    description: "Versioned prompt templates, system prompts, and few-shot example sets.",
    fields: ["prompt_id", "version", "agent_type", "template", "examples", "created_by", "updated_at"],
    records: "312",
    pos: [-18, 0, 13],
    relatedTrees: ["agents", "skills", "best_practices"],
  },
  {
    id: "house:tool-registry",
    name: "Tool Registry",
    description: "API keys, endpoint configs, rate limits, and health status for each tool.",
    fields: ["tool_id", "endpoint", "api_key_ref", "rate_limit", "timeout_ms", "health", "last_checked"],
    records: "47",
    pos: [18, 0, 20],
    relatedTrees: ["tools", "components", "architecture"],
  },
  {
    id: "house:permissions",
    name: "Permissions",
    description: "RBAC roles, scopes, and access policies governing agents and human users.",
    fields: ["role_id", "principal", "resource", "action", "scope", "granted_by", "expires_at"],
    records: "1.4K",
    pos: [-28, 0, 6],
    relatedTrees: ["agents", "components", "best_practices"],
  },
  {
    id: "house:env-vars",
    name: "Env Variables",
    description: "Runtime configuration — API endpoints, feature flags, secrets references.",
    fields: ["key", "value_ref", "env", "is_secret", "source", "last_rotated"],
    records: "186",
    pos: [28, 0, 6],
    relatedTrees: ["components", "architecture", "tools"],
  },
  {
    id: "house:audit-trail",
    name: "Audit Trail",
    description: "Immutable log of who did what, when, and why — compliance and debugging.",
    fields: ["event_id", "actor", "action", "resource", "timestamp", "reason", "ip_address"],
    records: "2.1M",
    pos: [0, 0, 28],
    relatedTrees: ["best_practices", "components", "flows"],
  },
];

// Flat lookup: houseId → house
export const HOUSE_INDEX = {};
HOUSES.forEach((h) => { HOUSE_INDEX[h.id] = h; });

// Database store — mock relational tables representing the forest as a DB
export const DB_TABLES = {
  id: "db:forest",
  name: "Knowledge Forest DB",
  pos: [0, 0, 8],
  relatedTrees: ["sectors", "companies", "people"],
  tables: [
    {
      name: "trees",
      columns: ["id", "label", "subtitle", "type"],
      rows: [
        { id: "sectors", label: "SECTOR TREE", subtitle: "Sectors", type: "entity" },
        { id: "companies", label: "COMPANY TREE", subtitle: "Companies", type: "entity" },
        { id: "people", label: "PEOPLE TREE", subtitle: "People", type: "entity" },
        { id: "geographies", label: "GEOGRAPHY TREE", subtitle: "Geographies", type: "entity" },
        { id: "regulation", label: "REGULATION TREE", subtitle: "Regulation", type: "entity" },
        { id: "agents", label: "AGENT TREE", subtitle: "Agents", type: "system" },
        { id: "tools", label: "TOOL TREE", subtitle: "Tools", type: "system" },
        { id: "flows", label: "FLOW TREE", subtitle: "Flows", type: "system" },
      ],
    },
    {
      name: "branches",
      columns: ["id", "tree_id", "name"],
      rows: [
        { id: "sector:cyber", tree_id: "sectors", name: "Cybersecurity" },
        { id: "sector:fintech", tree_id: "sectors", name: "Fintech" },
        { id: "sector:ai-infra", tree_id: "sectors", name: "AI Infrastructure" },
        { id: "company:crowdstrike", tree_id: "companies", name: "CrowdStrike" },
        { id: "company:stripe", tree_id: "companies", name: "Stripe" },
        { id: "company:nvidia", tree_id: "companies", name: "NVIDIA" },
        { id: "person:kurtz", tree_id: "people", name: "George Kurtz" },
        { id: "person:huang", tree_id: "people", name: "Jensen Huang" },
        { id: "agent:research", tree_id: "agents", name: "Research Agent" },
        { id: "flow:sector-scan", tree_id: "flows", name: "Sector Scan Flow" },
      ],
    },
    {
      name: "leaves",
      columns: ["id", "branch_id", "value"],
      rows: [
        { id: 1, branch_id: "sector:cyber", value: "Market: $180B" },
        { id: 2, branch_id: "sector:cyber", value: "CAGR: 12%" },
        { id: 3, branch_id: "sector:fintech", value: "Market: $310B" },
        { id: 4, branch_id: "company:crowdstrike", value: "Rev: $3.06B" },
        { id: 5, branch_id: "company:crowdstrike", value: "PE: 7.8" },
        { id: 6, branch_id: "company:nvidia", value: "Rev: $60B" },
        { id: 7, branch_id: "person:kurtz", value: "CEO CrowdStrike" },
        { id: 8, branch_id: "person:huang", value: "CEO NVIDIA" },
        { id: 9, branch_id: "agent:research", value: "Model: Claude" },
        { id: 10, branch_id: "flow:sector-scan", value: "Steps: 5" },
      ],
    },
    {
      name: "links",
      columns: ["source_id", "target_id", "why"],
      rows: [
        { source_id: "company:crowdstrike", target_id: "sector:cyber", why: "Primary sector" },
        { source_id: "company:stripe", target_id: "sector:fintech", why: "Payments infrastructure" },
        { source_id: "company:nvidia", target_id: "sector:ai-infra", why: "GPU supplier for AI" },
        { source_id: "person:kurtz", target_id: "company:crowdstrike", why: "Founder & CEO" },
        { source_id: "person:huang", target_id: "company:nvidia", why: "Co-founder & CEO" },
        { source_id: "agent:research", target_id: "flow:sector-scan", why: "Executes scanning" },
        { source_id: "sector:cyber", target_id: "sector:ai-infra", why: "AI powers detection" },
        { source_id: "company:crowdstrike", target_id: "company:nvidia", why: "Uses NVIDIA GPUs" },
      ],
    },
    {
      name: "houses",
      columns: ["id", "name", "records", "related_trees"],
      rows: [
        { id: "house:exec-logs", name: "Execution Logs", records: "48.2K", related_trees: "agents, flows, components" },
        { id: "house:prompt-lib", name: "Prompt Library", records: "312", related_trees: "agents, skills, best_practices" },
        { id: "house:tool-registry", name: "Tool Registry", records: "47", related_trees: "tools, components, architecture" },
        { id: "house:permissions", name: "Permissions", records: "1.4K", related_trees: "agents, components, best_practices" },
        { id: "house:env-vars", name: "Env Variables", records: "186", related_trees: "components, architecture, tools" },
        { id: "house:audit-trail", name: "Audit Trail", records: "2.1M", related_trees: "best_practices, components, flows" },
      ],
    },
  ],
};

// Geometry constants
export const SCALE = 1.0;
export const NODE_R = 0.18;
export const BRANCH_R = 0.13;
export const LEAF_R = 0.075;
export const TRUNK_H = 2.0;
export const BRANCH_LEN = 2.2;

export function vec3(arr) {
  return new THREE.Vector3(arr[0] * SCALE, arr[1] * SCALE, arr[2] * SCALE);
}
