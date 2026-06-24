-- Upgrade a placeholder email label to a real name on merge.
--
-- Person nodes are created by whichever source sees the address first. When that
-- first sight has no display name, the label is the bare email (e.g.
-- "matthias.kirsten@nzyme.com"). Later sights that DO carry a real name — a
-- subsequent email, or the CRM's full_name (Affinidad ingests the same
-- person::<tenant>::<email> node) — previously couldn't fix it: the `merged`
-- branch returns the existing pointer untouched (first writer wins).
--
-- Change: in the `merged` branch only, if the incoming pointer is a person whose
-- label is a real name and the stored label is a bare email, upgrade the stored
-- label. Never downgrades (only acts when the stored label looks like an email);
-- source-agnostic (CRM full_name and email display names both flow through here).
-- Everything else — thresholds, check_duplicates, the no-dupes path, the
-- flag-writing loop with its declared-distinct skip — is unchanged.
create or replace function public.insert_pointer_with_dedup(
  p_label text,
  p_type pointer_type,
  p_canonical_key text default null::text,
  p_metadata jsonb default '{}'::jsonb,
  p_embedding vector default null::vector,
  p_access_class text default 'public'::text
)
returns jsonb
language plpgsql
as $function$
DECLARE
  v_auto_merge_threshold REAL; v_review_threshold REAL; v_dupes JSONB;
  v_top_sim REAL; v_top_pointer_id UUID; v_top_canonical_key TEXT;
  v_top_access_class UUID; v_new_id UUID; v_dupe_elem JSONB; v_class_id UUID; v_same_identity BOOLEAN;
  v_cand_key TEXT; v_flags_written INT := 0;
BEGIN
  SELECT (value)::REAL INTO v_auto_merge_threshold FROM system_config WHERE key = 'dedup_auto_merge_threshold';
  SELECT (value)::REAL INTO v_review_threshold FROM system_config WHERE key = 'dedup_review_threshold';
  v_auto_merge_threshold := COALESCE(v_auto_merge_threshold, 0.8);
  v_review_threshold := COALESCE(v_review_threshold, 0.4);
  SELECT id INTO v_class_id FROM access_classes WHERE key = COALESCE(p_access_class, 'public');
  v_class_id := COALESCE(v_class_id, '00000000-0000-0000-0000-000000000001');
  SELECT jsonb_agg(jsonb_build_object(
    'pointer_id', d.pointer_id, 'label', d.pointer_label, 'match_method', d.match_method,
    'trigram_score', d.trigram_sim, 'embedding_score', d.embedding_sim, 'similarity', d.combined_sim
  )) INTO v_dupes
  FROM check_duplicates(p_label, p_type, p_canonical_key, p_embedding, v_review_threshold) d;
  IF v_dupes IS NULL OR jsonb_array_length(v_dupes) = 0 THEN
    INSERT INTO pointers (label, type, canonical_key, metadata, embedding, access_class_id)
    VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding, v_class_id)
    RETURNING id INTO v_new_id;
    RETURN jsonb_build_object('status', 'created', 'pointer_id', v_new_id, 'access_class', COALESCE(p_access_class, 'public'), 'duplicates', '[]'::jsonb);
  END IF;
  SELECT (elem->>'similarity')::REAL, (elem->>'pointer_id')::UUID
  INTO v_top_sim, v_top_pointer_id
  FROM jsonb_array_elements(v_dupes) AS elem
  ORDER BY (elem->>'similarity')::REAL DESC LIMIT 1;
  SELECT canonical_key, access_class_id INTO v_top_canonical_key, v_top_access_class FROM pointers WHERE id = v_top_pointer_id;
  v_same_identity := (p_canonical_key IS NOT NULL AND v_top_canonical_key IS NOT NULL AND p_canonical_key = v_top_canonical_key);
  IF v_top_sim >= v_auto_merge_threshold
     AND NOT (p_canonical_key IS NOT NULL AND v_top_canonical_key IS NOT NULL AND p_canonical_key <> v_top_canonical_key)
     AND (v_same_identity OR v_class_id = v_top_access_class)
  THEN
    -- Upgrade a bare-email placeholder label to a real name (persons only).
    IF p_type = 'person'
       AND p_label IS NOT NULL AND btrim(p_label) <> ''
       AND NOT (p_label ~ '@' AND p_label !~ '\s')
    THEN
      UPDATE pointers
         SET label = p_label, updated_at = now()
       WHERE id = v_top_pointer_id
         AND label ~ '@' AND label !~ '\s'
         AND label <> p_label;
    END IF;
    RETURN jsonb_build_object('status', 'merged', 'pointer_id', v_top_pointer_id, 'duplicates', v_dupes);
  END IF;
  INSERT INTO pointers (label, type, canonical_key, metadata, embedding, access_class_id)
  VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding, v_class_id)
  RETURNING id INTO v_new_id;
  FOR v_dupe_elem IN SELECT * FROM jsonb_array_elements(v_dupes)
  LOOP
    SELECT canonical_key INTO v_cand_key FROM pointers WHERE id = (v_dupe_elem->>'pointer_id')::UUID;
    CONTINUE WHEN p_canonical_key IS NOT NULL
              AND v_cand_key IS NOT NULL
              AND p_canonical_key <> v_cand_key;
    INSERT INTO duplicate_flags (pointer_id_a, pointer_id_b, similarity_score, trigram_score, embedding_score, match_method, resolution)
    VALUES (
      LEAST(v_new_id, (v_dupe_elem->>'pointer_id')::UUID),
      GREATEST(v_new_id, (v_dupe_elem->>'pointer_id')::UUID),
      (v_dupe_elem->>'similarity')::REAL, (v_dupe_elem->>'trigram_score')::REAL,
      (v_dupe_elem->>'embedding_score')::REAL, v_dupe_elem->>'match_method', 'pending'
    ) ON CONFLICT DO NOTHING;
    v_flags_written := v_flags_written + 1;
  END LOOP;
  RETURN jsonb_build_object(
    'status', CASE WHEN v_flags_written > 0 THEN 'pending_review' ELSE 'created' END,
    'pointer_id', v_new_id,
    'access_class', COALESCE(p_access_class, 'public'),
    'duplicates', v_dupes
  );
END;
$function$;
