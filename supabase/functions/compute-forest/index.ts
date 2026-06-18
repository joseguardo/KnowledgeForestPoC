import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

// --- Union-Find ---
class UnionFind {
  parent: Map<string, string> = new Map();
  rank: Map<string, number> = new Map();

  find(x: string): string {
    if (!this.parent.has(x)) {
      this.parent.set(x, x);
      this.rank.set(x, 0);
    }
    if (this.parent.get(x) !== x) {
      this.parent.set(x, this.find(this.parent.get(x)!));
    }
    return this.parent.get(x)!;
  }

  union(a: string, b: string): void {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra === rb) return;
    const rankA = this.rank.get(ra)!;
    const rankB = this.rank.get(rb)!;
    if (rankA < rankB) this.parent.set(ra, rb);
    else if (rankA > rankB) this.parent.set(rb, ra);
    else { this.parent.set(rb, ra); this.rank.set(ra, rankA + 1); }
  }

  components(): Map<string, string[]> {
    const groups = new Map<string, string[]>();
    for (const node of this.parent.keys()) {
      const root = this.find(node);
      if (!groups.has(root)) groups.set(root, []);
      groups.get(root)!.push(node);
    }
    return groups;
  }
}

// --- Tree position layout ---
function computeTreePositions(count: number): number[][] {
  const radius = 20 + count * 2;
  const positions: number[][] = [];
  for (let i = 0; i < count; i++) {
    const angle = (i / count) * Math.PI * 2;
    positions.push([
      Math.cos(angle) * radius,
      0,
      Math.sin(angle) * radius,
    ]);
  }
  return positions;
}

// --- LLM Naming ---
async function nameClusters(
  clusters: { pointerLabels: string[] }[],
  level: "branch" | "tree"
): Promise<string[]> {
  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey) {
    return clusters.map((_, i) => `${level === "tree" ? "Tree" : "Branch"} ${i + 1}`);
  }

  try {
    const prompt = clusters.map((c, i) =>
      `${i + 1}. [${c.pointerLabels.slice(0, 10).join(", ")}]`
    ).join("\n");

    const res = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${openaiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: [
          {
            role: "system",
            content: `You name groups of related items. For each numbered group, provide a short (2-4 word) ${level} name that captures what the items have in common. Respond with ONLY a JSON array of strings, one name per group. No explanation.`,
          },
          { role: "user", content: prompt },
        ],
        temperature: 0.3,
      }),
    });

    if (!res.ok) {
      console.error("Naming API error:", await res.text());
      return clusters.map((_, i) => `${level === "tree" ? "Tree" : "Branch"} ${i + 1}`);
    }

    const data = await res.json();
    const content = data.choices[0].message.content.trim();
    const names = JSON.parse(content);
    return names;
  } catch (err) {
    console.error("Naming failed:", err);
    return clusters.map((_, i) => `${level === "tree" ? "Tree" : "Branch"} ${i + 1}`);
  }
}

interface ComputeForestRequest {
  tenant_id: string;
  job_id?: string;
  weight_threshold?: number;
  min_branch_size?: number;
  max_trees?: number;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, serviceRoleKey);

    const body: ComputeForestRequest = await req.json();
    const tenantId = body.tenant_id;
    const WEIGHT_THRESHOLD = body.weight_threshold ?? 2.0;
    const MIN_BRANCH_SIZE = body.min_branch_size ?? 2;
    const MAX_TREES = body.max_trees ?? 12;

    if (!tenantId) {
      return new Response(
        JSON.stringify({ error: "tenant_id is required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // Mark job as running
    if (body.job_id) {
      await supabase
        .from("forest_computation_jobs")
        .update({ status: "running", started_at: new Date().toISOString() })
        .eq("id", body.job_id);
    }

    // 1. Fetch co-access edges above threshold
    const { data: edges, error: edgesError } = await supabase
      .from("tenant_coaccess")
      .select("pointer_a, pointer_b, proximity_weight")
      .eq("tenant_id", tenantId)
      .gte("proximity_weight", WEIGHT_THRESHOLD);

    if (edgesError) throw new Error(`Failed to fetch co-access: ${edgesError.message}`);

    if (!edges || edges.length === 0) {
      const result = { status: "no_data", trees: 0, branches: 0 };
      if (body.job_id) {
        await supabase
          .from("forest_computation_jobs")
          .update({ status: "completed", completed_at: new Date().toISOString(), result_summary: result })
          .eq("id", body.job_id);
      }
      return new Response(JSON.stringify(result), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    // 2. Union-Find clustering -> branches
    const uf = new UnionFind();
    for (const edge of edges) {
      uf.union(edge.pointer_a, edge.pointer_b);
    }
    const components = uf.components();
    const branches = [...components.values()].filter(c => c.length >= MIN_BRANCH_SIZE);

    if (branches.length === 0) {
      const result = { status: "no_branches", trees: 0, branches: 0 };
      if (body.job_id) {
        await supabase
          .from("forest_computation_jobs")
          .update({ status: "completed", completed_at: new Date().toISOString(), result_summary: result })
          .eq("id", body.job_id);
      }
      return new Response(JSON.stringify(result), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    // 3. Build branch-level adjacency for hierarchical merge
    const pointerToBranch = new Map<string, number>();
    branches.forEach((ptrs, idx) => ptrs.forEach(p => pointerToBranch.set(p, idx)));

    const branchWeights = new Map<string, number>();
    for (const edge of edges) {
      const bi = pointerToBranch.get(edge.pointer_a);
      const bj = pointerToBranch.get(edge.pointer_b);
      if (bi === undefined || bj === undefined || bi === bj) continue;
      const key = `${Math.min(bi, bj)}-${Math.max(bi, bj)}`;
      branchWeights.set(key, (branchWeights.get(key) || 0) + edge.proximity_weight);
    }

    // 4. Greedy agglomerative merge into trees
    let treeBranches = branches.map((_: string[], i: number) => [i]);

    while (treeBranches.length > MAX_TREES) {
      let bestPair = [-1, -1];
      let bestWeight = 0;

      for (let i = 0; i < treeBranches.length; i++) {
        for (let j = i + 1; j < treeBranches.length; j++) {
          let w = 0;
          for (const bi of treeBranches[i]) {
            for (const bj of treeBranches[j]) {
              const key = `${Math.min(bi, bj)}-${Math.max(bi, bj)}`;
              w += branchWeights.get(key) || 0;
            }
          }
          if (w > bestWeight) { bestWeight = w; bestPair = [i, j]; }
        }
      }

      if (bestWeight === 0) break;
      treeBranches[bestPair[0]] = [...treeBranches[bestPair[0]], ...treeBranches[bestPair[1]]];
      treeBranches.splice(bestPair[1], 1);
    }

    // 5. Fetch pointer labels for naming
    const allPointerIds = branches.flat();
    const { data: pointerData } = await supabase
      .from("pointers")
      .select("id, label")
      .in("id", allPointerIds);

    const labelMap = new Map<string, string>();
    for (const p of pointerData || []) {
      labelMap.set(p.id, p.label);
    }

    // 6. Fetch old branches for stability mapping
    const { data: oldBranches } = await supabase
      .from("tenant_branches")
      .select("id, pointer_ids")
      .eq("tenant_id", tenantId);

    // 7. LLM naming for branches
    const branchNamingInput = branches.map(ptrs => ({
      pointerLabels: ptrs.map(p => labelMap.get(p) || "unknown"),
    }));
    const branchNames = await nameClusters(branchNamingInput, "branch");

    // 8. LLM naming for trees
    const treeNamingInput = treeBranches.map((bIdxs: number[]) => ({
      pointerLabels: bIdxs.flatMap((bi: number) =>
        branches[bi].map(p => labelMap.get(p) || "unknown")
      ),
    }));
    const treeNames = await nameClusters(treeNamingInput, "tree");

    // 9. Delete old structure for this tenant
    await supabase.from("tenant_pointer_assignments").delete().eq("tenant_id", tenantId);
    await supabase.from("tenant_branches").delete().eq("tenant_id", tenantId);
    await supabase.from("tenant_trees").delete().eq("tenant_id", tenantId);

    // 10. Insert new trees
    const treePositions = computeTreePositions(treeBranches.length);
    const treeRows = treeBranches.map((_, ti: number) => ({
      tenant_id: tenantId,
      name: treeNames[ti] || `Tree ${ti + 1}`,
      subtitle: treeNames[ti] || `Tree ${ti + 1}`,
      type: "entity",
      pos: treePositions[ti],
      is_seed: false,
      version: 1,
    }));

    const { data: newTrees, error: treeErr } = await supabase
      .from("tenant_trees")
      .insert(treeRows)
      .select("id");

    if (treeErr) throw new Error(`Tree insert failed: ${treeErr.message}`);

    // 11. Insert new branches
    const branchRows: any[] = [];
    for (let ti = 0; ti < treeBranches.length; ti++) {
      for (const bi of treeBranches[ti]) {
        branchRows.push({
          tenant_id: tenantId,
          tree_id: newTrees![ti].id,
          name: branchNames[bi] || `Branch ${bi + 1}`,
          pointer_ids: branches[bi],
          version: 1,
        });
      }
    }

    const { data: newBranches, error: branchErr } = await supabase
      .from("tenant_branches")
      .insert(branchRows)
      .select("id, pointer_ids, tree_id");

    if (branchErr) throw new Error(`Branch insert failed: ${branchErr.message}`);

    // 12. Insert pointer assignments
    const assignments: any[] = [];
    for (const b of newBranches!) {
      for (const pid of b.pointer_ids) {
        assignments.push({
          tenant_id: tenantId,
          pointer_id: pid,
          branch_id: b.id,
          tree_id: b.tree_id,
        });
      }
    }
    if (assignments.length > 0) {
      await supabase.from("tenant_pointer_assignments").insert(assignments);
    }

    // 13. Stability mapping (Jaccard old->new)
    if (oldBranches && oldBranches.length > 0) {
      const mappings: any[] = [];
      const events: any[] = [];

      for (const oldB of oldBranches) {
        const oldSet = new Set(oldB.pointer_ids);
        let bestMatch: any = null;
        let bestJaccard = 0;

        for (const newB of newBranches!) {
          const newSet = new Set(newB.pointer_ids);
          const intersection = [...oldSet].filter(p => newSet.has(p)).length;
          const union = new Set([...oldSet, ...newSet]).size;
          const jaccard = union > 0 ? intersection / union : 0;
          if (jaccard > bestJaccard) { bestJaccard = jaccard; bestMatch = newB; }
        }

        if (bestMatch && bestJaccard > 0.3) {
          mappings.push({
            tenant_id: tenantId,
            entity_type: "branch",
            old_id: oldB.id,
            new_id: bestMatch.id,
            overlap_ratio: bestJaccard,
          });
        }
      }

      if (mappings.length > 0) {
        await supabase.from("tenant_structure_mapping").insert(mappings);
      }

      // Emit structure_evolved event if significant changes
      if (oldBranches.length !== newBranches!.length || mappings.some(m => m.overlap_ratio < 0.8)) {
        await supabase.from("tenant_structure_events").insert({
          tenant_id: tenantId,
          event_type: "structure_evolved",
          details: {
            old_branches: oldBranches.length,
            new_branches: newBranches!.length,
            new_trees: newTrees!.length,
            avg_overlap: mappings.length > 0
              ? mappings.reduce((s, m) => s + m.overlap_ratio, 0) / mappings.length
              : 0,
          },
        });
      }
    }

    // 14. Mark job completed
    const resultSummary = {
      status: "completed",
      trees_count: newTrees!.length,
      branches_count: newBranches!.length,
      pointers_assigned: assignments.length,
    };

    if (body.job_id) {
      await supabase
        .from("forest_computation_jobs")
        .update({
          status: "completed",
          completed_at: new Date().toISOString(),
          result_summary: resultSummary,
        })
        .eq("id", body.job_id);
    }

    return new Response(
      JSON.stringify(resultSummary),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    // Mark job as failed
    try {
      const body = await req.clone().json().catch(() => ({}));
      if (body.job_id) {
        const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
        const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
        const supabase = createClient(supabaseUrl, serviceRoleKey);
        await supabase
          .from("forest_computation_jobs")
          .update({ status: "failed", error_message: err.message })
          .eq("id", body.job_id);
      }
    } catch (_) { /* best effort */ }

    return new Response(
      JSON.stringify({ error: err.message }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
