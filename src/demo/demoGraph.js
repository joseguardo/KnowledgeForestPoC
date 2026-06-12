/**
 * Graph views over the demo dataset: pointer lookup, adjacency, stats.
 * Same shape the old knowledgeGraph.js exposed, but sourced from the
 * self-contained demo dataset instead of the live app's trees.js.
 */
import { DEMO_POINTERS, DEMO_EDGES } from "./data/demoDataset.js";

export const POINTERS = DEMO_POINTERS;
export const EDGES = DEMO_EDGES;

export const POINTER_MAP = {};
for (const p of POINTERS) POINTER_MAP[p.id] = p;

// Bidirectional adjacency for query detours
export const ADJACENCY = {};

function addEdge(a, b) {
  if (!ADJACENCY[a]) ADJACENCY[a] = new Set();
  if (!ADJACENCY[b]) ADJACENCY[b] = new Set();
  ADJACENCY[a].add(b);
  ADJACENCY[b].add(a);
}

EDGES.forEach((e) => addEdge(e.source, e.target));
Object.keys(ADJACENCY).forEach((k) => {
  ADJACENCY[k] = [...ADJACENCY[k]];
});

export const GRAPH_STATS = {
  pointerCount: POINTERS.length,
  edgeCount: EDGES.length,
  connectedPointers: Object.keys(ADJACENCY).length,
  isolatedPointers: POINTERS.filter((p) => !ADJACENCY[p.id] || ADJACENCY[p.id].length === 0).map((p) => p.id),
};
