-- Add 'event' to the pointer_type enum so calendar interactions (meetings,
-- calls, emails) are first-class nodes in the memory layer, alongside
-- companies, people and documents. Must be its own migration: a new enum
-- value cannot be referenced in the same transaction that adds it.
alter type public.pointer_type add value if not exists 'event';

-- Describe the new type for agent/LLM context (mirrors the 34 existing rows).
insert into public.schema_vocabulary (term, category, description)
values (
  'event',
  'pointer_type',
  'A time-stamped interaction (meeting, call, email) linked to the people and companies involved. occurred_at holds the interaction time; edges (attended / attended_by / regarding) connect it to participants.'
)
on conflict do nothing;
