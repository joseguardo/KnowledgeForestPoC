-- regression_check.sql
-- Read-only behavioral snapshot of the SHARED KnowledgeForest retrieval layer.
-- Run before/after any change to query-knowledge / search_hierarchy_aware /
-- search_knowledge / traverse_graph and DIFF the output against
-- scripts/regression_baseline.json to catch unintended regressions.
--
-- Deterministic: text-only (no embedding, no LLM), so the same DB state yields
-- the same output. Run via the Supabase SQL Editor (admin sees all rows) or MCP.
--
-- CAVEAT: total pointer/edge counts drift as ingestion (e.g. Gmail) continues.
-- The invariants OUR changes must preserve are NALUAT-specific:
--   fund_rosters = {Fund II:22, Fund III:22, Opportunity Fund:7, Fund IV:4}
--   edges_by_type.part_of = 55
--   naluat_status_divested.total = 5
-- The search_* blocks validate the shared search path still returns sane results.

with T as (select 'ca61f0e5-563e-5894-954f-38f5a9e0eabc'::uuid t)
select jsonb_pretty(jsonb_build_object(
  'captured_at', now(),
  'counts', jsonb_build_object(
     'pointers_by_type', (select jsonb_object_agg(type, n) from (select type, count(*) n from pointers group by type) z),
     'edges_by_type', (select jsonb_object_agg(relationship_type, n) from (select relationship_type, count(*) n from edges group by relationship_type) z)
  ),
  'search_company_AI', (select jsonb_build_object('n',count(*),'top',jsonb_agg(label order by ord))
       from (select label, row_number() over () ord from search_hierarchy_aware('artificial intelligence company',(select t from T),null,'company',10)) z),
  'search_person', (select jsonb_build_object('n',count(*),'top',jsonb_agg(label order by ord))
       from (select label, row_number() over () ord from search_hierarchy_aware('founder ceo',(select t from T),null,'person',10)) z),
  'search_email_event', (select jsonb_build_object('n',count(*),'top',jsonb_agg(label order by ord))
       from (select label, row_number() over () ord from search_hierarchy_aware('email meeting',(select t from T),null,'event',10)) z),
  'fund_rosters', (select jsonb_object_agg(f.label, cnt) from pointers f
       cross join lateral (select count(*) cnt from traverse_graph(array[f.id]::uuid[],array['part_of'],'inbound','company'::pointer_type,1,100)) x
       where f.type='meta' and f.canonical_key like 'fund:%'),
  'naluat_status_divested', (select jsonb_build_object('total', (search_pointers(p_types=>array['company'],p_attr_filters=>'{"naluat_status":"divested"}'::jsonb,p_limit=>100))->'total'))
)) snapshot;
