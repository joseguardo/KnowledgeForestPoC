-- ============================================================================
-- Verification: class-gated RLS makes restricted rows COMPLETELY INVISIBLE
-- ----------------------------------------------------------------------------
-- Run AFTER 20260613100000_access_classes_grants_rls.sql is applied.
-- Plain SQL (no psql meta-commands) so it runs in the Supabase SQL editor.
-- Everything runs inside one transaction and ROLLBACKs at the end: it tags a
-- real pointer only transiently and persists NOTHING.
--
-- Identities are simulated with SET LOCAL ROLE + request.jwt.claims, exactly as
-- PostgREST does per request. The "direct user grant" path is used so no
-- auth.users row is needed (access_grants.grantee_id is a bare uuid).
--
-- Results are collected into a temp table and emitted by ONE final SELECT,
-- because the SQL editor shows only the last result set.
--
-- Expected output (with the seed dataset of 103 pointers):
--   { "baseline_total":"103",            -- editor role sees everything
--     "anon_sees_restricted":"0",        -- anon cannot see the tagged pointer
--     "anon_total":"102",                -- ...and it drops out of the COUNT (in-query filtering)
--     "uncleared_sees_restricted":"0",   -- logged-in but ungranted: still hidden
--     "cleared_sees_restricted":"1",     -- granted user: visible
--     "cleared_total":"103" }            -- ...and back in the count
-- ============================================================================
begin;

-- fixture: a restricted class, and one real pointer re-tagged into it
insert into public.access_classes (key, description)
values ('confidential:test', 'verification-only class') on conflict (key) do nothing;

create temporary table _t as
  select id as pid,
         (select id from public.access_classes where key = 'confidential:test') as cls
  from public.pointers order by created_at limit 1;

update public.pointers set access_class_id = (select cls from _t)
where id = (select pid from _t);

-- scratch results (single final SELECT shows everything)
create temporary table _r(k text, v text);
grant insert, select on _r to anon, authenticated;
grant select on _t to anon, authenticated;

insert into _r select 'baseline_total',
  (public.search_pointers(null::text[],null::timestamptz,null::timestamptz,null::jsonb,null::text,null::vector,500,0)->>'total');

-- 1) anon (no JWT): only the public class is readable
set local role anon;
select set_config('request.jwt.claims', '', true);
insert into _r select 'anon_sees_restricted', count(*)::text
  from public.pointers where id = (select pid from _t);
insert into _r select 'anon_total',
  (public.search_pointers(null::text[],null::timestamptz,null::timestamptz,null::jsonb,null::text,null::vector,500,0)->>'total');
reset role;

-- 2) authenticated but NOT granted: still hidden
set local role authenticated;
select set_config('request.jwt.claims',
  json_build_object('sub','22222222-2222-2222-2222-222222222222','role','authenticated')::text, true);
insert into _r select 'uncleared_sees_restricted', count(*)::text
  from public.pointers where id = (select pid from _t);
reset role;

-- 3) grant the class to a user, then act as that user: now visible
insert into public.access_grants(access_class_id, grantee_type, grantee_id)
values ((select cls from _t), 'user', '11111111-1111-1111-1111-111111111111');
set local role authenticated;
select set_config('request.jwt.claims',
  json_build_object('sub','11111111-1111-1111-1111-111111111111','role','authenticated')::text, true);
insert into _r select 'cleared_sees_restricted', count(*)::text
  from public.pointers where id = (select pid from _t);
insert into _r select 'cleared_total',
  (public.search_pointers(null::text[],null::timestamptz,null::timestamptz,null::jsonb,null::text,null::vector,500,0)->>'total');
reset role;

select jsonb_object_agg(k, v order by k) as results from _r;

rollback;  -- persist nothing
