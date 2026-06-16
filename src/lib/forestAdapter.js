/**
 * Transforms the get_tenant_forest() RPC response into the exact shape
 * that buildScene.js and useForestScene.js expect.
 *
 * Supabase returns:
 *   [{ id, label, subtitle, type, pos (real[]), is_seed, version,
 *      branches: [{ id, name, pointer_ids, leaves (string[]), links ([{id, why}]) }] }]
 *
 * buildScene.js expects:
 *   TREES: [{ id, label, subtitle, type, pos: [x,y,z],
 *             branches: [{ id, name, leaves: [string], links: [{id, why}] }] }]
 *   BRANCH_INDEX: { branchId: { tree, branch } }
 */

export function adaptForest(supabaseTrees) {
  if (!supabaseTrees || !Array.isArray(supabaseTrees)) {
    return { trees: [], branchIndex: {} };
  }

  const trees = supabaseTrees.map((t) => ({
    id: t.id,
    label: t.label,
    subtitle: t.subtitle,
    type: t.type,
    pos: Array.isArray(t.pos) ? t.pos : [0, 0, 0],
    branches: (t.branches || []).map((b) => ({
      id: b.id,
      name: b.name,
      leaves: Array.isArray(b.leaves) ? b.leaves : [],
      links: Array.isArray(b.links) ? b.links : [],
      // Retained so per-branch members (e.g. people) can be resolved for the
      // calendar feature; unused by buildScene.js.
      pointer_ids: Array.isArray(b.pointer_ids) ? b.pointer_ids : [],
    })),
  }));

  const branchIndex = {};
  trees.forEach((t) =>
    t.branches.forEach((b) => {
      branchIndex[b.id] = { tree: t, branch: b };
    })
  );

  return { trees, branchIndex };
}
