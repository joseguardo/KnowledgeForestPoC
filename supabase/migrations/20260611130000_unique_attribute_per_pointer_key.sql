-- Enables upsert semantics so re-ingestion updates attribute values
-- instead of duplicating rows.
ALTER TABLE public.attributes_kv
  ADD CONSTRAINT attributes_kv_pointer_key_unique UNIQUE (pointer_id, key);
