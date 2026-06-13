-- ============================================================================
-- Reverses 20260613110000_seed_access_classes_demo.sql: returns all content to
-- the public class. Run this to clear the demo classification. Does NOT drop the
-- foundation (access_classes / grants / RLS) from 20260613100000.
-- ============================================================================
update public.pointers        set access_class_id = '00000000-0000-0000-0000-000000000001'
  where access_class_id <> '00000000-0000-0000-0000-000000000001';
update public.attributes_kv   set access_class_id = '00000000-0000-0000-0000-000000000001'
  where access_class_id <> '00000000-0000-0000-0000-000000000001';
update public.document_chunks set access_class_id = '00000000-0000-0000-0000-000000000001'
  where access_class_id <> '00000000-0000-0000-0000-000000000001';
update public.edges           set access_class_id = '00000000-0000-0000-0000-000000000001'
  where access_class_id <> '00000000-0000-0000-0000-000000000001';
-- access_grants referencing confidential/restricted are removed when those grants
-- are no longer wanted; the class rows can stay (harmless) or be deleted manually.
