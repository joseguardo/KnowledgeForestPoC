# Handover — Step FE (frontend wiring)

## What changed
- `src/lib/ingestionPipeline.js`: added `export function ingestNaluat(body)` →
  `POST /api/v1/ingest/naluat` (defaults body to `{}`).
- `src/hooks/useIngestion.js`: imported `ingestNaluat` and added
  `naluat: ingestNaluat` to the `SUBMITTERS` map.

## How to use
`const { submit } = useIngestion();` then `submit("naluat", { dry_run: true })`
(or `{}` for a real run). Returns the standard
`{ source_type, items_produced, results, errors, duration_ms }` envelope; history
tracking works like the other source types.

## Cross-contract
Only the fixed endpoint path string `/ingest/naluat` couples FE to BE. The BE
agent owns that route in `pipeline/pipeline/api/ingest.py`.

## Data-structure delta
None (frontend only).

## Verify
Lint/build the frontend (see DD-FE). The `ingestNaluat` import is now used, so the
earlier "declared but never read" hint is resolved.
