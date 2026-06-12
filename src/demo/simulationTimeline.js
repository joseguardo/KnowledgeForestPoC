/**
 * Precomputes the full Forest Creation timeline.
 *
 * Replays every synthetic query through the co-access engine ONE query at a
 * time, tracks stable branch/tree identity across steps, assigns layout
 * positions, and emits a flat, time-stamped event list that the scene
 * manager plays back. Also produces snapshots so the scrubber can jump to
 * any moment.
 *
 * Pure data — no three.js — so it runs under plain node for calibration:
 *   node --input-type=module -e "import('./src/demo/simulationTimeline.js')
 *     .then(m => console.log(m.debugSummary()))"
 */
import { POINTERS, POINTER_MAP } from "./demoGraph.js";
import { DEMO_QUERIES } from "./queryGenerator.js";
import { DEMO_TUNING } from "./data/demoDataset.js";
import { createCoAccessState, computeForest } from "./coAccessEngine.js";
import { matchClusters, createTracker } from "./identityTracker.js";
import { createLayout, add3 } from "./layoutEngine.js";
import { nameBranch, nameTree } from "./treeNamer.js";

const FOREST_OPTS = {
  threshold: DEMO_TUNING.THRESHOLD,
  maxTrees: DEMO_TUNING.MAX_TREES,
  minBranchSize: DEMO_TUNING.MIN_BRANCH_SIZE,
  linkage: "avg",
  treeAffinity: 1.0,
  secondaryThreshold: DEMO_TUNING.SECONDARY_THRESHOLD,
  maxSecondary: DEMO_TUNING.MAX_SECONDARY,
};

const ENTITY_TYPES = new Set(["company", "person", "sector", "geography", "regulation"]);

const WEIGHT_CHECKPOINT_EVERY = 64;

// ─── Pacing (timeline seconds at 1x; target ~60-90s total) ──────
const PACING = {
  intro: 1.2, // establishing beat before the first query
  slotStart: 0.45, // time between query launches at the beginning
  slotEnd: 0.07, // ... and once the stream is flowing
  slotRampQueries: 70, // queries over which the slot eases down
  travelMin: 0.45,
  travelMax: 1.0,
  outro: 3.0,
  beats: {
    TREE_FORMED: [1.3, 0.4, 3], // [early hold, late hold, "early" count]
    BRANCH_FORMED: [1.2, 0.3, 3],
    BRANCH_GREW: [0.1, 0.1, 0],
    BRANCH_MOVED_TREE: [0.1, 0.1, 0],
    BRANCH_DISSOLVED: [0.15, 0.15, 0],
    POINTERS_RELEASED: [0.15, 0.15, 0],
    BRANCH_RENAMED: [0, 0, 0],
    TREE_RENAMED: [0, 0, 0],
    TREE_DISSOLVED: [0.15, 0.15, 0],
    POINTER_LINKED: [0.9, 0.2, 2], // card joins a second cluster
    POINTER_UNLINKED: [0.1, 0.1, 0],
  },
  featuredMinGap: 3.0, // seconds between camera-featured events
};

function smoothstep(a, b, x) {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function treeType(pointerIds) {
  let entity = 0;
  for (const pid of pointerIds) {
    if (ENTITY_TYPES.has(POINTER_MAP[pid]?.type)) entity++;
  }
  return entity > pointerIds.length / 2 ? "entity" : "system";
}

// ─── Build ──────────────────────────────────────────────────────

function build() {
  const queries = DEMO_QUERIES;
  const allPointerIds = POINTERS.map((p) => p.id);

  // Pair registry: stable segment index per co-accessed pair
  const pairIndex = new Map(); // "a\0b" -> idx
  const pairEndpoints = []; // idx -> [aPid, bPid]
  const pairWeights = new Map(); // idx -> cumulative weight

  const state = createCoAccessState();

  function addPath(pointerIds) {
    const touched = new Map(); // idx -> new cumulative weight
    for (let i = 0; i < pointerIds.length; i++) {
      for (let j = i + 1; j < pointerIds.length; j++) {
        const a = pointerIds[i];
        const b = pointerIds[j];
        if (a === b) continue;
        const key = a < b ? `${a}\0${b}` : `${b}\0${a}`;
        const w = (state.weights.get(key) || 0) + 1.0 / (j - i);
        state.weights.set(key, w);
        let idx = pairIndex.get(key);
        if (idx === undefined) {
          idx = pairEndpoints.length;
          pairIndex.set(key, idx);
          pairEndpoints.push(a < b ? [a, b] : [b, a]);
        }
        pairWeights.set(idx, w);
        touched.set(idx, w);
      }
    }
    state.pathCount++;
    return [...touched.entries()]; // [[pairIdx, newWeight], ...]
  }

  // ─── Pass A: replay + identity tracking ───────────────────────
  const tracker = createTracker();
  const steps = []; // per query
  const structures = []; // snapshots at structural changes
  const weightCheckpoints = []; // { step, weights: Map<idx, w> }
  let prevAssigned = new Map(); // pid -> branchUid
  let prevSecondary = new Map(); // "pid|branchUid" -> weight

  for (let qi = 0; qi < queries.length; qi++) {
    const q = queries[qi];
    const deltas = addPath(q.pointerIds);
    const { branches: rawBranches, trees: rawTrees, secondary: rawSecondary } = computeForest(
      state,
      FOREST_OPTS
    );

    const events = [];

    // Branch identity
    const branchMatch = matchClusters(tracker.branchMembers, rawBranches);
    const clusterUid = []; // ci -> uid
    rawBranches.forEach((cluster, ci) => {
      let uid = branchMatch.assignments[ci];
      if (uid == null) uid = tracker.nextBranchUid++;
      clusterUid[ci] = uid;
    });

    // Tree identity (matched on pointer unions for stability)
    const refToIdx = new Map();
    rawBranches.forEach((c, idx) => refToIdx.set(c, idx));
    const treeBranchUids = rawTrees.map((tc) => tc.map((c) => clusterUid[refToIdx.get(c)]));
    const treeUnions = rawTrees.map((tc) => tc.flat());
    const treeMatch = matchClusters(tracker.treeMembers, treeUnions);
    const treeUidByIdx = []; // ti -> uid
    rawTrees.forEach((_, ti) => {
      let uid = treeMatch.assignments[ti];
      if (uid == null) uid = tracker.nextTreeUid++;
      treeUidByIdx[ti] = uid;
    });
    const branchToTree = new Map();
    treeBranchUids.forEach((uids, ti) => {
      for (const bu of uids) branchToTree.set(bu, treeUidByIdx[ti]);
    });

    // Tree events
    const treeLabels = rawTrees.map((tc, ti) => {
      const formatted = tc.map((c) => ({ name: nameBranch(c), pointerIds: c }));
      return nameTree(formatted);
    });
    rawTrees.forEach((tc, ti) => {
      const uid = treeUidByIdx[ti];
      const label = treeLabels[ti];
      const union = treeUnions[ti];
      if (treeMatch.assignments[ti] == null) {
        events.push({
          type: "TREE_FORMED",
          treeUid: uid,
          label,
          treeType: treeType(union),
        });
        tracker.treeLabels.set(uid, label);
      } else if (tracker.treeLabels.get(uid) !== label) {
        events.push({ type: "TREE_RENAMED", treeUid: uid, label });
        tracker.treeLabels.set(uid, label);
      }
      tracker.treeMembers.set(uid, new Set(union));
    });

    // Branch events
    const nextAssigned = new Map();
    rawBranches.forEach((cluster, ci) => {
      const uid = clusterUid[ci];
      const treeUid = branchToTree.get(uid);
      const name = nameBranch(cluster);
      for (const pid of cluster) nextAssigned.set(pid, uid);

      if (branchMatch.assignments[ci] == null) {
        events.push({
          type: "BRANCH_FORMED",
          branchUid: uid,
          treeUid,
          name,
          pointerIds: [...cluster],
          size: cluster.length,
        });
        tracker.branchTree.set(uid, treeUid);
        tracker.branchNames.set(uid, name);
      } else {
        const prevSet = tracker.branchMembers.get(uid);
        const added = cluster.filter((p) => !prevSet.has(p));
        if (tracker.branchTree.get(uid) !== treeUid) {
          events.push({
            type: "BRANCH_MOVED_TREE",
            branchUid: uid,
            fromTreeUid: tracker.branchTree.get(uid),
            treeUid,
            pointerIds: [...cluster],
            size: cluster.length,
          });
          tracker.branchTree.set(uid, treeUid);
        }
        if (added.length > 0) {
          events.push({
            type: "BRANCH_GREW",
            branchUid: uid,
            treeUid,
            name,
            addedPointerIds: added,
            size: cluster.length,
          });
        }
        if (tracker.branchNames.get(uid) !== name) {
          if (added.length === 0) {
            events.push({ type: "BRANCH_RENAMED", branchUid: uid, name });
          }
          tracker.branchNames.set(uid, name);
        }
      }
      tracker.branchMembers.set(uid, new Set(cluster));
    });

    // Dissolved branches (members were absorbed elsewhere)
    for (const uid of branchMatch.unmatchedPrev) {
      const members = tracker.branchMembers.get(uid);
      const counts = new Map();
      for (const pid of members) {
        const to = nextAssigned.get(pid);
        if (to != null) counts.set(to, (counts.get(to) || 0) + 1);
      }
      let intoBranchUid = null;
      let best = 0;
      for (const [to, n] of counts) {
        if (n > best || (n === best && (intoBranchUid == null || to < intoBranchUid))) {
          best = n;
          intoBranchUid = to;
        }
      }
      events.push({ type: "BRANCH_DISSOLVED", branchUid: uid, intoBranchUid });
      tracker.branchMembers.delete(uid);
      tracker.branchTree.delete(uid);
      tracker.branchNames.delete(uid);
    }

    // Dissolved trees
    for (const uid of treeMatch.unmatchedPrev) {
      events.push({ type: "TREE_DISSOLVED", treeUid: uid });
      tracker.treeMembers.delete(uid);
      tracker.treeLabels.delete(uid);
    }

    // Released pointers (left the forest entirely)
    const released = [];
    for (const pid of prevAssigned.keys()) {
      if (!nextAssigned.has(pid)) released.push(pid);
    }
    if (released.length > 0) {
      events.push({ type: "POINTERS_RELEASED", pointerIds: released });
    }
    prevAssigned = nextAssigned;

    // Secondary (multi-cluster) membership diff
    const nextSecondary = new Map();
    for (const s of rawSecondary) {
      const branchUid = clusterUid[s.branchIndex];
      nextSecondary.set(`${s.pointerId}|${branchUid}`, s.weight);
    }
    for (const [key, weight] of nextSecondary) {
      if (prevSecondary.has(key)) continue;
      const [pid, uidStr] = key.split("|");
      const branchUid = Number(uidStr);
      events.push({
        type: "POINTER_LINKED",
        pointerId: pid,
        pointerLabel: POINTER_MAP[pid]?.label || pid,
        branchUid,
        branchName: tracker.branchNames.get(branchUid),
        weight,
      });
    }
    for (const key of prevSecondary.keys()) {
      if (nextSecondary.has(key)) continue;
      const [pid, uidStr] = key.split("|");
      events.push({ type: "POINTER_UNLINKED", pointerId: pid, branchUid: Number(uidStr) });
    }
    prevSecondary = nextSecondary;

    // Sort: trees form before the branches that attach to them
    const ORDER = {
      TREE_FORMED: 0,
      BRANCH_MOVED_TREE: 1,
      BRANCH_FORMED: 2,
      BRANCH_GREW: 3,
      BRANCH_RENAMED: 4,
      TREE_RENAMED: 5,
      BRANCH_DISSOLVED: 6,
      TREE_DISSOLVED: 7,
      POINTERS_RELEASED: 8,
      POINTER_UNLINKED: 9,
      POINTER_LINKED: 10,
    };
    events.sort((a, b) => ORDER[a.type] - ORDER[b.type]);

    // Structure snapshot when anything changed
    let structureIdx = structures.length - 1;
    if (events.length > 0) {
      const branchesSnap = rawBranches.map((cluster, ci) => ({
        uid: clusterUid[ci],
        treeUid: branchToTree.get(clusterUid[ci]),
        name: nameBranch(cluster),
        pointerIds: [...cluster],
      }));
      const treesSnap = rawTrees.map((tc, ti) => ({
        uid: treeUidByIdx[ti],
        label: treeLabels[ti],
        treeType: treeType(treeUnions[ti]),
        branchUids: [...treeBranchUids[ti]],
      }));
      const secondariesSnap = [];
      for (const [key, weight] of nextSecondary) {
        const [pid, uidStr] = key.split("|");
        secondariesSnap.push({ pid, branchUid: Number(uidStr), weight });
      }
      structures.push({
        step: qi,
        trees: treesSnap,
        branches: branchesSnap,
        secondaries: secondariesSnap,
        stats: {
          treeCount: treesSnap.length,
          branchCount: branchesSnap.length,
          assigned: nextAssigned.size,
          shared: new Set(secondariesSnap.map((s) => s.pid)).size,
          total: allPointerIds.length,
        },
      });
      structureIdx = structures.length - 1;
    }

    steps.push({
      queryIndex: qi,
      deltas,
      events,
      structureIdx,
      tStart: 0, // filled in pass C
    });

    if ((qi + 1) % WEIGHT_CHECKPOINT_EVERY === 0) {
      weightCheckpoints.push({ step: qi, weights: new Map(pairWeights) });
    }
  }

  const totalTrees = tracker.nextTreeUid - 1;

  // ─── Pass B: layout (positions decided in event order, never recycled) ──
  const layout = createLayout(totalTrees, allPointerIds);
  const branchWorld = new Map(); // branchUid -> [x,y,z]

  function satelliteWorlds(branchUid, pointerIds) {
    const bw = branchWorld.get(branchUid);
    const out = {};
    for (const pid of pointerIds) {
      out[pid] = add3(bw, layout.getSatelliteLocal(branchUid, pid));
    }
    return out;
  }

  for (const step of steps) {
    for (const ev of step.events) {
      switch (ev.type) {
        case "TREE_FORMED":
          ev.pos = layout.getTreePos(ev.treeUid);
          break;
        case "BRANCH_FORMED": {
          const tp = layout.getTreePos(ev.treeUid);
          const local = layout.getBranchLocal(ev.treeUid, ev.branchUid);
          const world = add3(tp, local);
          branchWorld.set(ev.branchUid, world);
          ev.world = world;
          ev.treePos = tp;
          ev.satellites = satelliteWorlds(ev.branchUid, ev.pointerIds);
          break;
        }
        case "BRANCH_MOVED_TREE": {
          const tp = layout.getTreePos(ev.treeUid);
          const local = layout.getBranchLocal(ev.treeUid, ev.branchUid);
          const world = add3(tp, local);
          branchWorld.set(ev.branchUid, world);
          ev.world = world;
          ev.treePos = tp;
          ev.satellites = satelliteWorlds(ev.branchUid, ev.pointerIds);
          break;
        }
        case "BRANCH_GREW":
          ev.satellites = satelliteWorlds(ev.branchUid, ev.addedPointerIds);
          break;
        case "POINTER_LINKED": {
          // Ghost slot is branch-local so the ghost rides along if the
          // branch later moves between trees
          ev.local = layout.getSatelliteLocal(ev.branchUid, `ghost:${ev.pointerId}`);
          const bw = branchWorld.get(ev.branchUid);
          if (bw) ev.world = add3(bw, ev.local);
          break;
        }
        default:
          break;
      }
    }
  }

  // Decorate structure snapshots with resolved positions
  for (const s of structures) {
    for (const t of s.trees) t.pos = layout.getTreePos(t.uid);
    for (const b of s.branches) {
      const tp = layout.getTreePos(b.treeUid);
      b.world = add3(tp, layout.getBranchLocal(b.treeUid, b.uid));
      b.satellites = {};
      for (const pid of b.pointerIds) {
        b.satellites[pid] = add3(b.world, layout.getSatelliteLocal(b.uid, pid));
      }
    }
    for (const sec of s.secondaries) {
      sec.local = layout.getSatelliteLocal(sec.branchUid, `ghost:${sec.pid}`);
    }
  }

  // ─── Pass C: pacing ────────────────────────────────────────────
  const flatEvents = [];
  let t = PACING.intro;
  let branchFormedCount = 0;
  let treeFormedCount = 0;
  let linkedCount = 0;
  let lastFeaturedT = -100;
  let phase = 0;

  function pushPhase(at, title, subtitle) {
    flatEvents.push({ type: "PHASE", t: at, title, subtitle });
  }

  pushPhase(0, "Scattered knowledge", `${allPointerIds.length} pointers — no structure yet`);

  for (const step of steps) {
    const qi = step.queryIndex;
    const q = queries[qi];
    const slot =
      qi < 6
        ? PACING.slotStart
        : lerp(PACING.slotStart * 0.9, PACING.slotEnd, smoothstep(6, PACING.slotRampQueries, qi));
    const travel = Math.max(PACING.travelMin, Math.min(PACING.travelMax, slot * 2.2));

    step.tStart = t;
    flatEvents.push({
      type: "QUERY",
      t,
      travel,
      queryIndex: qi,
      themeColor: q.themeColor,
      themeLabel: q.themeLabel,
      pointerIds: q.pointerIds,
      text: q.pointerIds.map((pid) => POINTER_MAP[pid]?.label || pid).join("  →  "),
      deltas: step.deltas,
    });

    let hold = 0;
    const impactT = t + travel * 0.85;
    for (const ev of step.events) {
      ev.t = impactT + hold;
      const beat = PACING.beats[ev.type] || [0, 0, 0];
      let beatLen = beat[1];
      if (ev.type === "BRANCH_FORMED") {
        beatLen = branchFormedCount < beat[2] ? beat[0] : beat[1];
        branchFormedCount++;
      } else if (ev.type === "TREE_FORMED") {
        beatLen = treeFormedCount < beat[2] ? beat[0] : beat[1];
        treeFormedCount++;
      } else if (ev.type === "POINTER_LINKED") {
        beatLen = linkedCount < beat[2] ? beat[0] : beat[1];
        linkedCount++;
      }
      // Featured events get a camera shot
      if (
        (ev.type === "BRANCH_FORMED" || ev.type === "TREE_FORMED") &&
        (branchFormedCount + treeFormedCount <= 6 || ev.t - lastFeaturedT > PACING.featuredMinGap)
      ) {
        ev.featured = true;
        lastFeaturedT = ev.t;
      }
      // The first shared cards are a key story moment — feature them
      if (ev.type === "POINTER_LINKED" && linkedCount <= 2 && ev.world) {
        ev.featured = true;
        lastFeaturedT = ev.t;
      }
      hold += beatLen;
      flatEvents.push(ev);

      // Narrative phases
      if (phase === 0 && ev.type === "BRANCH_FORMED") {
        phase = 1;
        pushPhase(ev.t - 0.05, "Patterns emerge", "Co-accessed pointers fuse into branches");
      } else if (phase === 1 && ev.type === "TREE_FORMED" && treeFormedCount >= 3) {
        phase = 2;
        pushPhase(ev.t - 0.05, "Trees take root", "Related branches cluster into trees");
      }
    }
    if (phase === 2 && step.structureIdx >= 0) {
      const st = structures[step.structureIdx].stats;
      if (st.assigned / st.total >= 0.6) {
        phase = 3;
        pushPhase(t + slot, "The forest organizes", "Most knowledge now lives on a tree");
      }
    }

    t += slot + hold;
  }

  const finalStructure = structures[structures.length - 1] || null;
  if (finalStructure) {
    const st = finalStructure.stats;
    pushPhase(
      t + 0.5,
      "A living forest",
      `${st.treeCount} trees · ${st.branchCount} branches · grown from ${queries.length} queries`
    );
  }

  const totalDuration = t + PACING.outro;
  flatEvents.sort((a, b) => a.t - b.t);

  // ─── Snapshot access (for scrubbing) ───────────────────────────
  // stepCount = number of queries fully applied (0..N)
  function snapshotAt(stepCount) {
    const clamped = Math.max(0, Math.min(stepCount, steps.length));
    const structure =
      clamped === 0 ? null : (() => {
        const idx = steps[clamped - 1].structureIdx;
        return idx >= 0 ? structures[idx] : null;
      })();

    // Rebuild weights from nearest checkpoint + deltas
    const weights = new Map();
    let from = 0;
    for (let i = weightCheckpoints.length - 1; i >= 0; i--) {
      if (weightCheckpoints[i].step < clamped) {
        for (const [k, v] of weightCheckpoints[i].weights) weights.set(k, v);
        from = weightCheckpoints[i].step + 1;
        break;
      }
    }
    for (let s = from; s < clamped; s++) {
      for (const [idx, w] of steps[s].deltas) weights.set(idx, w);
    }

    return {
      stepCount: clamped,
      structure,
      weights,
      stats: structure
        ? structure.stats
        : { treeCount: 0, branchCount: 0, assigned: 0, shared: 0, total: allPointerIds.length },
    };
  }

  function stepForTime(time) {
    // number of queries whose tStart <= time
    let lo = 0;
    let hi = steps.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (steps[mid].tStart <= time) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  const scatterHomes = {};
  for (const pid of allPointerIds) scatterHomes[pid] = layout.getScatterHome(pid);

  return {
    events: flatEvents,
    steps,
    structures,
    scatterHomes,
    pairEndpoints,
    pairCount: pairEndpoints.length,
    totalDuration,
    totalQueries: queries.length,
    finalStructure,
    snapshotAt,
    stepForTime,
    threshold: DEMO_TUNING.THRESHOLD,
  };
}

export const TIMELINE = build();

/**
 * Calibration summary (node-runnable, also logged once in dev).
 */
export function debugSummary() {
  const T = TIMELINE;
  const counts = {};
  for (const ev of T.events) counts[ev.type] = (counts[ev.type] || 0) + 1;
  const fs = T.finalStructure;
  return {
    totalDuration: +T.totalDuration.toFixed(1),
    totalQueries: T.totalQueries,
    pairCount: T.pairCount,
    eventCounts: counts,
    finalStats: fs?.stats,
    finalTrees: fs?.trees.map((t) => ({
      label: t.label,
      branches: t.branchUids.length,
    })),
  };
}
