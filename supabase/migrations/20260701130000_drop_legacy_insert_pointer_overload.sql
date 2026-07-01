-- 20260701130000_drop_legacy_insert_pointer_overload.sql
-- Drop the dead pre-ACL overload of insert_pointer_with_dedup. The 6-arg form
-- (…, p_access_class text) without p_acl still inserts into the dropped
-- access_class_id column and errors if PostgREST ever resolves to it. Only the
-- 7-arg `p_acl uuid[]` overload is live.
drop function if exists public.insert_pointer_with_dedup(
  text, pointer_type, text, jsonb, vector, text);
