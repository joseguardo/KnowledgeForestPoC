/**
 * Generates 200 synthetic navigation queries for the Nzyme tenant.
 * Each query is a path of 3-6 pointer IDs following actual graph edges.
 * Queries are interleaved across 10 investigation themes.
 */
import { ADJACENCY } from "./knowledgeGraph";

// Simple seeded PRNG (mulberry32)
function seededRandom(seed) {
  let s = seed | 0;
  return function () {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Theme definitions: investigation patterns for a regulatory intelligence firm
const THEMES = [
  {
    id: "eu-ai-regulation",
    label: "European AI Regulation",
    color: "#4a90d9",
    count: 22,
    spines: [
      ["reg:eu-ai-act", "geo:europe", "reg:gdpr", "sector:cyber"],
      ["reg:mifid", "geo:europe", "reg:eu-ai-act", "agent:research"],
      ["reg:gdpr", "geo:europe", "reg:eu-ai-act", "sector:ai-infra"],
    ],
  },
  {
    id: "security-compliance",
    label: "Security & Compliance",
    color: "#e04040",
    count: 22,
    spines: [
      ["bp:security", "reg:gdpr", "company:crowdstrike", "company:wiz", "sector:cyber"],
      ["bp:security", "comp:api-gateway", "arch:service-mesh"],
      ["company:crowdstrike", "person:kurtz", "person:huang", "company:nvidia"],
    ],
  },
  {
    id: "spanish-tech",
    label: "Spanish Tech Hub",
    color: "#e8a838",
    count: 20,
    spines: [
      ["geo:spain", "company:factorial", "sector:fintech"],
      ["geo:spain", "company:seedtag", "sector:consumer", "company:jobandtalent"],
      ["company:clarity-ai", "sector:ai-infra", "company:seedtag", "geo:spain"],
    ],
  },
  {
    id: "ai-infrastructure",
    label: "AI Infrastructure",
    color: "#7b61ff",
    count: 22,
    spines: [
      ["company:nvidia", "sector:ai-infra", "company:seedtag", "geo:spain"],
      ["person:huang", "company:nvidia", "sector:ai-infra", "reg:eu-ai-act"],
      ["sector:ai-infra", "sector:cyber", "company:crowdstrike"],
    ],
  },
  {
    id: "agent-architecture",
    label: "Agent Architecture",
    color: "#40c0a0",
    count: 20,
    spines: [
      ["comp:orchestrator", "agent:research", "skill:web-research", "tool:web-search"],
      ["arch:agent-framework", "agent:analyst", "skill:report-gen", "tool:doc-writer"],
      ["comp:orchestrator", "arch:event-bus", "arch:service-mesh", "comp:api-gateway"],
    ],
  },
  {
    id: "monitoring-pipeline",
    label: "Monitoring Pipeline",
    color: "#d94070",
    count: 18,
    spines: [
      ["flow:alert-pipeline", "agent:monitor", "skill:alerting", "tool:notifier"],
      ["comp:scheduler", "flow:alert-pipeline", "agent:monitor", "skill:alerting"],
    ],
  },
  {
    id: "data-knowledge",
    label: "Data & Knowledge",
    color: "#60a0c0",
    count: 18,
    spines: [
      ["bp:data-quality", "comp:knowledge-store", "arch:data-layer", "tool:db-connector"],
      ["arch:data-layer", "tool:db-connector", "comp:knowledge-store", "bp:data-quality"],
    ],
  },
  {
    id: "fintech-latam",
    label: "Fintech & LatAm",
    color: "#a0d040",
    count: 18,
    spines: [
      ["geo:latam", "sector:fintech", "company:stripe", "person:collison"],
      ["sector:fintech", "reg:sec", "geo:us", "company:stripe"],
      ["company:stripe", "sector:fintech", "company:factorial", "geo:spain"],
    ],
  },
  {
    id: "research-workflows",
    label: "Research Workflows",
    color: "#c080e0",
    count: 20,
    spines: [
      ["flow:sector-scan", "agent:research", "skill:web-research", "tool:web-search"],
      ["flow:dd-flow", "skill:analysis", "agent:analyst", "skill:report-gen", "tool:doc-writer"],
      ["flow:network-map", "agent:connector", "skill:web-research"],
    ],
  },
  {
    id: "consumer-biotech",
    label: "Consumer & Biotech",
    color: "#e0a070",
    count: 20,
    spines: [
      ["sector:consumer", "company:apple", "person:cook", "person:collison"],
      ["company:moderna", "sector:biotech", "sector:consumer", "company:seedtag"],
      ["company:apple", "sector:consumer", "company:jobandtalent", "geo:spain"],
    ],
  },
];

export { THEMES };

/**
 * Generate a single query path from a theme definition.
 * Returns an array of pointer IDs (3-6 elements).
 */
function generateSingleQuery(theme, rng) {
  // Pick a random spine
  const spine = theme.spines[Math.floor(rng() * theme.spines.length)];

  // Random entry offset (0 or 1 nodes into the spine)
  const maxStart = Math.min(1, spine.length - 3);
  const start = Math.floor(rng() * (maxStart + 1));

  // Random end offset
  const minEnd = start + 3;
  const end = Math.min(
    spine.length,
    minEnd + Math.floor(rng() * (spine.length - minEnd + 1))
  );

  let path = spine.slice(start, end);

  // Optionally add a detour from a neighbor of a random node
  if (rng() > 0.35 && path.length < 6) {
    const pivotIdx = Math.floor(rng() * path.length);
    const neighbors = ADJACENCY[path[pivotIdx]] || [];
    const detour = neighbors.filter((n) => !path.includes(n));
    if (detour.length > 0) {
      const d = detour[Math.floor(rng() * detour.length)];
      path.splice(pivotIdx + 1, 0, d);
    }
  }

  // Trim to max 6
  path = path.slice(0, 6);

  // Ensure minimum 3
  if (path.length < 3) {
    path = spine.slice(0, Math.min(3, spine.length));
  }

  return path;
}

/**
 * Interleave queries across themes using round-robin with jitter.
 */
function interleaveQueries(queriesByTheme, rng) {
  const result = [];
  const queues = queriesByTheme.map((q) => [...q]);
  let emptyCount = 0;

  while (emptyCount < queues.length) {
    emptyCount = 0;
    for (let t = 0; t < queues.length; t++) {
      if (queues[t].length === 0) {
        emptyCount++;
        continue;
      }
      // Take 1-3 queries from this theme
      const take = Math.min(
        queues[t].length,
        1 + Math.floor(rng() * 2)
      );
      for (let i = 0; i < take; i++) {
        result.push(queues[t].shift());
      }
    }
  }

  return result;
}

/**
 * Generate all 200 queries with deterministic seeded PRNG.
 * Returns array of { themeId, themeLabel, themeColor, pointerIds }
 */
export function generateQueries(seed = 42) {
  const rng = seededRandom(seed);
  const queriesByTheme = [];

  for (const theme of THEMES) {
    const themeQueries = [];
    for (let i = 0; i < theme.count; i++) {
      const pointerIds = generateSingleQuery(theme, rng);
      themeQueries.push({
        themeId: theme.id,
        themeLabel: theme.label,
        themeColor: theme.color,
        pointerIds,
      });
    }
    queriesByTheme.push(themeQueries);
  }

  return interleaveQueries(queriesByTheme, rng);
}

// Pre-generated queries for the demo (deterministic)
export const NZYME_QUERIES = generateQueries(42);

/**
 * Stats about the generated queries.
 */
export function getQueryStats(queries) {
  const pointerHits = {};
  const themeCounts = {};
  const pathLengths = [];

  for (const q of queries) {
    themeCounts[q.themeId] = (themeCounts[q.themeId] || 0) + 1;
    pathLengths.push(q.pointerIds.length);
    for (const pid of q.pointerIds) {
      pointerHits[pid] = (pointerHits[pid] || 0) + 1;
    }
  }

  return {
    totalQueries: queries.length,
    themeCounts,
    avgPathLength: (pathLengths.reduce((a, b) => a + b, 0) / pathLengths.length).toFixed(1),
    uniquePointersTouched: Object.keys(pointerHits).length,
    pointerHits,
  };
}
