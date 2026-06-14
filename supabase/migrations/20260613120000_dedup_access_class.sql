-- ============================================================================
-- Phase 2: access-class awareness in the single insert contract.
--   1. insert_pointer_with_dedup now accepts p_access_class (a class KEY, e.g.
--      'confidential') and stamps it onto the pointer on create / review.
--   2. Cross-class auto-merge guard: a candidate whose access class differs from
--      its top match does NOT auto-merge — it falls to pending_review, the same
--      way a canonical_key conflict does. This prevents a confidential pointer
--      from being silently collapsed into a public one (or vice-versa).
--      Exception: if both sides share the same non-null canonical_key they are
--      the same identity, so enrichment still merges (class is left unchanged).
-- ============================================================================

DROP FUNCTION IF EXISTS public.insert_pointer_with_dedup(text, pointer_type, text, jsonb, vector);

CREATE OR REPLACE FUNCTION public.insert_pointer_with_dedup(
  p_label text,
  p_type pointer_type,
  p_canonical_key text DEFAULT NULL::text,
  p_metadata jsonb DEFAULT '{}'::jsonb,
  p_embedding vector DEFAULT NULL::vector,
  p_access_class text DEFAULT 'public'
)
RETURNS jsonb
LANGUAGE plpgsql
AS $function$
DECLARE
  v_auto_merge_threshold REAL;
  v_review_threshold REAL;
  v_dupes JSONB;
  v_top_sim REAL;
  v_top_pointer_id UUID;
  v_top_canonical_key TEXT;
  v_top_access_class UUID;
  v_new_id UUID;
  v_dupe_elem JSONB;
  v_class_id UUID;
  v_same_identity BOOLEAN;
BEGIN
  SELECT (value)::REAL INTO v_auto_merge_threshold
  FROM system_config WHERE key = 'dedup_auto_merge_threshold';
  SELECT (value)::REAL INTO v_review_threshold
  FROM system_config WHERE key = 'dedup_review_threshold';

  v_auto_merge_threshold := COALESCE(v_auto_merge_threshold, 0.8);
  v_review_threshold := COALESCE(v_review_threshold, 0.4);

  -- Resolve the access class key to its id; default/fallback to public.
  SELECT id INTO v_class_id FROM access_classes WHERE key = COALESCE(p_access_class, 'public');
  v_class_id := COALESCE(v_class_id, '00000000-0000-0000-0000-000000000001');

  SELECT jsonb_agg(jsonb_build_object(
    'pointer_id', d.pointer_id,
    'label', d.pointer_label,
    'match_method', d.match_method,
    'trigram_score', d.trigram_sim,
    'embedding_score', d.embedding_sim,
    'similarity', d.combined_sim
  ))
  INTO v_dupes
  FROM check_duplicates(p_label, p_type, p_canonical_key, p_embedding, v_review_threshold) d;

  -- No duplicates: clean insert
  IF v_dupes IS NULL OR jsonb_array_length(v_dupes) = 0 THEN
    INSERT INTO pointers (label, type, canonical_key, metadata, embedding, access_class_id)
    VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding, v_class_id)
    RETURNING id INTO v_new_id;

    RETURN jsonb_build_object(
      'status', 'created',
      'pointer_id', v_new_id,
      'access_class', COALESCE(p_access_class, 'public'),
      'duplicates', '[]'::jsonb
    );
  END IF;

  SELECT
    (elem->>'similarity')::REAL,
    (elem->>'pointer_id')::UUID
  INTO v_top_sim, v_top_pointer_id
  FROM jsonb_array_elements(v_dupes) AS elem
  ORDER BY (elem->>'similarity')::REAL DESC
  LIMIT 1;

  SELECT canonical_key, access_class_id
  INTO v_top_canonical_key, v_top_access_class
  FROM pointers WHERE id = v_top_pointer_id;

  v_same_identity := (
    p_canonical_key IS NOT NULL
    AND v_top_canonical_key IS NOT NULL
    AND p_canonical_key = v_top_canonical_key
  );

  -- AUTO-MERGE: above threshold, and NOT a canonical_key conflict, and either
  -- the same declared identity (same canonical_key -> enrichment) or the same
  -- access class. A class mismatch on a mere lookalike blocks the merge.
  IF v_top_sim >= v_auto_merge_threshold
     AND NOT (
       p_canonical_key IS NOT NULL
       AND v_top_canonical_key IS NOT NULL
       AND p_canonical_key <> v_top_canonical_key
     )
     AND (v_same_identity OR v_class_id = v_top_access_class)
  THEN
    RETURN jsonb_build_object(
      'status', 'merged',
      'pointer_id', v_top_pointer_id,
      'duplicates', v_dupes
    );
  END IF;

  -- BLOCK FOR REVIEW: review-range match, canonical_key conflict, or class mismatch
  INSERT INTO pointers (label, type, canonical_key, metadata, embedding, access_class_id)
  VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding, v_class_id)
  RETURNING id INTO v_new_id;

  FOR v_dupe_elem IN SELECT * FROM jsonb_array_elements(v_dupes)
  LOOP
    INSERT INTO duplicate_flags (
      pointer_id_a, pointer_id_b, similarity_score, trigram_score, embedding_score,
      match_method, resolution
    ) VALUES (
      LEAST(v_new_id, (v_dupe_elem->>'pointer_id')::UUID),
      GREATEST(v_new_id, (v_dupe_elem->>'pointer_id')::UUID),
      (v_dupe_elem->>'similarity')::REAL,
      (v_dupe_elem->>'trigram_score')::REAL,
      (v_dupe_elem->>'embedding_score')::REAL,
      v_dupe_elem->>'match_method',
      'pending'
    ) ON CONFLICT DO NOTHING;
  END LOOP;

  RETURN jsonb_build_object(
    'status', 'pending_review',
    'pointer_id', v_new_id,
    'access_class', COALESCE(p_access_class, 'public'),
    'duplicates', v_dupes
  );
END;
$function$;