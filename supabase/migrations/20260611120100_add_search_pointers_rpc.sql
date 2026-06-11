CREATE OR REPLACE FUNCTION public.search_pointers(
  p_types        text[]      DEFAULT NULL,
  p_date_from    timestamptz DEFAULT NULL,
  p_date_to      timestamptz DEFAULT NULL,
  p_attr_filters jsonb       DEFAULT NULL,
  p_query_text   text        DEFAULT NULL,
  p_embedding    vector      DEFAULT NULL,
  p_limit        int         DEFAULT 20,
  p_offset       int         DEFAULT 0
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $function$
DECLARE
  v_limit   int := LEAST(GREATEST(COALESCE(p_limit, 20), 1), 100);
  v_offset  int := GREATEST(COALESCE(p_offset, 0), 0);
  v_types   pointer_type[];
  v_tsquery tsquery;
  v_result  jsonb;
BEGIN
  IF p_types IS NOT NULL THEN
    v_types := p_types::pointer_type[];
  END IF;

  IF p_query_text IS NOT NULL AND length(trim(p_query_text)) > 0 THEN
    v_tsquery := websearch_to_tsquery('english', p_query_text);
  END IF;

  WITH filtered AS (
    SELECT
      p.id, p.label, p.type, p.metadata, p.occurred_at, p.created_at,
      COALESCE(p.occurred_at, p.created_at) AS event_time,
      CASE
        WHEN v_tsquery IS NULL AND p_embedding IS NULL THEN NULL
        ELSE COALESCE(CASE WHEN v_tsquery IS NOT NULL
                           THEN ts_rank(p.search_text, v_tsquery) END, 0)
           + COALESCE(CASE WHEN v_tsquery IS NOT NULL
                           THEN similarity(p.label, p_query_text) END, 0)
           + COALESCE(CASE WHEN p_embedding IS NOT NULL
                           THEN 1 - (p.embedding <=> p_embedding) END, 0)
      END AS rank
    FROM public.pointers p
    WHERE (v_types IS NULL OR p.type = ANY (v_types))
      AND (p_date_from IS NULL OR COALESCE(p.occurred_at, p.created_at) >= p_date_from)
      AND (p_date_to   IS NULL OR COALESCE(p.occurred_at, p.created_at) <= p_date_to)
      AND (p_attr_filters IS NULL OR NOT EXISTS (
            SELECT 1 FROM jsonb_each(p_attr_filters) f
            WHERE NOT EXISTS (
              SELECT 1 FROM public.attributes_kv a
              WHERE a.pointer_id = p.id
                AND a.key = f.key
                AND a.value = f.value)))
      AND (v_tsquery IS NULL
           OR p.search_text @@ v_tsquery
           OR p.label % p_query_text)
  ),
  page AS (
    SELECT * FROM filtered
    ORDER BY rank DESC NULLS LAST, event_time DESC, id
    LIMIT v_limit OFFSET v_offset
  )
  SELECT jsonb_build_object(
    'total', (SELECT count(*) FROM filtered),
    'results', COALESCE((
      SELECT jsonb_agg(
        jsonb_build_object(
          'id', pg.id,
          'label', pg.label,
          'type', pg.type,
          'occurred_at', pg.occurred_at,
          'created_at', pg.created_at,
          'event_time', pg.event_time,
          'metadata', pg.metadata,
          'rank', pg.rank,
          'attributes', COALESCE((
            SELECT jsonb_agg(
              jsonb_build_object(
                'key', a.key,
                'value', a.value,
                'data_type', a.data_type,
                'sort_order', a.sort_order)
              ORDER BY a.sort_order, a.key)
            FROM public.attributes_kv a
            WHERE a.pointer_id = pg.id), '[]'::jsonb)
        )
        ORDER BY pg.rank DESC NULLS LAST, pg.event_time DESC, pg.id)
      FROM page pg), '[]'::jsonb)
  )
  INTO v_result;

  RETURN v_result;
END;
$function$;

COMMENT ON FUNCTION public.search_pointers IS
  'Deterministic pointer search: type/date/attribute filters plus hybrid text (tsvector + trigram) and optional embedding ranking. Date filters and recency sort use COALESCE(occurred_at, created_at). Returns {total, results[]} with attributes as an ordered array.';
