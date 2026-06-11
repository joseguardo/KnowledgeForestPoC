ALTER TABLE public.pointers ADD COLUMN occurred_at timestamptz;

COMMENT ON COLUMN public.pointers.occurred_at IS
  'Domain event time (email sent_at, doc published, meeting held). NULL for timeless entities; queries fall back to created_at.';

CREATE INDEX idx_pointers_event_time
  ON public.pointers ((COALESCE(occurred_at, created_at)) DESC);

INSERT INTO public.schema_vocabulary (term, category, description)
VALUES ('occurred_at', 'attribute_key',
        'Domain event time of a pointer (email sent, document published). Use for date filters and recency sorting; falls back to created_at when null.');
