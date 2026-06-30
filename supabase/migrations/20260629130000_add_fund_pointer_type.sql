-- Add 'fund' to the pointer_type enum so investment funds (Fund II/III/IV,
-- Opportunity Fund) are first-class nodes, distinct from portfolio companies.
-- Naluat ledger transactions (events) link to funds via `booked_to`, and
-- companies via `part_of`. Must be its own migration: a new enum value cannot
-- be referenced in the same transaction that adds it.
alter type public.pointer_type add value if not exists 'fund';

-- Describe the new type for agent/LLM context (mirrors the existing rows).
insert into public.schema_vocabulary (term, category, description)
values (
  'fund',
  'pointer_type',
  'An investment fund (e.g. Fund II, Opportunity Fund). Portfolio companies link to it via the part_of edge; individual ledger transactions (event pointers) link via booked_to. Carries Naluat rollup attributes (naluat_company_count, naluat_invested_by_currency).'
)
on conflict do nothing;
