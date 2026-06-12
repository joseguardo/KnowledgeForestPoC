/**
 * Stable identity for content-addressed clusters.
 *
 * The clustering engine outputs branches as raw pointer-id arrays whose
 * "natural" id changes whenever membership changes. To morph the scene
 * instead of rebuilding it, clusters are matched step-over-step by pointer
 * overlap and given persistent numeric uids.
 */

/**
 * Greedy max-overlap matching between previous uid → member-set map and the
 * next step's clusters. Deterministic tie-breaks (overlap desc, uid asc,
 * cluster index asc).
 *
 * @param {Map<number, Set<string>>} prevMap
 * @param {string[][]} nextClusters
 * @returns {{ assignments: (number|null)[], unmatchedPrev: number[] }}
 */
export function matchClusters(prevMap, nextClusters) {
  const candidates = [];
  for (const [uid, set] of prevMap) {
    for (let i = 0; i < nextClusters.length; i++) {
      let ov = 0;
      for (const x of nextClusters[i]) if (set.has(x)) ov++;
      if (ov > 0) candidates.push({ uid, i, ov });
    }
  }
  candidates.sort((a, b) => b.ov - a.ov || a.uid - b.uid || a.i - b.i);

  const usedPrev = new Set();
  const usedNext = new Set();
  const assignments = new Array(nextClusters.length).fill(null);
  for (const c of candidates) {
    if (usedPrev.has(c.uid) || usedNext.has(c.i)) continue;
    assignments[c.i] = c.uid;
    usedPrev.add(c.uid);
    usedNext.add(c.i);
  }
  return {
    assignments,
    unmatchedPrev: [...prevMap.keys()].filter((u) => !usedPrev.has(u)),
  };
}

export function createTracker() {
  return {
    branchMembers: new Map(), // branchUid -> Set<pointerId>
    treeMembers: new Map(), // treeUid -> Set<pointerId> (union of member branches)
    branchTree: new Map(), // branchUid -> treeUid
    branchNames: new Map(), // branchUid -> string
    treeLabels: new Map(), // treeUid -> string
    nextBranchUid: 1,
    nextTreeUid: 1,
  };
}
