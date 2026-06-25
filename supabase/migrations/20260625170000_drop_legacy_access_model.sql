-- ============================================================================
-- Stage 4c: drop the legacy class/grant access model, fully superseded by acl[].
-- ----------------------------------------------------------------------------
-- By now: RLS uses `acl && my_principals()`; the RPC + edge functions stamp acl
-- only; the pipeline no longer calls ensure_class/grant. Nothing references
-- access_class_id, access_classes, access_grants, thread_membership, or the
-- can_read_* gate functions (verified: no policy depends on them). Drop them.
-- `tenant_members` stays — it feeds my_principals().
-- ============================================================================

-- access_class_id columns (drops their FK to access_classes with them)
alter table public.pointers        drop column if exists access_class_id;
alter table public.attributes_kv   drop column if exists access_class_id;
alter table public.document_chunks drop column if exists access_class_id;
alter table public.edges           drop column if exists access_class_id;

-- legacy tables (their RLS policies drop with them)
drop table if exists public.access_grants;
drop table if exists public.thread_membership;
drop table if exists public.access_classes;

-- legacy gate functions
drop function if exists public.can_read_thread_doc(uuid);
drop function if exists public.can_read_thread(uuid, text);
drop function if exists public.can_read_class(uuid);