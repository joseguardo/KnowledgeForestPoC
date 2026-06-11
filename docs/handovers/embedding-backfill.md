# Embedding Backfill -- Edge Function

**Date**: 2026-06-10
**Function**: `backfill-embeddings`
**Project**: `rkuyvzcxaoulhjiflrmp`

## What was deployed

A one-time Supabase Edge Function (`backfill-embeddings`) that:

1. Queries all rows in `pointers` where `embedding IS NULL`
2. Batches them (20 at a time) and calls OpenAI `text-embedding-3-small`
3. Updates each pointer's `embedding` column (vector(1536))
4. Returns a JSON summary with counts of backfilled / failed rows

The embedding input text for each pointer is: `label + " " + JSON.stringify(metadata)`.

## Prerequisites

The `OPENAI_API_KEY` secret must be set in Supabase:

```bash
supabase secrets set OPENAI_API_KEY=sk-...
```

If the key is missing, the function returns a 500 with a clear error message.

## How to invoke

The function has `verify_jwt: true`, so you need to pass a valid service-role or user JWT.

```bash
curl -X POST \
  'https://rkuyvzcxaoulhjiflrmp.supabase.co/functions/v1/backfill-embeddings' \
  -H 'Authorization: Bearer <SUPABASE_SERVICE_ROLE_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

## Expected response

```json
{
  "message": "Backfill complete.",
  "total_null": 58,
  "backfilled": 58,
  "failed": 0
}
```

If some fail, an `errors` array will be included with details per pointer.

## After running

- The function is idempotent: re-running it will only process pointers that still have `embedding IS NULL`.
- Once all 58 pointers are backfilled, it returns `backfilled: 0`.
- The function can be deleted after use if desired:
  ```bash
  supabase functions delete backfill-embeddings --project-ref rkuyvzcxaoulhjiflrmp
  ```
