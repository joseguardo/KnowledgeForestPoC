/**
 * Client-side co-access engine: accumulator + union-find clustering + agglomerative merge.
 * Port of the compute-forest Edge Function algorithm for offline demo use.
 */

// ─── Co-Access Matrix ───────────────────────────────────────────

/**
 * Create a new empty co-access state.
 */
export function createCoAccessState() {
  return {
    weights: new Map(), // "a\0b" → weight (a < b canonical order)
    pathCount: 0,
  };
}

function pairKey(a, b) {
  return a < b ? `${a}\0${b}` : `${b}\0${a}`;
}

/**
 * Add a navigation path to the co-access matrix.
 * Proximity weighting: weight = 1 / distance_in_path.
 */
export function addPathToMatrix(state, pointerIds) {
  for (let i = 0; i < pointerIds.length; i++) {
    for (let j = i + 1; j < pointerIds.length; j++) {
      const distance = j - i;
      const weight = 1.0 / distance;
      const key = pairKey(pointerIds[i], pointerIds[j]);
      state.weights.set(key, (state.weights.get(key) || 0) + weight);
    }
  }
  state.pathCount++;
}

/**
 * Get all co-access edges as an array.
 */
export function getEdges(state, threshold = 0) {
  const edges = [];
  for (const [key, weight] of state.weights) {
    const [a, b] = key.split("\0");
    edges.push({ a, b, weight, aboveThreshold: weight >= threshold });
  }
  return edges;
}

// ─── Union-Find ─────────────────────────────────────────────────

class UnionFind {
  constructor() {
    this.parent = new Map();
    this.rank = new Map();
  }

  find(x) {
    if (!this.parent.has(x)) {
      this.parent.set(x, x);
      this.rank.set(x, 0);
    }
    if (this.parent.get(x) !== x) {
      this.parent.set(x, this.find(this.parent.get(x)));
    }
    return this.parent.get(x);
  }

  union(a, b) {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra === rb) return;
    const rankA = this.rank.get(ra);
    const rankB = this.rank.get(rb);
    if (rankA < rankB) this.parent.set(ra, rb);
    else if (rankA > rankB) this.parent.set(rb, ra);
    else {
      this.parent.set(rb, ra);
      this.rank.set(ra, rankA + 1);
    }
  }

  components() {
    const groups = new Map();
    for (const node of this.parent.keys()) {
      const root = this.find(node);
      if (!groups.has(root)) groups.set(root, []);
      groups.get(root).push(node);
    }
    return [...groups.values()];
  }
}

// ─── Clustering Pipeline ────────────────────────────────────────

/**
 * Cluster pointers into branches using union-find on co-access edges above threshold.
 * Returns array of pointer ID arrays (each array = one branch).
 */
export function clusterBranches(state, threshold = 1.5, minBranchSize = 2) {
  const uf = new UnionFind();

  for (const [key, weight] of state.weights) {
    if (weight >= threshold) {
      const [a, b] = key.split("\0");
      uf.union(a, b);
    }
  }

  return uf.components().filter((c) => c.length >= minBranchSize);
}

/**
 * Greedy agglomerative merge: combine branches into trees.
 * Merges the two most-affiliated branches until count <= maxTrees.
 */
export function mergeBranchesIntoTrees(branches, state, maxTrees = 12, linkage = "sum", treeAffinity = Infinity) {
  // With the default treeAffinity (Infinity) behavior is unchanged: merging
  // only happens to get under maxTrees. A finite treeAffinity additionally
  // merges any pair whose linkage weight reaches it, so related branches
  // share a tree as soon as the affinity exists instead of reshuffling later.
  if (branches.length <= maxTrees && !Number.isFinite(treeAffinity)) {
    return branches.map((b) => [b]);
  }
  if (branches.length <= 1) {
    return branches.map((b) => [b]);
  }

  // Map pointer → branch index
  const ptrToBranch = new Map();
  branches.forEach((ptrs, idx) =>
    ptrs.forEach((p) => ptrToBranch.set(p, idx))
  );

  // Compute inter-branch affinity
  const branchWeights = new Map();
  for (const [key, weight] of state.weights) {
    const [a, b] = key.split("\0");
    const bi = ptrToBranch.get(a);
    const bj = ptrToBranch.get(b);
    if (bi === undefined || bj === undefined || bi === bj) continue;
    const bKey = `${Math.min(bi, bj)}-${Math.max(bi, bj)}`;
    branchWeights.set(bKey, (branchWeights.get(bKey) || 0) + weight);
  }

  // Start: each branch is its own tree (array of branch indices)
  let treeBranches = branches.map((_, i) => [i]);

  while (treeBranches.length > 1) {
    let bestPair = [-1, -1];
    let bestWeight = 0;

    for (let i = 0; i < treeBranches.length; i++) {
      for (let j = i + 1; j < treeBranches.length; j++) {
        let w = 0;
        for (const bi of treeBranches[i]) {
          for (const bj of treeBranches[j]) {
            const bKey = `${Math.min(bi, bj)}-${Math.max(bi, bj)}`;
            w += branchWeights.get(bKey) || 0;
          }
        }
        // Average linkage avoids one mega-tree absorbing everything
        if (linkage === "avg" && w > 0) {
          w /= treeBranches[i].length * treeBranches[j].length;
        }
        if (w > bestWeight) {
          bestWeight = w;
          bestPair = [i, j];
        }
      }
    }

    if (bestWeight === 0) break;
    if (treeBranches.length <= maxTrees && bestWeight < treeAffinity) break;
    treeBranches[bestPair[0]] = [
      ...treeBranches[bestPair[0]],
      ...treeBranches[bestPair[1]],
    ];
    treeBranches.splice(bestPair[1], 1);
  }

  return treeBranches.map((treeIdxs) => treeIdxs.map((i) => branches[i]));
}

/**
 * Secondary (multi-cluster) memberships: a pointer that already lives in a
 * branch can ALSO belong to other branches it has strong accumulated
 * co-access affinity with. Affinity = sum of pair weights from the pointer
 * to the target branch's members. Pointers stay primary in exactly one
 * branch (the union-find component); this adds overlay memberships.
 *
 * Returns [{ pointerId, branchIndex, weight }] sorted deterministically.
 */
export function computeSecondaryMemberships(
  state,
  branches,
  secondaryThreshold = Infinity,
  maxPerPointer = 2
) {
  if (!Number.isFinite(secondaryThreshold) || branches.length < 2) return [];

  const primary = new Map(); // pointerId -> branchIndex
  branches.forEach((ptrs, bi) => ptrs.forEach((p) => primary.set(p, bi)));

  // Accumulate pointer → foreign-branch affinity
  const affinity = new Map(); // "pid\0bi" -> weight
  for (const [key, w] of state.weights) {
    const [a, b] = key.split("\0");
    const ba = primary.get(a);
    const bb = primary.get(b);
    if (ba === undefined || bb === undefined || ba === bb) continue;
    const ka = `${a}\0${bb}`;
    const kb = `${b}\0${ba}`;
    affinity.set(ka, (affinity.get(ka) || 0) + w);
    affinity.set(kb, (affinity.get(kb) || 0) + w);
  }

  // Group by pointer, keep the strongest few above threshold
  const byPointer = new Map(); // pid -> [{ branchIndex, weight }]
  for (const [key, w] of affinity) {
    if (w < secondaryThreshold) continue;
    const [pid, biStr] = key.split("\0");
    const bi = Number(biStr);
    if (!byPointer.has(pid)) byPointer.set(pid, []);
    byPointer.get(pid).push({ branchIndex: bi, weight: w });
  }

  const result = [];
  const pids = [...byPointer.keys()].sort();
  for (const pid of pids) {
    const list = byPointer
      .get(pid)
      .sort((x, y) => y.weight - x.weight || x.branchIndex - y.branchIndex)
      .slice(0, maxPerPointer);
    for (const m of list) {
      result.push({ pointerId: pid, branchIndex: m.branchIndex, weight: m.weight });
    }
  }
  return result;
}

/**
 * Full clustering pipeline. Returns { branches, trees, secondary }.
 * trees is array of arrays of arrays: trees[treeIdx][branchIdx] = pointerIds[]
 * secondary is [] unless options.secondaryThreshold is set (finite).
 */
export function computeForest(state, options = {}) {
  const threshold = options.threshold ?? 1.5;
  const maxTrees = options.maxTrees ?? 12;
  const minBranchSize = options.minBranchSize ?? 2;
  const linkage = options.linkage ?? "sum";
  const treeAffinity = options.treeAffinity ?? Infinity;
  const secondaryThreshold = options.secondaryThreshold ?? Infinity;
  const maxSecondary = options.maxSecondary ?? 2;

  const branches = clusterBranches(state, threshold, minBranchSize);
  const trees = mergeBranchesIntoTrees(branches, state, maxTrees, linkage, treeAffinity);
  const secondary = computeSecondaryMemberships(state, branches, secondaryThreshold, maxSecondary);

  return { branches, trees, secondary };
}
