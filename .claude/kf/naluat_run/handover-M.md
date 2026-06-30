# Handover — Step M (fund pointer type migration)

## What changed
- NEW migration file: `supabase/migrations/20260629130000_add_fund_pointer_type.sql`
  - `alter type public.pointer_type add value if not exists 'fund';`
  - inserts a `schema_vocabulary` row (`term='fund'`, `category='pointer_type'`).

## Data-structure delta
- New enum value `fund` on `public.pointer_type`. Additive, safe, irreversible
  (Postgres cannot drop enum values).
- New vocab row describing `fund`.

## ⚠ NOT YET APPLIED — needs the user
There is **no local apply path** in this environment: no Supabase CLI, no
SQL-exec edge function/RPC, no management/access token, no direct KF Postgres DSN
(the only DSNs in `pipeline/.env` point to the *source* Neo project), and no
Python PG driver installed. Prior enum migrations (event, opportunity,
communication) were applied externally — presumably via the **Supabase dashboard
SQL editor**. The user must run this migration there before the real ingest.

## Verify after apply
Service-role PostgREST (key in `pipeline/.env`):
```
# expect a row for any 'fund' pointer once ingested; first just confirm enum:
# (enum check needs SQL; via dashboard: SELECT enum_range(NULL::pointer_type);)
curl -s "$URL/rest/v1/schema_vocabulary?term=eq.fund&category=eq.pointer_type" -H "apikey: $KEY" -H "Authorization: Bearer $KEY"
```

## Gate
Agent RUN's real ingest (which inserts `type=fund` pointers) MUST wait until this
migration is applied; otherwise the fund inserts fail with an invalid enum value.
