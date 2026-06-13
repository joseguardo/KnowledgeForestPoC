-- ============================================================================
-- Demo data: assign 3-level security classification to the existing mock data
-- ----------------------------------------------------------------------------
-- Levels:
--   public       (default) - market knowledge: sectors, geographies, regulations,
--                            well-known public companies, system meta nodes.
--   confidential           - deal/diligence material: all people (founders/execs)
--                            + a "deal pipeline" set of companies, plus sensitive
--                            financial attributes (Rev / PE / VC 2024 / Revenue)
--                            even on otherwise-public companies (per-attribute).
--   restricted             - most sensitive: the active-pipeline demo company.
--
-- Idempotent. Reversible via 20260613110001_reset_access_classes_demo.sql.
-- ============================================================================

insert into public.access_classes (key, description) values
  ('confidential', 'Deal / diligence material; cleared users only'),
  ('restricted',   'Most sensitive; restricted pipeline & financials')
on conflict (key) do nothing;

-- --- pointer-level: confidential ----------------------------------------------
update public.pointers p
set access_class_id = (select id from public.access_classes where key='confidential')
where p.type = 'person'
   or (p.type = 'company' and p.label in
        ('Factorial','Seedtag','Jobandtalent','Clarity AI','Doctolib','Alan'));

-- --- pointer-level: restricted ------------------------------------------------
update public.pointers p
set access_class_id = (select id from public.access_classes where key='restricted')
where p.label = 'Aurora Robotics (demo)';

-- --- cascade a pointer's class onto its own attributes & chunks ---------------
-- so a confidential/restricted pointer disappears entirely (incl. forest leaves),
-- not just its row.
update public.attributes_kv a
set access_class_id = p.access_class_id
from public.pointers p
where a.pointer_id = p.id
  and p.access_class_id <> '00000000-0000-0000-0000-000000000001';

update public.document_chunks dc
set access_class_id = p.access_class_id
from public.pointers p
where dc.pointer_id = p.id
  and p.access_class_id <> '00000000-0000-0000-0000-000000000001';

-- --- per-attribute: hide financials on still-public pointers ------------------
-- A public company stays visible (label, sector, HQ, CEO, stage) but its revenue,
-- P/E and VC-funding leaves are confidential -> visible only to cleared users.
update public.attributes_kv a
set access_class_id = (select id from public.access_classes where key='confidential')
from public.pointers p
where a.pointer_id = p.id
  and p.access_class_id = '00000000-0000-0000-0000-000000000001'
  and a.key in ('Rev','PE','VC 2024','Revenue');
