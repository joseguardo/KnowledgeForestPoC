/**
 * Self-contained synthetic knowledge base for the Forest Creation demo
 * (Nzyme — regulatory intelligence tenant).
 *
 * Deliberately larger than the live-app dataset (src/data/trees.js, which
 * stays untouched): ~115 pointers, ~200 edges, 15 query themes.
 *
 * The themes are authored so that co-access clustering converges to a
 * meaningful forest: each core theme has 2-4 node-disjoint "spines" — each
 * spine becomes one branch — and low-volume cross-pollination themes supply
 * the sub-threshold affinity that merges branches into trees.
 */

// ─── Tuning ─────────────────────────────────────────────────────
export const DEMO_TUNING = {
  THRESHOLD: 4.0, // co-access weight needed to fuse two pointers into a branch
  MAX_TREES: 10,
  MIN_BRANCH_SIZE: 2,
  // Multi-cluster membership: total affinity from a card to ANOTHER branch's
  // members needed for the card to also join that cluster (ghost instance)
  SECONDARY_THRESHOLD: 4.0,
  MAX_SECONDARY: 2,
  SEED: 42,
};

// ─── Pointers ───────────────────────────────────────────────────

const SECTORS = [
  { id: "sector:cyber",      label: "Cybersecurity",     leaves: ["Market: $180B", "CAGR: 12%"] },
  { id: "sector:fintech",    label: "Fintech",           leaves: ["Market: $310B", "CAGR: 9%"] },
  { id: "sector:biotech",    label: "Biotech",           leaves: ["Market: $497B", "CAGR: 14%"] },
  { id: "sector:consumer",   label: "Consumer Tech",     leaves: ["Market: $1.2T", "CAGR: 6%"] },
  { id: "sector:ai-infra",   label: "AI Infrastructure", leaves: ["Market: $82B", "CAGR: 38%"] },
  { id: "sector:regtech",    label: "RegTech",           leaves: ["Market: $16B", "CAGR: 21%"] },
  { id: "sector:healthtech", label: "HealthTech",        leaves: ["Market: $260B", "CAGR: 17%"] },
  { id: "sector:defense",    label: "Defense Tech",      leaves: ["Market: $48B", "CAGR: 24%"] },
  { id: "sector:climate",    label: "Climate Tech",      leaves: ["Market: $60B", "CAGR: 26%"] },
  { id: "sector:devtools",   label: "DevTools",          leaves: ["Market: $28B", "CAGR: 19%"] },
];

const COMPANIES = [
  { id: "company:crowdstrike", label: "CrowdStrike",  leaves: ["Rev: $3.06B", "HQ: Austin"] },
  { id: "company:wiz",         label: "Wiz",          leaves: ["Rev: $500M", "HQ: NYC"] },
  { id: "company:darktrace",   label: "Darktrace",    leaves: ["Rev: £545M", "HQ: Cambridge"] },
  { id: "company:snyk",        label: "Snyk",         leaves: ["Rev: $300M", "HQ: Boston/London"] },
  { id: "company:apple",       label: "Apple",        leaves: ["Rev: $383B", "HQ: Cupertino"] },
  { id: "company:stripe",      label: "Stripe",       leaves: ["Rev: $14.4B", "HQ: SF/Dublin"] },
  { id: "company:nvidia",      label: "NVIDIA",       leaves: ["Rev: $60B", "HQ: Santa Clara"] },
  { id: "company:openai",      label: "OpenAI",       leaves: ["Rev: $3.7B", "HQ: SF"] },
  { id: "company:anthropic",   label: "Anthropic",    leaves: ["Rev: $1B+", "HQ: SF"] },
  { id: "company:databricks",  label: "Databricks",   leaves: ["Rev: $2.4B", "HQ: SF"] },
  { id: "company:palantir",    label: "Palantir",     leaves: ["Rev: $2.9B", "HQ: Denver"] },
  { id: "company:mistral",     label: "Mistral AI",   leaves: ["Raised: €1B+", "HQ: Paris"] },
  { id: "company:aleph-alpha", label: "Aleph Alpha",  leaves: ["Raised: €500M", "HQ: Heidelberg"] },
  { id: "company:deepl",       label: "DeepL",        leaves: ["Val: $2B", "HQ: Cologne"] },
  { id: "company:helsing",     label: "Helsing",      leaves: ["Val: €5B", "HQ: Munich"] },
  { id: "company:moderna",     label: "Moderna",      leaves: ["Rev: $6.8B", "HQ: Cambridge MA"] },
  { id: "company:biontech",    label: "BioNTech",     leaves: ["Rev: €3.8B", "HQ: Mainz"] },
  { id: "company:tempus",      label: "Tempus",       leaves: ["Rev: $700M", "HQ: Chicago"] },
  { id: "company:northvolt",   label: "Northvolt",    leaves: ["Raised: $15B", "HQ: Stockholm"] },
  { id: "company:factorial",   label: "Factorial",    leaves: ["Rev: €80M", "HQ: Barcelona"] },
  { id: "company:typeform",    label: "Typeform",     leaves: ["Rev: $100M", "HQ: Barcelona"] },
  { id: "company:travelperk",  label: "TravelPerk",   leaves: ["Rev: $150M", "HQ: Barcelona"] },
  { id: "company:cabify",      label: "Cabify",       leaves: ["Rev: €700M", "HQ: Madrid"] },
  { id: "company:glovo",       label: "Glovo",        leaves: ["GMV: €3.5B", "HQ: Barcelona"] },
  { id: "company:jobandtalent",label: "Jobandtalent", leaves: ["Rev: €200M", "HQ: Madrid"] },
  { id: "company:seedtag",     label: "Seedtag",      leaves: ["Rev: €100M", "HQ: Madrid"] },
  { id: "company:clarity-ai",  label: "Clarity AI",   leaves: ["Rev: €30M", "HQ: Madrid"] },
  { id: "company:nubank",      label: "Nubank",       leaves: ["Rev: $8B", "HQ: São Paulo"] },
  { id: "company:rappi",       label: "Rappi",        leaves: ["GMV: $5B", "HQ: Bogotá"] },
  { id: "company:clip",        label: "Clip",         leaves: ["Val: $2B", "HQ: Mexico City"] },
  { id: "company:kavak",       label: "Kavak",        leaves: ["Val: $4B", "HQ: Mexico City"] },
];

const PEOPLE = [
  { id: "person:kurtz",     label: "George Kurtz",     leaves: ["CEO CrowdStrike"] },
  { id: "person:cook",      label: "Tim Cook",         leaves: ["CEO Apple"] },
  { id: "person:collison",  label: "Patrick Collison", leaves: ["CEO Stripe"] },
  { id: "person:huang",     label: "Jensen Huang",     leaves: ["CEO NVIDIA"] },
  { id: "person:altman",    label: "Sam Altman",       leaves: ["CEO OpenAI"] },
  { id: "person:amodei",    label: "Dario Amodei",     leaves: ["CEO Anthropic"] },
  { id: "person:ghodsi",    label: "Ali Ghodsi",       leaves: ["CEO Databricks"] },
  { id: "person:karp",      label: "Alex Karp",        leaves: ["CEO Palantir"] },
  { id: "person:mensch",    label: "Arthur Mensch",    leaves: ["CEO Mistral AI"] },
  { id: "person:sahin",     label: "Uğur Şahin",       leaves: ["CEO BioNTech"] },
  { id: "person:deantonio", label: "Juan de Antonio",  leaves: ["CEO Cabify"] },
  { id: "person:minguela",  label: "Rebeca Minguela",  leaves: ["CEO Clarity AI"] },
  { id: "person:velez",     label: "David Vélez",      leaves: ["CEO Nubank"] },
];

const GEOS = [
  { id: "geo:europe",  label: "Europe",        leaves: ["GDP: $18.3T", "VC: €52B"] },
  { id: "geo:spain",   label: "Spain",         leaves: ["GDP: $1.4T", "VC: €2.1B"] },
  { id: "geo:germany", label: "Germany",       leaves: ["GDP: $4.4T", "VC: €8.2B"] },
  { id: "geo:france",  label: "France",        leaves: ["GDP: $3.0T", "VC: €8.5B"] },
  { id: "geo:uk",      label: "United Kingdom",leaves: ["GDP: $3.3T", "VC: £18B"] },
  { id: "geo:nordics", label: "Nordics",       leaves: ["GDP: $1.9T", "VC: €6B"] },
  { id: "geo:israel",  label: "Israel",        leaves: ["GDP: $520B", "VC: $8B"] },
  { id: "geo:us",      label: "United States", leaves: ["GDP: $27T", "VC: $170B"] },
  { id: "geo:latam",   label: "Latin America", leaves: ["GDP: $5.7T", "VC: $4.2B"] },
];

const REGULATIONS = [
  { id: "reg:gdpr",      label: "GDPR",      leaves: ["EU data protection", "Since 2018"] },
  { id: "reg:eu-ai-act", label: "EU AI Act", leaves: ["AI risk tiers", "Phased 2025-27"] },
  { id: "reg:dora",      label: "DORA",      leaves: ["Financial ops resilience", "Live 2025"] },
  { id: "reg:nis2",      label: "NIS2",      leaves: ["Critical infra security", "Live 2024"] },
  { id: "reg:dsa",       label: "DSA",       leaves: ["Platform content rules", "Live 2024"] },
  { id: "reg:dma",       label: "DMA",       leaves: ["Gatekeeper rules", "Live 2024"] },
  { id: "reg:mifid",     label: "MiFID II",  leaves: ["EU markets", "Since 2018"] },
  { id: "reg:basel",     label: "Basel III", leaves: ["Bank capital", "Phased"] },
  { id: "reg:psd2",      label: "PSD2",      leaves: ["Open banking", "Since 2019"] },
  { id: "reg:sec",       label: "SEC Rules", leaves: ["US securities", "Reg D / S"] },
  { id: "reg:ccpa",      label: "CCPA",      leaves: ["California privacy", "Since 2020"] },
  { id: "reg:hipaa",     label: "HIPAA",     leaves: ["US health data", "Since 1996"] },
  { id: "reg:mdr",       label: "EU MDR",    leaves: ["Medical devices", "Since 2021"] },
];

const SYSTEM = [
  // components
  { id: "comp:orchestrator",    label: "Orchestrator",    type: "component", leaves: ["Core runtime", "Node.js"] },
  { id: "comp:knowledge-store", label: "Knowledge Store", type: "component", leaves: ["Vector DB", "Forest state"] },
  { id: "comp:api-gateway",     label: "API Gateway",     type: "component", leaves: ["OAuth2", "Rate limited"] },
  { id: "comp:scheduler",       label: "Scheduler",       type: "component", leaves: ["Cron + events"] },
  { id: "comp:vector-index",    label: "Vector Index",    type: "component", leaves: ["HNSW", "1536-dim"] },
  { id: "comp:citation-store",  label: "Citation Store",  type: "component", leaves: ["Source provenance"] },
  // agents
  { id: "agent:research",   label: "Research Agent",   type: "agent", leaves: ["Model: Claude", "Autonomy: high"] },
  { id: "agent:analyst",    label: "Analyst Agent",    type: "agent", leaves: ["Model: Claude", "Autonomy: med"] },
  { id: "agent:monitor",    label: "Monitor Agent",    type: "agent", leaves: ["Model: Haiku", "Always-on"] },
  { id: "agent:connector",  label: "Connector Agent",  type: "agent", leaves: ["Network mapping"] },
  { id: "agent:compliance", label: "Compliance Agent", type: "agent", leaves: ["Obligation mapping"] },
  { id: "agent:horizon",    label: "Horizon Scanner",  type: "agent", leaves: ["Reg pipeline watch"] },
  // skills
  { id: "skill:web-research",      label: "Web Research",        type: "skill", leaves: ["12 APIs", "3.2s avg"] },
  { id: "skill:analysis",          label: "Financial Analysis",  type: "skill", leaves: ["24 metrics"] },
  { id: "skill:report-gen",        label: "Report Generation",   type: "skill", leaves: ["8 templates"] },
  { id: "skill:alerting",          label: "Alerting",            type: "skill", leaves: ["Slack/email"] },
  { id: "skill:entity-extraction", label: "Entity Extraction",   type: "skill", leaves: ["NER + linking"] },
  { id: "skill:summarization",     label: "Summarization",       type: "skill", leaves: ["Map-reduce"] },
  // tools
  { id: "tool:web-search",   label: "Web Search",      type: "tool", leaves: ["100/min", "1hr cache"] },
  { id: "tool:scraper",      label: "Web Scraper",     type: "tool", leaves: ["Playwright"] },
  { id: "tool:doc-writer",   label: "Document Writer", type: "tool", leaves: ["PDF/DOCX/MD"] },
  { id: "tool:notifier",     label: "Notifier",        type: "tool", leaves: ["3 channels"] },
  { id: "tool:db-connector", label: "DB Connector",    type: "tool", leaves: ["REST/SQL"] },
  { id: "tool:pdf-parser",   label: "PDF Parser",      type: "tool", leaves: ["OCR + layout"] },
  { id: "tool:translator",   label: "Translator",      type: "tool", leaves: ["31 languages"] },
  // flows
  { id: "flow:sector-scan",    label: "Sector Scan",     type: "flow", leaves: ["5 steps", "4m avg"] },
  { id: "flow:dd-flow",        label: "Due Diligence",   type: "flow", leaves: ["8 steps", "12m avg"] },
  { id: "flow:network-map",    label: "Network Mapping", type: "flow", leaves: ["4 steps"] },
  { id: "flow:alert-pipeline", label: "Alert Pipeline",  type: "flow", leaves: ["Real-time"] },
  { id: "flow:reg-watch",      label: "Reg Watch",       type: "flow", leaves: ["Nightly", "14 sources"] },
  { id: "flow:client-report",  label: "Client Report",   type: "flow", leaves: ["Weekly digest"] },
  // best practices + architecture + meta
  { id: "bp:prompt-design", label: "Prompt Design",      type: "best_practice", leaves: ["CoT", "Few-shot"] },
  { id: "bp:data-quality",  label: "Data Quality",       type: "best_practice", leaves: ["Dedup", "Provenance"] },
  { id: "bp:cost-control",  label: "Cost Control",       type: "best_practice", leaves: ["Token budgets"] },
  { id: "bp:security",      label: "Security Practices", type: "best_practice", leaves: ["Least privilege"] },
  { id: "arch:event-bus",       label: "Event Bus",       type: "architecture", leaves: ["Pub/sub", "Redis"] },
  { id: "arch:data-layer",      label: "Data Layer",      type: "architecture", leaves: ["CQRS"] },
  { id: "arch:service-mesh",    label: "Service Mesh",    type: "architecture", leaves: ["Sidecar proxy"] },
  { id: "arch:agent-framework", label: "Agent Framework", type: "architecture", leaves: ["ReAct loop"] },
  { id: "meta:domain-trees", label: "Domain Trees", type: "meta", leaves: ["Entity knowledge"] },
  { id: "meta:system-trees", label: "System Trees", type: "meta", leaves: ["Platform knowledge"] },
];

function withType(arr, type) {
  return arr.map((p) => ({ ...p, type }));
}

export const DEMO_POINTERS = [
  ...withType(SECTORS, "sector"),
  ...withType(COMPANIES, "company"),
  ...withType(PEOPLE, "person"),
  ...withType(GEOS, "geography"),
  ...withType(REGULATIONS, "regulation"),
  ...SYSTEM,
];

// ─── Edges (knowledge-graph links; feed query detours + flavor) ─

const E = (source, target, why) => ({ source, target, why });

export const DEMO_EDGES = [
  // European AI regulation neighborhood
  E("reg:eu-ai-act", "geo:europe", "First comprehensive AI regulation globally"),
  E("reg:eu-ai-act", "reg:gdpr", "Builds on GDPR's risk-based enforcement model"),
  E("reg:gdpr", "geo:europe", "Applies across all EU/EEA member states"),
  E("company:mistral", "geo:france", "HQ Paris — France's AI champion"),
  E("person:mensch", "company:mistral", "Co-founder & CEO"),
  E("company:mistral", "reg:eu-ai-act", "GPAI model provider obligations"),
  E("company:aleph-alpha", "geo:germany", "HQ Heidelberg"),
  E("company:deepl", "geo:germany", "HQ Cologne"),
  E("company:aleph-alpha", "reg:eu-ai-act", "Sovereign-AI positioning shaped by the Act"),
  E("company:deepl", "company:aleph-alpha", "German AI ecosystem peers"),
  E("geo:france", "geo:europe", "EU member state"),
  E("geo:germany", "geo:europe", "EU member state"),

  // Cyber resilience neighborhood
  E("reg:dora", "sector:cyber", "Operational resilience for financial entities"),
  E("reg:nis2", "sector:cyber", "Critical-infrastructure security directive"),
  E("reg:dora", "reg:nis2", "Overlapping EU cyber resilience regimes"),
  E("reg:nis2", "geo:europe", "EU-wide directive"),
  E("company:crowdstrike", "sector:cyber", "Endpoint security market leader"),
  E("person:kurtz", "company:crowdstrike", "Founder & CEO since 2011"),
  E("company:wiz", "sector:cyber", "Cloud-native security platform"),
  E("company:crowdstrike", "company:wiz", "Compete for enterprise CISO budgets"),
  E("company:darktrace", "geo:uk", "HQ Cambridge"),
  E("company:snyk", "geo:uk", "Major London engineering hub"),
  E("company:darktrace", "sector:cyber", "AI-driven network detection"),
  E("company:snyk", "sector:devtools", "Developer-first security tooling"),
  E("bp:security", "reg:gdpr", "Security practices ensure GDPR compliance"),
  E("bp:security", "reg:nis2", "NIS2 mandates these baseline controls"),
  E("bp:security", "comp:api-gateway", "Gateway enforces auth and access control"),

  // Spanish tech neighborhood
  E("company:factorial", "geo:spain", "HQ Barcelona"),
  E("company:typeform", "geo:spain", "HQ Barcelona"),
  E("company:travelperk", "geo:spain", "HQ Barcelona"),
  E("company:factorial", "company:typeform", "Barcelona SaaS peers"),
  E("company:cabify", "geo:spain", "HQ Madrid"),
  E("company:glovo", "geo:spain", "HQ Barcelona"),
  E("person:deantonio", "company:cabify", "Founder & CEO"),
  E("company:cabify", "company:glovo", "Spanish mobility & delivery champions"),
  E("company:seedtag", "geo:spain", "HQ Madrid"),
  E("company:clarity-ai", "geo:spain", "HQ Madrid"),
  E("person:minguela", "company:clarity-ai", "Founder & CEO"),
  E("company:jobandtalent", "geo:spain", "HQ Madrid"),
  E("company:seedtag", "sector:ai-infra", "AI-native contextual advertising"),
  E("company:clarity-ai", "sector:ai-infra", "AI-powered sustainability analytics"),
  E("geo:spain", "geo:europe", "EU member state"),

  // LatAm fintech neighborhood
  E("company:nubank", "geo:latam", "Brazil's largest neobank"),
  E("person:velez", "company:nubank", "Founder & CEO"),
  E("company:rappi", "geo:latam", "Colombian super-app"),
  E("company:clip", "geo:latam", "Mexican payments terminal leader"),
  E("company:kavak", "geo:latam", "Mexican used-car marketplace"),
  E("company:rappi", "company:clip", "LatAm payments ecosystem"),
  E("company:nubank", "sector:fintech", "Neobanking at continental scale"),
  E("company:stripe", "sector:fintech", "Payments infrastructure"),
  E("person:collison", "company:stripe", "Co-founder & CEO"),
  E("reg:psd2", "sector:fintech", "Open-banking mandate"),
  E("reg:psd2", "geo:europe", "EU payments directive"),
  E("company:stripe", "reg:psd2", "SCA compliance in EU payments"),

  // Platform & markets regulation neighborhood
  E("reg:dsa", "geo:europe", "EU platform content rules"),
  E("reg:dma", "geo:europe", "EU gatekeeper competition rules"),
  E("reg:dsa", "reg:dma", "Twin EU platform regulations"),
  E("company:apple", "reg:dma", "Designated gatekeeper"),
  E("person:cook", "company:apple", "CEO since 2011"),
  E("company:apple", "sector:consumer", "Consumer hardware & services"),
  E("reg:mifid", "geo:europe", "EU financial markets directive"),
  E("reg:basel", "reg:mifid", "Complementary prudential regimes"),
  E("reg:sec", "geo:us", "US securities regulator"),
  E("reg:basel", "sector:fintech", "Capital rules ripple to fintech lenders"),
  E("reg:mifid", "sector:fintech", "Governs EU investment services"),

  // AI infrastructure neighborhood
  E("company:nvidia", "sector:ai-infra", "Dominant GPU supplier for AI training"),
  E("person:huang", "company:nvidia", "Co-founder & CEO since 1993"),
  E("company:openai", "sector:ai-infra", "Frontier model lab"),
  E("person:altman", "company:openai", "CEO"),
  E("company:anthropic", "sector:ai-infra", "Frontier model lab"),
  E("person:amodei", "company:anthropic", "Co-founder & CEO"),
  E("company:openai", "company:anthropic", "Frontier lab rivals"),
  E("company:databricks", "sector:devtools", "Data & AI platform"),
  E("person:ghodsi", "company:databricks", "Co-founder & CEO"),
  E("company:nvidia", "company:openai", "Compute supplier"),
  E("company:anthropic", "reg:eu-ai-act", "GPAI compliance scope"),
  E("company:databricks", "sector:ai-infra", "Lakehouse for AI workloads"),
  E("sector:ai-infra", "sector:cyber", "AI powers next-gen threat detection"),

  // Health data compliance neighborhood
  E("reg:hipaa", "sector:healthtech", "US health-data privacy baseline"),
  E("reg:mdr", "sector:healthtech", "EU medical device regulation"),
  E("reg:ccpa", "reg:hipaa", "Overlapping US privacy regimes"),
  E("reg:ccpa", "geo:us", "California privacy statute"),
  E("company:tempus", "sector:healthtech", "Precision-medicine data platform"),
  E("company:tempus", "reg:hipaa", "Clinical data compliance"),
  E("company:moderna", "sector:biotech", "mRNA therapeutics pioneer"),
  E("company:biontech", "sector:biotech", "mRNA pioneer"),
  E("person:sahin", "company:biontech", "Co-founder & CEO"),
  E("company:moderna", "company:biontech", "mRNA platform rivals"),
  E("company:biontech", "geo:germany", "HQ Mainz"),
  E("sector:healthtech", "sector:biotech", "Adjacent health value chain"),

  // Defense & frontier neighborhood
  E("company:helsing", "sector:defense", "European defense AI"),
  E("company:palantir", "sector:defense", "Government & defense analytics"),
  E("person:karp", "company:palantir", "Co-founder & CEO"),
  E("company:helsing", "geo:germany", "HQ Munich"),
  E("geo:israel", "sector:defense", "Defense tech powerhouse"),
  E("geo:israel", "sector:cyber", "Unit 8200 alumni ecosystem"),
  E("company:northvolt", "sector:climate", "European battery champion"),
  E("company:northvolt", "geo:nordics", "HQ Stockholm"),
  E("geo:nordics", "sector:climate", "Nordic climate-tech density"),
  E("company:helsing", "company:palantir", "Defense AI competitors"),

  // Regulatory monitoring neighborhood (system)
  E("flow:reg-watch", "agent:horizon", "Horizon scanner executes the watch flow"),
  E("agent:horizon", "sector:regtech", "Scans the regulatory horizon"),
  E("agent:compliance", "sector:regtech", "Maps obligations to controls"),
  E("agent:compliance", "flow:reg-watch", "Consumes watch-flow output"),
  E("flow:alert-pipeline", "agent:monitor", "Monitor evaluates alert conditions"),
  E("agent:monitor", "skill:alerting", "Triggers alerts on portfolio events"),
  E("skill:alerting", "tool:notifier", "Delivers via notifier"),
  E("comp:scheduler", "flow:alert-pipeline", "Triggers periodic checks"),
  E("comp:scheduler", "arch:event-bus", "Emits timer events on the bus"),
  E("flow:reg-watch", "comp:scheduler", "Runs on the nightly schedule"),
  E("agent:horizon", "reg:eu-ai-act", "Tracks implementation milestones"),

  // Research & reporting neighborhood (system)
  E("flow:sector-scan", "agent:research", "Research agent executes the scanning step"),
  E("agent:research", "skill:web-research", "Primary information-gathering skill"),
  E("skill:web-research", "tool:web-search", "Search APIs"),
  E("skill:web-research", "tool:scraper", "Structured extraction from pages"),
  E("flow:dd-flow", "agent:analyst", "Analyst performs the evaluation step"),
  E("agent:analyst", "skill:analysis", "Core financial-analysis capability"),
  E("agent:analyst", "skill:report-gen", "Generates memos and reports"),
  E("skill:report-gen", "tool:doc-writer", "Document output"),
  E("flow:client-report", "skill:summarization", "Summarizes findings for clients"),
  E("skill:summarization", "tool:translator", "Multi-language client delivery"),
  E("flow:client-report", "agent:analyst", "Analyst compiles the digest"),
  E("flow:network-map", "agent:connector", "Connector agent maps the network"),
  E("agent:connector", "skill:web-research", "Researches network connections"),
  E("flow:dd-flow", "skill:analysis", "Evaluation step"),

  // Knowledge platform neighborhood (system)
  E("comp:knowledge-store", "arch:data-layer", "Primary data-layer component"),
  E("arch:data-layer", "tool:db-connector", "Data-layer access for agents"),
  E("bp:data-quality", "comp:knowledge-store", "Store enforces provenance tracking"),
  E("comp:vector-index", "comp:knowledge-store", "Embedding index over the store"),
  E("comp:citation-store", "comp:knowledge-store", "Provenance for every fact"),
  E("skill:entity-extraction", "comp:vector-index", "Extracted entities are embedded"),
  E("tool:pdf-parser", "skill:entity-extraction", "Parses filings for extraction"),
  E("comp:orchestrator", "arch:agent-framework", "Runs framework agents"),
  E("comp:orchestrator", "arch:event-bus", "Publishes and subscribes to events"),
  E("arch:service-mesh", "comp:api-gateway", "Gateway is the mesh ingress"),
  E("arch:service-mesh", "comp:orchestrator", "Core mesh service"),
  E("arch:agent-framework", "agent:research", "Built on this framework"),
  E("arch:agent-framework", "agent:analyst", "Built on this framework"),
  E("bp:prompt-design", "agent:research", "Prompts follow these guidelines"),
  E("bp:prompt-design", "skill:report-gen", "Structured output patterns"),
  E("bp:cost-control", "agent:monitor", "Cheaper model tier for always-on work"),
  E("bp:cost-control", "comp:api-gateway", "Rate limits and quotas"),
  E("meta:domain-trees", "meta:system-trees", "System trees enrich domain data"),
  E("meta:domain-trees", "arch:data-layer", "Domain trees are the data layer's content"),

  // Cross-tree flavor
  E("reg:gdpr", "sector:cyber", "Drives demand for data-protection tooling"),
  E("reg:eu-ai-act", "sector:ai-infra", "Directly regulates model providers"),
  E("company:nvidia", "company:crowdstrike", "GPUs for AI-driven threat detection"),
  E("geo:us", "company:stripe", "HQ San Francisco"),
  E("geo:us", "company:nvidia", "HQ Santa Clara"),
  E("sector:fintech", "sector:consumer", "Payments serve consumer markets"),
  E("agent:research", "reg:eu-ai-act", "Agents must meet transparency duties"),
  E("tool:web-search", "comp:api-gateway", "External calls routed via gateway"),
  E("tool:notifier", "comp:scheduler", "Scheduler can trigger notifications"),
  E("tool:db-connector", "comp:knowledge-store", "Reads/writes forest state"),
];

// ─── Query themes ───────────────────────────────────────────────
// Core themes: each spine is node-disjoint from the theme's other spines —
// every spine is an intended branch. Cross-pollination themes (low count)
// walk across branches to create the sub-threshold affinity that merges
// branches into trees.

export const DEMO_THEMES = [
  {
    id: "eu-ai-regulation",
    label: "European AI Regulation",
    color: "#4a90d9",
    count: 36,
    spines: [
      ["reg:eu-ai-act", "geo:europe", "reg:gdpr"],
      ["company:mistral", "person:mensch", "geo:france"],
      ["company:aleph-alpha", "company:deepl", "geo:germany"],
    ],
  },
  {
    id: "cyber-resilience",
    label: "Cyber Resilience (DORA / NIS2)",
    color: "#e04040",
    count: 36,
    spines: [
      ["reg:dora", "reg:nis2", "sector:cyber"],
      ["company:crowdstrike", "person:kurtz", "company:wiz"],
      ["company:darktrace", "company:snyk", "geo:uk", "bp:security"],
    ],
  },
  {
    id: "spanish-tech",
    label: "Spanish Tech Hub",
    color: "#e8a838",
    count: 38,
    spines: [
      ["geo:spain", "company:factorial", "company:typeform", "company:travelperk"],
      ["company:cabify", "company:glovo", "person:deantonio"],
      ["company:seedtag", "company:clarity-ai", "person:minguela", "company:jobandtalent"],
    ],
  },
  {
    id: "latam-fintech",
    label: "LatAm Fintech",
    color: "#a0d040",
    count: 36,
    spines: [
      ["geo:latam", "company:nubank", "person:velez"],
      ["company:rappi", "company:clip", "company:kavak"],
      ["sector:fintech", "reg:psd2", "company:stripe", "person:collison"],
    ],
  },
  {
    id: "platform-regulation",
    label: "Platform & Markets Regulation",
    color: "#d94070",
    count: 30,
    spines: [
      ["reg:dsa", "reg:dma", "company:apple", "person:cook"],
      ["reg:mifid", "reg:basel", "reg:sec", "geo:us"],
    ],
  },
  {
    id: "ai-infrastructure",
    label: "AI Infrastructure",
    color: "#7b61ff",
    count: 38,
    spines: [
      ["company:nvidia", "person:huang", "sector:ai-infra"],
      ["company:openai", "person:altman", "company:anthropic", "person:amodei"],
      ["company:databricks", "person:ghodsi", "sector:devtools"],
    ],
  },
  {
    id: "health-compliance",
    label: "Health Data Compliance",
    color: "#40b0c0",
    count: 30,
    spines: [
      ["reg:hipaa", "reg:mdr", "sector:healthtech", "company:tempus", "reg:ccpa"],
      ["company:moderna", "company:biontech", "person:sahin", "sector:biotech"],
    ],
  },
  {
    id: "defense-frontier",
    label: "Defense & Frontier Tech",
    color: "#708090",
    count: 28,
    spines: [
      ["sector:defense", "company:helsing", "company:palantir", "person:karp", "geo:israel"],
      ["sector:climate", "geo:nordics", "company:northvolt"],
    ],
  },
  {
    id: "reg-monitoring",
    label: "Regulatory Monitoring",
    color: "#d4a017",
    count: 34,
    spines: [
      ["flow:reg-watch", "agent:horizon", "sector:regtech", "agent:compliance"],
      ["flow:alert-pipeline", "agent:monitor", "skill:alerting", "tool:notifier"],
      ["comp:scheduler", "arch:event-bus"],
    ],
  },
  {
    id: "research-reporting",
    label: "Research & Reporting",
    color: "#c080e0",
    count: 40,
    spines: [
      ["flow:sector-scan", "agent:research", "skill:web-research", "tool:web-search", "tool:scraper"],
      ["flow:dd-flow", "agent:analyst", "skill:analysis", "skill:report-gen", "tool:doc-writer"],
      ["flow:client-report", "skill:summarization", "tool:translator"],
      ["flow:network-map", "agent:connector"],
    ],
  },
  {
    id: "knowledge-platform",
    label: "Knowledge Platform",
    color: "#60a0c0",
    count: 38,
    spines: [
      ["comp:knowledge-store", "arch:data-layer", "tool:db-connector", "bp:data-quality"],
      ["comp:vector-index", "comp:citation-store", "skill:entity-extraction", "tool:pdf-parser"],
      ["comp:orchestrator", "arch:agent-framework", "arch:service-mesh", "comp:api-gateway"],
    ],
  },
  // Cross-pollination themes — low volume, bridge branches into trees
  {
    id: "eu-policy-synthesis",
    label: "EU Policy Synthesis",
    color: "#9090a0",
    count: 6,
    spines: [
      ["reg:eu-ai-act", "company:mistral", "company:aleph-alpha"],
      ["reg:dora", "company:crowdstrike", "company:darktrace"],
      ["reg:dsa", "reg:mifid", "geo:us"],
    ],
  },
  {
    id: "portfolio-scan",
    label: "Portfolio Scan",
    color: "#b0a090",
    count: 6,
    spines: [
      ["geo:spain", "company:cabify", "company:seedtag"],
      ["geo:latam", "company:rappi", "sector:fintech"],
      ["company:nvidia", "company:openai", "company:databricks"],
    ],
  },
  {
    id: "platform-operations",
    label: "Platform Operations",
    color: "#90b090",
    count: 6,
    spines: [
      ["flow:reg-watch", "flow:alert-pipeline", "comp:scheduler"],
      ["flow:sector-scan", "flow:dd-flow", "flow:client-report"],
      ["comp:knowledge-store", "comp:vector-index", "comp:orchestrator"],
    ],
  },
  {
    id: "frontier-health-watch",
    label: "Frontier & Health Watch",
    color: "#c0a0a0",
    count: 6,
    spines: [
      ["reg:hipaa", "company:moderna", "sector:biotech"],
      ["sector:defense", "sector:climate", "geo:nordics"],
      ["reg:mdr", "company:biontech", "geo:germany"],
    ],
  },
];

export const TOTAL_QUERIES = DEMO_THEMES.reduce((s, t) => s + t.count, 0);
