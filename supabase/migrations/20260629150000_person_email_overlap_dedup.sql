-- ============================================================================
-- Person dedup by email overlap (global-identity reinforcement).
-- ----------------------------------------------------------------------------
-- People are meant to be one node per human (global key `person::{email}`), but
-- different sources key the same person by different addresses (team directory by
-- their kibo address, Affinidad CRM by their primary/nzyme address, etc.). The
-- name/canonical dedup in insert_pointer_with_dedup does NOT auto-merge when two
-- non-null canonical keys differ, so each source re-creates its own node and the
-- human splits into duplicates on every sync.
--
-- This adds an email-overlap step to the *person* path of the (acl) overload of
-- insert_pointer_with_dedup: before any name/canonical matching, an incoming
-- person folds into an existing person that already carries any of its emails (or
-- is keyed on one). The survivor's email set is unioned so it stays matchable by
-- every address the human is ever seen under — making manual merges durable across
-- re-syncs. The survivor's canonical_key is kept (the established identity wins).
-- Only `person` is affected; companies (keyed by tenant+domain) are untouched.
-- ============================================================================

-- Supports the `metadata->'emails' ?| array[...]` membership probe.
create index if not exists idx_pointers_emails
  on public.pointers using gin ((metadata -> 'emails'));

create or replace function public.insert_pointer_with_dedup(
  p_label text, p_type pointer_type, p_canonical_key text DEFAULT NULL::text,
  p_metadata jsonb DEFAULT '{}'::jsonb, p_embedding vector DEFAULT NULL::vector,
  p_access_class text DEFAULT 'public'::text, p_acl uuid[] DEFAULT NULL::uuid[]
)
RETURNS jsonb
LANGUAGE plpgsql
AS $function$
DECLARE
  v_auto_merge_threshold REAL; v_review_threshold REAL; v_dupes JSONB;
  v_top_sim REAL; v_top_pointer_id UUID; v_top_canonical_key TEXT;
  v_new_id UUID; v_dupe_elem JSONB;
  v_cand_key TEXT; v_cand_label TEXT; v_flags_written INT := 0; v_acl uuid[];
  v_emails text[]; v_match_id uuid;
BEGIN
  v_acl := coalesce(p_acl, public.principals_for_class(p_access_class));

  -- ── Person identity by email overlap (runs before name/canonical dedup) ──
  -- Fold an incoming person into an existing one that already carries any of its
  -- emails (or is keyed on one). Unions the email set so the survivor remains
  -- matchable by every address; keeps the survivor's canonical_key.
  IF p_type = 'person' THEN
    SELECT coalesce(array_agg(DISTINCT e), '{}')
      INTO v_emails
    FROM (
      SELECT jsonb_array_elements_text(coalesce(p_metadata->'emails','[]'::jsonb)) AS e
      UNION
      SELECT substring(p_canonical_key from 'person::(.+)') AS e
        WHERE p_canonical_key LIKE 'person::%@%'
    ) s
    WHERE e IS NOT NULL AND e <> '';

    IF array_length(v_emails, 1) > 0 THEN
      SELECT p.id INTO v_match_id
      FROM public.pointers p
      WHERE p.type = 'person'
        AND (
          p.canonical_key = ANY (SELECT 'person::' || e FROM unnest(v_emails) e)
          OR p.metadata->'emails' ?| v_emails
        )
      ORDER BY (p.canonical_key = ANY (SELECT 'person::' || e FROM unnest(v_emails) e)) DESC,
               p.created_at ASC
      LIMIT 1;

      IF v_match_id IS NOT NULL THEN
        UPDATE public.pointers p SET
          acl = coalesce((SELECT array_agg(DISTINCT a) FROM unnest(p.acl || v_acl) a), '{}'::uuid[]),
          metadata = jsonb_set(coalesce(p.metadata,'{}'::jsonb), '{emails}',
            coalesce((SELECT jsonb_agg(DISTINCT em) FROM (
              SELECT jsonb_array_elements_text(coalesce(p.metadata->'emails','[]'::jsonb)) em
              UNION SELECT unnest(v_emails)
            ) q), '[]'::jsonb)),
          -- upgrade an email-looking label to a real name (same rule as below)
          label = CASE
            WHEN p.label ~ '@' AND p.label !~ '\s'
                 AND p_label IS NOT NULL AND btrim(p_label) <> ''
                 AND NOT (p_label ~ '@' AND p_label !~ '\s')
            THEN p_label ELSE p.label END,
          updated_at = now()
        WHERE p.id = v_match_id;
        RETURN jsonb_build_object('status','merged','pointer_id',v_match_id,'match_method','email_overlap');
      END IF;
    END IF;
  END IF;

  -- ── Existing name / canonical / embedding dedup ──
  SELECT (value)::REAL INTO v_auto_merge_threshold FROM system_config WHERE key = 'dedup_auto_merge_threshold';
  SELECT (value)::REAL INTO v_review_threshold FROM system_config WHERE key = 'dedup_review_threshold';
  v_auto_merge_threshold := COALESCE(v_auto_merge_threshold, 0.8);
  v_review_threshold := COALESCE(v_review_threshold, 0.4);
  SELECT jsonb_agg(jsonb_build_object(
    'pointer_id', d.pointer_id, 'label', d.pointer_label, 'match_method', d.match_method,
    'trigram_score', d.trigram_sim, 'embedding_score', d.embedding_sim, 'similarity', d.combined_sim
  )) INTO v_dupes
  FROM check_duplicates(p_label, p_type, p_canonical_key, p_embedding, v_review_threshold) d;
  IF v_dupes IS NULL OR jsonb_array_length(v_dupes) = 0 THEN
    INSERT INTO pointers (label, type, canonical_key, metadata, embedding, acl)
    VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding, v_acl)
    RETURNING id INTO v_new_id;
    RETURN jsonb_build_object('status', 'created', 'pointer_id', v_new_id, 'access_class', COALESCE(p_access_class, 'public'), 'duplicates', '[]'::jsonb);
  END IF;
  SELECT (elem->>'similarity')::REAL, (elem->>'pointer_id')::UUID
  INTO v_top_sim, v_top_pointer_id
  FROM jsonb_array_elements(v_dupes) AS elem
  ORDER BY (elem->>'similarity')::REAL DESC LIMIT 1;
  SELECT canonical_key INTO v_top_canonical_key FROM pointers WHERE id = v_top_pointer_id;
  IF v_top_sim >= v_auto_merge_threshold
     AND NOT (p_canonical_key IS NOT NULL AND v_top_canonical_key IS NOT NULL AND p_canonical_key <> v_top_canonical_key)
  THEN
    UPDATE pointers
       SET acl = COALESCE((SELECT array_agg(DISTINCT e) FROM unnest(pointers.acl || v_acl) e), '{}'::uuid[]),
           updated_at = now()
     WHERE id = v_top_pointer_id;
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
  INSERT INTO pointers (label, type, canonical_key, metadata, embedding, acl)
  VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding, v_acl)
  RETURNING id INTO v_new_id;
  FOR v_dupe_elem IN SELECT * FROM jsonb_array_elements(v_dupes)
  LOOP
    SELECT canonical_key, label INTO v_cand_key, v_cand_label FROM pointers WHERE id = (v_dupe_elem->>'pointer_id')::UUID;
    CONTINUE WHEN p_canonical_key IS NOT NULL
              AND v_cand_key IS NOT NULL
              AND p_canonical_key <> v_cand_key
              AND NOT (
                p_type = 'person'
                AND v_cand_label IS NOT NULL
                AND lower(btrim(p_label)) = lower(btrim(v_cand_label))
                AND btrim(p_label) ~ '\s'
              );
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
