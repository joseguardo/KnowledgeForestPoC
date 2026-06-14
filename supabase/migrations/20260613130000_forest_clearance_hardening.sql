-- ============================================================================
-- Leak hardening for the forest skeleton.
-- get_tenant_forest is SECURITY INVOKER, so its leaves (attributes_kv) and links
-- (edges) are already RLS-gated per caller. But the tenant_trees / tenant_branches
-- *structure* is not class-tagged, so a branch whose every pointer is restricted
-- would still appear as an empty husk (with a possibly revealing name) to an
-- uncleared caller. This drops any branch with no readable leaves AND no readable
-- links, and any tree left with no branches — so the skeleton reflects clearance.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_tenant_forest(p_tenant_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_result JSONB;
BEGIN
  SELECT jsonb_agg(tree_obj ORDER BY created_at) INTO v_result
  FROM (
    SELECT jsonb_build_object(
      'id', t.id,
      'label', COALESCE(t.name, 'Unnamed Tree'),
      'subtitle', COALESCE(t.subtitle, t.name, 'Tree'),
      'type', t.type,
      'pos', t.pos,
      'is_seed', t.is_seed,
      'version', t.version,
      'branches', br.branches
    ) AS tree_obj,
    t.created_at
    FROM tenant_trees t
    CROSS JOIN LATERAL (
      SELECT COALESCE(jsonb_agg(bsub.branch_obj), '[]'::jsonb) AS branches
      FROM (
        SELECT jsonb_build_object(
          'id', b.id,
          'name', COALESCE(b.name, 'Unnamed Branch'),
          'pointer_ids', b.pointer_ids,
          'leaves', ll.leaves,
          'links', ll.links
        ) AS branch_obj
        FROM tenant_branches b
        CROSS JOIN LATERAL (
          SELECT
            COALESCE((
              SELECT jsonb_agg(a.key || ': ' || (a.value #>> '{}') ORDER BY a.sort_order)
              FROM attributes_kv a
              WHERE a.pointer_id = ANY(b.pointer_ids)
            ), '[]'::jsonb) AS leaves,
            COALESCE((
              SELECT jsonb_agg(jsonb_build_object('id', e.target_id, 'why', e.why))
              FROM edges e
              WHERE e.source_id = ANY(b.pointer_ids)
                AND NOT (e.target_id = ANY(b.pointer_ids))
            ), '[]'::jsonb) AS links
        ) ll
        WHERE b.tree_id = t.id
          -- drop branches with nothing readable at the caller's clearance
          AND (jsonb_array_length(ll.leaves) > 0 OR jsonb_array_length(ll.links) > 0)
      ) bsub
    ) br
    WHERE t.tenant_id = p_tenant_id
      -- drop trees left with no visible branches
      AND jsonb_array_length(br.branches) > 0
  ) sub;

  RETURN COALESCE(v_result, '[]'::jsonb);
END;
$function$;