-- Emails become a first-class node kind, distinct from the generic `event`
-- (meetings / calendar / CRM interactions). Adds the enum value only; existing
-- rows are untouched. Safe outside a transaction since the value isn't used in
-- this same statement.
ALTER TYPE public.pointer_type ADD VALUE IF NOT EXISTS 'message';
