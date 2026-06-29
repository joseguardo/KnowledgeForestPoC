-- Add pointer types for the Affinidad ingest + the meetings-as-communication model.
--   opportunity   — CRM dealflow/LP opportunities (kind='opportunity' in the source)
--   communication — meetings (and, later, emails) — replaces 'event' for comms
-- ADD VALUE only (no immediate use), so it's safe even inside a migration txn;
-- inserts that use these values run in later migrations / at ingest time.
alter type public.pointer_type add value if not exists 'opportunity';
alter type public.pointer_type add value if not exists 'communication';
