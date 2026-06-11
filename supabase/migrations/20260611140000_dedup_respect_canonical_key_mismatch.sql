-- Fix surfaced by ingestion audit: two pointers with DIFFERENT non-null
-- canonical_keys are declared distinct identities and must never auto-merge,
-- regardless of label/embedding similarity ("Batch Testco Alpha" vs
-- "Batch Testco Beta" merged at sim 0.8+). Such pairs now fall through to
-- the pending_review path instead.
CREATE OR REPLACE FUNCTION public.insert_pointer_with_dedup(
  p_label text,
  p_type pointer_type,
  p_canonical_key text DEFAULT NULL::text,
  p_metadata jsonb DEFAULT '{}'::jsonb,
  p_embedding vector DEFAULT NULL::vector
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
  v_new_id UUID;
  v_dupe_elem JSONB;
BEGIN
  -- Read adaptive thresholds
  SELECT (value)::REAL INTO v_auto_merge_threshold
  FROM system_config WHERE key = 'dedup_auto_merge_threshold';
  SELECT (value)::REAL INTO v_review_threshold
  FROM system_config WHERE key = 'dedup_review_threshold';

  v_auto_merge_threshold := COALESCE(v_auto_merge_threshold, 0.8);
  v_review_threshold := COALESCE(v_review_threshold, 0.4);

  -- Check for duplicates
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
    INSERT INTO pointers (label, type, canonical_key, metadata, embedding)
    VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding)
    RETURNING id INTO v_new_id;

    RETURN jsonb_build_object(
      'status', 'created',
      'pointer_id', v_new_id,
      'duplicates', '[]'::jsonb
    );
  END IF;

  -- Get top match score and ID
  SELECT
    (elem->>'similarity')::REAL,
    (elem->>'pointer_id')::UUID
  INTO v_top_sim, v_top_pointer_id
  FROM jsonb_array_elements(v_dupes) AS elem
  ORDER BY (elem->>'similarity')::REAL DESC
  LIMIT 1;

  SELECT canonical_key INTO v_top_canonical_key
  FROM pointers WHERE id = v_top_pointer_id;

  -- AUTO-MERGE: top match above threshold, unless both sides carry
  -- different non-null canonical_keys (declared distinct identities).
  IF v_top_sim >= v_auto_merge_threshold
     AND NOT (
       p_canonical_key IS NOT NULL
       AND v_top_canonical_key IS NOT NULL
       AND p_canonical_key <> v_top_canonical_key
     )
  THEN
    RETURN jsonb_build_object(
      'status', 'merged',
      'pointer_id', v_top_pointer_id,
      'duplicates', v_dupes
    );
  END IF;

  -- BLOCK FOR REVIEW: matches in review range (or canonical_key conflict)
  INSERT INTO pointers (label, type, canonical_key, metadata, embedding)
  VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding)
  RETURNING id INTO v_new_id;

  -- Flag each duplicate pair
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
    'duplicates', v_dupes
  );
END;
$function$;
