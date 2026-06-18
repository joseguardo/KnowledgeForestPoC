-- =====================================================================
-- KnowledgeForest — structural / reference seed (NOT user content).
-- Run AFTER schema_dump.sql.
--
-- Part A is safe to run immediately (no auth dependency).
-- Part B wires up the demo user's clearance and tenant membership; it
-- requires the demo auth user (fixed id aaaaaaaa-0000-4000-8000-aaaaaaaaaaaa)
-- to already exist — see RUNBOOK.md step "Create the demo auth user".
-- Re-runnable: every insert is guarded with ON CONFLICT DO NOTHING.
-- =====================================================================

-- =====================================================================
-- PART A — reference / config data
-- =====================================================================

-- Access classes (the fixed-id public class is required by every default).
insert into access_classes (id,key,description,created_at) values
  ('00000000-0000-0000-0000-000000000001','public','Readable by everyone; default class for untagged rows','2026-06-13 16:22:35.152331+00'),
  ('5ef80a04-e782-4da8-9da3-b39e38a93d40','confidential','Deal / diligence material; cleared users only','2026-06-13 17:03:39.952366+00'),
  ('77a49e50-7a2b-4206-a769-2db2550d2e25','restricted','Most sensitive; restricted pipeline & financials','2026-06-13 17:03:39.952366+00')
on conflict (id) do nothing;

-- Dedup thresholds.
insert into system_config (key,value,updated_at,updated_by) values
  ('dedup_review_threshold','0.4'::jsonb,'2026-06-10 09:24:02.708171+00','system'),
  ('dedup_auto_merge_threshold','0.8'::jsonb,'2026-06-10 09:24:02.708171+00','system')
on conflict (key) do nothing;

-- The Kibo tenant (same UUID as source so VITE_KIBO_TENANT_ID is unchanged).
insert into tenants (id,name,settings,created_at) values
  ('ca61f0e5-563e-5894-954f-38f5a9e0eabc','Kibo','{"type": "investment_fund"}'::jsonb,'2026-06-10 09:37:57.345174+00')
on conflict (id) do nothing;

-- Schema vocabulary — required by query-knowledge LLM planning.
-- Embeddings are intentionally left NULL here; backfill them after deploy by
-- invoking the backfill-vocab-embeddings edge function (see RUNBOOK.md).
insert into schema_vocabulary (term,category,description) values
  ('CAGR','attribute_key','CAGR, compound annual growth rate, growth rate, annual growth, growth percentage'),
  ('CEO','attribute_key','CEO, chief executive officer, leader, head, founder, who runs'),
  ('Conf','attribute_key','confidence, confidence level, certainty, reliability'),
  ('Enacted','attribute_key','enacted, passed, effective date, year established, when created'),
  ('GDP','attribute_key','GDP, gross domestic product, economic output, economy size'),
  ('HQ','attribute_key','headquarters, HQ, office location, based in, company location, where located'),
  ('Location','attribute_key','location, city, where, based, office, address'),
  ('Market','attribute_key','market size, total addressable market, TAM, market cap, industry size'),
  ('occurred_at','attribute_key','Domain event time of a pointer (email sent, document published). Use for date filters and recency sorting; falls back to created_at when null.'),
  ('PE','attribute_key','PE ratio, price to earnings, valuation multiple, stock valuation'),
  ('Rev','attribute_key','revenue, annual revenue, total revenue, income, sales, earnings, turnover'),
  ('Scope','attribute_key','scope, coverage, applies to, what it covers, domain'),
  ('Stage','attribute_key','funding stage, series, investment round, funding round, venture stage'),
  ('Title','attribute_key','title, job title, role, position, occupation'),
  ('ceo','edge_type','chief executive officer, CEO, founder, co-founder, leader, runs, heads, leads the company'),
  ('competitor','edge_type','competitor, rival, competes with, competing company'),
  ('contains','edge_type','contains, includes, encompasses, has component'),
  ('ensures_compliance','edge_type','ensures compliance, compliant with, satisfies regulation'),
  ('follows','edge_type','follows, adheres to, complies with, guided by'),
  ('guides','edge_type','guides, best practice for, follows guidelines, governed by practice'),
  ('hq_location','edge_type','headquarters location, based in, located in, office in, HQ city'),
  ('jurisdiction','edge_type','jurisdiction, applies in, governs, regulatory scope, enforced in'),
  ('part_of','edge_type','part of, belongs to, component of, included in'),
  ('powers','edge_type','powers, runs on, built on, framework for'),
  ('primary_sector','edge_type','primary sector, main industry, belongs to sector, operates in industry'),
  ('related','edge_type','related to, connected to, associated with, linked to'),
  ('uses_agent','edge_type','uses agent, deploys agent, agent assignment'),
  ('uses_skill','edge_type','uses skill, has capability, employs skill, skill set'),
  ('uses_tool','edge_type','uses tool, employs tool, tool usage, works with tool'),
  ('company','pointer_type','company, corporation, firm, business, enterprise, startup, organization'),
  ('event','pointer_type','A time-stamped interaction (meeting, call, email) linked to the people and companies involved. occurred_at holds the interaction time; edges (attended / attended_by / regarding) connect it to participants.'),
  ('geography','pointer_type','geography, country, region, location, place, where, city, nation'),
  ('person','pointer_type','person, individual, executive, founder, leader, people, who'),
  ('regulation','pointer_type','regulation, law, policy, compliance, rule, act, directive, legislation'),
  ('sector','pointer_type','sector, industry, market, vertical, domain, field')
on conflict (term,category) do nothing;

-- =====================================================================
-- PART B — demo user clearance + tenant membership
-- Requires the demo auth user to exist (fixed id below). Run after the
-- "Create the demo auth user" step in RUNBOOK.md.
-- =====================================================================

-- Demo user (Kibo Partner) is admin of the Kibo tenant.
insert into tenant_members (user_id,tenant_id,role) values
  ('aaaaaaaa-0000-4000-8000-aaaaaaaaaaaa','ca61f0e5-563e-5894-954f-38f5a9e0eabc','admin')
on conflict (user_id,tenant_id) do nothing;

-- Demo user is granted the confidential + restricted classes directly.
insert into access_grants (access_class_id,grantee_type,grantee_id) values
  ('5ef80a04-e782-4da8-9da3-b39e38a93d40','user','aaaaaaaa-0000-4000-8000-aaaaaaaaaaaa'),
  ('77a49e50-7a2b-4206-a769-2db2550d2e25','user','aaaaaaaa-0000-4000-8000-aaaaaaaaaaaa')
on conflict (access_class_id,grantee_type,grantee_id) do nothing;
