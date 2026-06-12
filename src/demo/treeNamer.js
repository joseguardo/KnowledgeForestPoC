/**
 * Deterministic naming for branches and trees based on member pointer labels/types.
 * No LLM needed — uses heuristics.
 */
import { POINTER_MAP } from "./demoGraph.js";

function mode(arr) {
  const counts = {};
  let maxCount = 0;
  let maxItem = arr[0];
  for (const item of arr) {
    counts[item] = (counts[item] || 0) + 1;
    if (counts[item] > maxCount) {
      maxCount = counts[item];
      maxItem = item;
    }
  }
  return maxItem;
}

/**
 * Name a branch from its member pointer IDs.
 */
export function nameBranch(pointerIds) {
  if (pointerIds.length === 0) return "Empty";
  if (pointerIds.length === 1) {
    return POINTER_MAP[pointerIds[0]]?.label || pointerIds[0];
  }

  const ptrs = pointerIds.map((id) => POINTER_MAP[id]).filter(Boolean);
  const types = ptrs.map((p) => p.type);
  const dominantType = mode(types);

  // If all same type, use the first label
  if (types.every((t) => t === dominantType)) {
    return ptrs[0].label;
  }

  // Priority: prefer the most specific/recognizable entity as the branch name
  const priority = [
    "company",
    "person",
    "regulation",
    "sector",
    "geography",
    "flow",
    "agent",
    "component",
    "skill",
    "tool",
    "architecture",
    "best_practice",
    "meta",
  ];

  for (const pType of priority) {
    const match = ptrs.find((p) => p.type === pType);
    if (match) return match.label;
  }

  return ptrs[0].label;
}

/**
 * Name a tree from its branches.
 * treeData: array of branches, each is { name, pointerIds }
 */
export function nameTree(branches) {
  if (branches.length === 0) return "Empty Tree";
  if (branches.length === 1) return branches[0].name;

  // Collect all pointer types across branches
  const allPtrs = branches.flatMap((b) =>
    b.pointerIds.map((id) => POINTER_MAP[id]).filter(Boolean)
  );
  const types = allPtrs.map((p) => p.type);
  const dominantType = mode(types);

  // Group labels by type
  const typeLabels = {};
  for (const p of allPtrs) {
    if (!typeLabels[p.type]) typeLabels[p.type] = [];
    typeLabels[p.type].push(p.label);
  }

  // If the tree mixes entity and system types, use dominant
  const entityTypes = new Set([
    "company", "person", "sector", "geography", "regulation",
  ]);
  const hasEntity = types.some((t) => entityTypes.has(t));
  const hasSystem = types.some((t) => !entityTypes.has(t));

  if (hasEntity && hasSystem) {
    // Mixed: use the most prominent entity label
    const entityPtrs = allPtrs.filter((p) => entityTypes.has(p.type));
    if (entityPtrs.length > 0) return entityPtrs[0].label + " Ecosystem";
    return branches[0].name + " & Related";
  }

  if (hasEntity) {
    // All entity: use the sector or geography as the umbrella
    if (typeLabels["sector"]) return typeLabels["sector"][0];
    if (typeLabels["geography"]) return typeLabels["geography"][0];
    if (typeLabels["regulation"]) return typeLabels["regulation"][0];
    return branches[0].name;
  }

  // All system: use the architectural or component umbrella
  if (typeLabels["architecture"]) return typeLabels["architecture"][0];
  if (typeLabels["component"]) return typeLabels["component"][0];
  if (typeLabels["flow"]) return typeLabels["flow"][0] + " Pipeline";

  return branches[0].name;
}
