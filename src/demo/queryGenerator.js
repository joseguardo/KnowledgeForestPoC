/**
 * Generates the synthetic navigation queries that drive the Forest Creation
 * demo. Each query is a path of pointer IDs (a simulated research session),
 * generated deterministically from the theme spines in the demo dataset.
 * Queries are interleaved across themes round-robin with jitter.
 */
import { ADJACENCY } from "./demoGraph.js";
import { DEMO_THEMES, DEMO_TUNING } from "./data/demoDataset.js";

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

export const THEMES = DEMO_THEMES;

/**
 * Generate a single query path from a theme definition.
 * Returns an array of pointer IDs (2-6 elements).
 */
function generateSingleQuery(theme, rng) {
  const spine = theme.spines[Math.floor(rng() * theme.spines.length)];

  // Random entry offset (0 or 1 nodes into the spine)
  const maxStart = Math.max(0, Math.min(1, spine.length - 3));
  const start = Math.floor(rng() * (maxStart + 1));

  // Random end offset
  const minEnd = Math.min(spine.length, start + 3);
  const end = Math.min(
    spine.length,
    minEnd + Math.floor(rng() * (spine.length - minEnd + 1))
  );

  let path = spine.slice(start, end);

  // Occasionally add a detour through a knowledge-graph neighbor
  if (rng() > 0.7 && path.length < 6) {
    const pivotIdx = Math.floor(rng() * path.length);
    const neighbors = ADJACENCY[path[pivotIdx]] || [];
    const detour = neighbors.filter((n) => !path.includes(n));
    if (detour.length > 0) {
      const d = detour[Math.floor(rng() * detour.length)];
      path.splice(pivotIdx + 1, 0, d);
    }
  }

  path = path.slice(0, 6);

  if (path.length < 2) {
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
      const take = Math.min(queues[t].length, 1 + Math.floor(rng() * 2));
      for (let i = 0; i < take; i++) {
        result.push(queues[t].shift());
      }
    }
  }

  return result;
}

/**
 * Generate all queries with a deterministic seeded PRNG.
 * Returns array of { themeId, themeLabel, themeColor, pointerIds }
 */
export function generateQueries(seed = DEMO_TUNING.SEED) {
  const rng = seededRandom(seed);
  const queriesByTheme = [];

  // Kickoff burst: the first theme's first spine is hit repeatedly at the
  // start, so the viewer sees the first branch fuse within a few queries.
  const KICKOFF = 6;
  const kickoffTheme = THEMES[0];
  const kickoff = Array.from({ length: KICKOFF }, () => ({
    themeId: kickoffTheme.id,
    themeLabel: kickoffTheme.label,
    themeColor: kickoffTheme.color,
    pointerIds: [...kickoffTheme.spines[0]],
  }));

  for (const theme of THEMES) {
    const themeQueries = [];
    const count = theme === kickoffTheme ? Math.max(0, theme.count - KICKOFF) : theme.count;
    for (let i = 0; i < count; i++) {
      themeQueries.push({
        themeId: theme.id,
        themeLabel: theme.label,
        themeColor: theme.color,
        pointerIds: generateSingleQuery(theme, rng),
      });
    }
    queriesByTheme.push(themeQueries);
  }

  return [...kickoff, ...interleaveQueries(queriesByTheme, rng)];
}

// Pre-generated queries for the demo (deterministic)
export const DEMO_QUERIES = generateQueries();

/**
 * Stats about the generated queries (used for calibration).
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
