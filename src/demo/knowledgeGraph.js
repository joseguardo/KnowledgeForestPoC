/**
 * Flat graph representation of the 58 pointers and 95 edges
 * extracted from src/data/trees.js. Used for offline demo simulation.
 *
 * IDs use the original string format (e.g., "company:crowdstrike")
 * for readability in the demo context.
 */
import { TREES } from "../data/trees";

// Tree-ID → singular pointer type (must match priority list in treeNamer.js)
const TREE_TYPE = {
  sectors:        "sector",
  companies:      "company",
  people:         "person",
  geographies:    "geography",
  regulation:     "regulation",
  components:     "component",
  agents:         "agent",
  skills:         "skill",
  tools:          "tool",
  flows:          "flow",
  trees_meta:     "meta",
  best_practices: "best_practice",
  architecture:   "architecture",
};

// Extract all pointers (branches) from TREES
export const POINTERS = [];
export const POINTER_MAP = {}; // id → { id, label, type, treeId, leaves }

TREES.forEach((tree) => {
  tree.branches.forEach((branch) => {
    const ptr = {
      id: branch.id,
      label: branch.name,
      type: TREE_TYPE[tree.id] || tree.id, // explicit map; fallback to raw id
      treeId: tree.id,
      leaves: branch.leaves || [],
    };
    POINTERS.push(ptr);
    POINTER_MAP[branch.id] = ptr;
  });
});

// Extract all edges (from branch links) — directed
export const EDGES = [];

TREES.forEach((tree) => {
  tree.branches.forEach((branch) => {
    (branch.links || []).forEach((link) => {
      EDGES.push({
        source: branch.id,
        target: link.id,
        why: link.why,
      });
    });
  });
});

// Build bidirectional adjacency map for path validation
export const ADJACENCY = {};

function addEdge(a, b) {
  if (!ADJACENCY[a]) ADJACENCY[a] = new Set();
  if (!ADJACENCY[b]) ADJACENCY[b] = new Set();
  ADJACENCY[a].add(b);
  ADJACENCY[b].add(a);
}

EDGES.forEach((e) => addEdge(e.source, e.target));

// Convert sets to arrays for easier consumption
Object.keys(ADJACENCY).forEach((k) => {
  ADJACENCY[k] = [...ADJACENCY[k]];
});

// Stats
export const GRAPH_STATS = {
  pointerCount: POINTERS.length,
  edgeCount: EDGES.length,
  connectedPointers: Object.keys(ADJACENCY).length,
  isolatedPointers: POINTERS.filter((p) => !ADJACENCY[p.id] || ADJACENCY[p.id].length === 0).map((p) => p.id),
};
