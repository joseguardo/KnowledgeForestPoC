/**
 * Runs the full simulation: feeds 200 queries into the co-access engine,
 * snapshots at 7 checkpoints, computes diffs between checkpoints.
 *
 * Produces the data that drives the demo animation.
 */
import { POINTERS, POINTER_MAP, EDGES } from "./knowledgeGraph";
import { NZYME_QUERIES } from "./queryGenerator";
import {
  createCoAccessState,
  addPathToMatrix,
  getEdges,
  computeForest,
} from "./coAccessEngine";
import { nameBranch, nameTree } from "./treeNamer";

// Checkpoint schedule: after N queries
const CHECKPOINT_INDICES = [0, 15, 35, 70, 120, 170, 200];

/**
 * Compute circular tree positions.
 */
function computeTreePositions(count) {
  if (count === 0) return [];
  const radius = 18 + count * 1.5;
  return Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * Math.PI * 2;
    return [
      Math.cos(angle) * radius,
      0,
      Math.sin(angle) * radius,
    ];
  });
}

/**
 * Convert clustering output to the TREES-compatible shape for buildScene.js.
 * trees: array of arrays of arrays (trees[treeIdx][branchIdxInTree] = pointerIds[])
 * branches: flat array of pointerIds[]
 */
function formatForScene(trees, branches, coAccessState, threshold) {
  const positions = computeTreePositions(trees.length);
  const coEdges = getEdges(coAccessState, threshold);

  return trees.map((treeBranches, ti) => {
    const formattedBranches = treeBranches.map((branchPointerIds) => {
      const name = nameBranch(branchPointerIds);

      // Collect leaves (attributes) from all pointers in this branch
      const leaves = branchPointerIds.flatMap((pid) => {
        const ptr = POINTER_MAP[pid];
        return ptr ? ptr.leaves : [];
      });

      // Collect outbound links (edges to pointers outside this branch)
      const branchSet = new Set(branchPointerIds);
      const links = [];
      for (const edge of EDGES) {
        if (
          branchSet.has(edge.source) &&
          !branchSet.has(edge.target)
        ) {
          links.push({ id: edge.target, why: edge.why });
        }
      }

      return {
        id: `branch:${[...branchPointerIds].sort().join("+")}`,
        name,
        pointerIds: branchPointerIds,
        leaves,
        links,
      };
    });

    const treeLabel = nameTree(formattedBranches);

    // Determine type: entity if most pointers are entity types
    const allTypes = treeBranches
      .flat()
      .map((pid) => POINTER_MAP[pid]?.type)
      .filter(Boolean);
    const entityTypes = new Set([
      "company", "person", "sector", "geography", "regulation",
    ]);
    const entityCount = allTypes.filter((t) => entityTypes.has(t)).length;
    const type = entityCount > allTypes.length / 2 ? "entity" : "system";

    return {
      id: `tree:${ti}`,
      label: treeLabel.toUpperCase(),
      subtitle: treeLabel,
      type,
      pos: positions[ti],
      branches: formattedBranches,
    };
  });
}

/**
 * Compute diff between two checkpoint states.
 */
function computeDiff(prevTrees, newTrees) {
  const prevBranchIds = new Set(
    (prevTrees || []).flatMap((t) => t.branches.map((b) => b.id))
  );
  const newBranchIds = new Set(
    newTrees.flatMap((t) => t.branches.map((b) => b.id))
  );

  const newBranches = [...newBranchIds].filter((id) => !prevBranchIds.has(id));
  const removedBranches = [...prevBranchIds].filter(
    (id) => !newBranchIds.has(id)
  );

  // Track pointer movements
  const prevPointerToBranch = {};
  for (const t of prevTrees || []) {
    for (const b of t.branches) {
      for (const pid of b.pointerIds) {
        prevPointerToBranch[pid] = b.id;
      }
    }
  }

  const movedPointers = [];
  for (const t of newTrees) {
    for (const b of t.branches) {
      for (const pid of b.pointerIds) {
        const prevBranch = prevPointerToBranch[pid];
        if (prevBranch && prevBranch !== b.id) {
          movedPointers.push({
            pointerId: pid,
            fromBranch: prevBranch,
            toBranch: b.id,
          });
        }
      }
    }
  }

  const prevTreeIds = new Set((prevTrees || []).map((t) => t.id));
  const newTreeIds = new Set(newTrees.map((t) => t.id));

  return {
    newBranches,
    removedBranches,
    movedPointers,
    newTrees: [...newTreeIds].filter((id) => !prevTreeIds.has(id)),
    removedTrees: [...prevTreeIds].filter((id) => !newTreeIds.has(id)),
  };
}

/**
 * Generate all checkpoints for the demo simulation.
 */
export function generateCheckpoints(
  queries = NZYME_QUERIES,
  options = {}
) {
  const threshold = options.threshold ?? 1.5;
  const maxTrees = options.maxTrees ?? 12;

  const state = createCoAccessState();
  const checkpoints = [];
  const allPointerIds = POINTERS.map((p) => p.id);
  let prevTrees = null;

  for (const cpIndex of CHECKPOINT_INDICES) {
    // Feed queries up to this checkpoint
    while (state.pathCount < cpIndex && state.pathCount < queries.length) {
      addPathToMatrix(state, queries[state.pathCount].pointerIds);
    }

    // Compute clustering
    const { branches, trees } = computeForest(state, {
      threshold,
      maxTrees,
    });

    // Format for scene
    const formattedTrees = cpIndex === 0
      ? []
      : formatForScene(trees, branches, state, threshold);

    // Find unassigned pointers
    const assignedIds = new Set(
      formattedTrees.flatMap((t) =>
        t.branches.flatMap((b) => b.pointerIds)
      )
    );
    const unassignedPointers = allPointerIds.filter(
      (id) => !assignedIds.has(id)
    );

    // Co-access edges for visualization
    const coAccessEdges = getEdges(state, threshold);

    // Diff from previous
    const diff = computeDiff(prevTrees, formattedTrees);

    checkpoints.push({
      queryIndex: cpIndex,
      trees: formattedTrees,
      unassignedPointers,
      coAccessEdges,
      diff,
      stats: {
        treeCount: formattedTrees.length,
        branchCount: formattedTrees.reduce(
          (sum, t) => sum + t.branches.length,
          0
        ),
        assignedPointers: assignedIds.size,
        totalPointers: allPointerIds.length,
        totalCoAccessEdges: coAccessEdges.length,
        edgesAboveThreshold: coAccessEdges.filter((e) => e.aboveThreshold)
          .length,
      },
    });

    prevTrees = formattedTrees;
  }

  return checkpoints;
}
