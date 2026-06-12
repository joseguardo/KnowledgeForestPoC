/**
 * Deterministic, stable layout for the demo forest.
 *
 * Every position is decided once and never recycled: tree uids get fixed
 * circular slots, branch uids get golden-angle slots per tree in join order,
 * pointer satellites get golden-angle slots per branch in join order, and
 * scattered pointers get seeded phyllotaxis homes on the ground plane.
 *
 * All positions are plain [x, y, z] arrays so this module stays free of
 * three.js and runnable under plain node for calibration.
 */

const GOLDEN = 2.399963229728653; // golden angle in radians

export const DEMO_GEOM = {
  TRUNK_H: 2.8,
  BRANCH_LEN: 3.0,
  POINTER_R: 0.16,
  BRANCH_R: 0.34,
  ROOT_R: 0.55,
  SCATTER_Y: 0.35,
};

// Simple seeded PRNG (mulberry32) — local copy to keep this module standalone
function seededRandom(seed) {
  let s = seed | 0;
  return function () {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Layout factory. `totalTrees` = number of tree uids ever minted in the run
 * (known after the simulation pre-pass), so slots never shift.
 */
export function createLayout(totalTrees, pointerIds, seed = 7) {
  // ── Scatter homes: jittered phyllotaxis disc, deterministically shuffled
  const rng = seededRandom(seed);
  const order = pointerIds.map((_, i) => i);
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }
  const scatterHomes = {};
  pointerIds.forEach((pid, idx) => {
    const i = order[idx];
    const r = 2.8 * Math.sqrt(i + 0.6) + (rng() - 0.5) * 1.4;
    const theta = i * GOLDEN + (rng() - 0.5) * 0.5;
    scatterHomes[pid] = [
      Math.cos(theta) * r,
      DEMO_GEOM.SCATTER_Y + rng() * 0.5,
      Math.sin(theta) * r,
    ];
  });

  // ── Tree slots: fixed circle sized by the total uid count
  const n = Math.max(totalTrees, 1);
  const treeRadius = 19 + Math.max(0, n - 8) * 1.1;
  const treeSlots = new Map(); // treeUid -> [x,y,z]

  function getTreePos(treeUid) {
    if (!treeSlots.has(treeUid)) {
      const idx = treeSlots.size;
      const angle = (idx / n) * Math.PI * 2 - Math.PI / 2;
      treeSlots.set(treeUid, [
        Math.cos(angle) * treeRadius,
        0,
        Math.sin(angle) * treeRadius,
      ]);
    }
    return treeSlots.get(treeUid);
  }

  // ── Branch slots: per (treeUid, branchUid), golden angle in join order
  const branchSlotCounters = new Map(); // treeUid -> next join index
  const branchSlots = new Map(); // `${treeUid}|${branchUid}` -> local [x,y,z]

  function getBranchLocal(treeUid, branchUid) {
    const key = `${treeUid}|${branchUid}`;
    if (!branchSlots.has(key)) {
      const j = branchSlotCounters.get(treeUid) || 0;
      branchSlotCounters.set(treeUid, j + 1);
      const angle = j * GOLDEN;
      const len = DEMO_GEOM.BRANCH_LEN + (j % 2) * 0.7;
      branchSlots.set(key, [
        Math.cos(angle) * len,
        DEMO_GEOM.TRUNK_H + 0.5 + (j % 3) * 0.65,
        Math.sin(angle) * len,
      ]);
    }
    return branchSlots.get(key);
  }

  // ── Satellite slots: per (branchUid, pointerId), golden angle in join order
  const satCounters = new Map(); // branchUid -> next join index
  const satSlots = new Map(); // `${branchUid}|${pid}` -> local [x,y,z]

  function getSatelliteLocal(branchUid, pid) {
    const key = `${branchUid}|${pid}`;
    if (!satSlots.has(key)) {
      const j = satCounters.get(branchUid) || 0;
      satCounters.set(branchUid, j + 1);
      const angle = j * GOLDEN;
      const r = 0.75 + (j % 2) * 0.25;
      satSlots.set(key, [
        Math.cos(angle) * r,
        ((j % 3) - 1) * 0.32 + 0.12,
        Math.sin(angle) * r,
      ]);
    }
    return satSlots.get(key);
  }

  function getScatterHome(pid) {
    return scatterHomes[pid];
  }

  return { getTreePos, getBranchLocal, getSatelliteLocal, getScatterHome, treeRadius };
}

export function add3(a, b) {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}
