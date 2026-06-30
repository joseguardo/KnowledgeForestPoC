#!/usr/bin/env python3
"""
kf_ingest.py — ingest structured entities into KnowledgeForest from a file.

Reads a JSON or CSV file of entities and pushes them through the SAME path the
FastAPI pipeline uses: pipeline.adapters.StructuredAdapter -> pipeline.router.route
-> the insert-pointer / ingest-batch edge functions. Dedup/merge is therefore
handled by the edge functions (the insert_pointer_with_dedup RPC), exactly as in
the API — this script does not reimplement any of that.

──────────────────────────────────────────────────────────────────────────────
INPUT SCHEMA
──────────────────────────────────────────────────────────────────────────────
JSON — either the full request object or a bare array of items:

    {"items": [ <item>, ... ], "source": "...", "access_class": "..."}
    [ <item>, ... ]

Each <item> (a StructuredItem):
    label          (required)  str
    type           (required)  one of pipeline.adapters.structured.VALID_POINTER_TYPES
                               (company, person, sector, geography, event, ...)
    canonical_key  (optional)  str — identity anchor; drives dedup/merge
    metadata       (optional)  object
    occurred_at    (optional)  ISO timestamp
    access_class   (optional)  str
    attributes     (optional)  [ {key, value, data_type?, sort_order?,
                                  source?, access_class?}, ... ]

CSV — one row per item. These columns map to fields:
    label, type, canonical_key, occurred_at, access_class
    metadata_json   (optional)  parsed as JSON into `metadata`
Every OTHER non-empty column becomes an attribute:
    {"key": <column name>, "value": <cell>, "data_type": "string"}

──────────────────────────────────────────────────────────────────────────────
CREDENTIALS
──────────────────────────────────────────────────────────────────────────────
Real runs read SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from pipeline/.env
(via pipeline.config.settings). --dry-run needs no credentials.

──────────────────────────────────────────────────────────────────────────────
EXAMPLES
──────────────────────────────────────────────────────────────────────────────
    python3 scripts/kf_ingest.py scripts/sample_entities.json --dry-run
    python3 scripts/kf_ingest.py scripts/sample_entities.json
    python3 scripts/kf_ingest.py data/companies.csv --source naluat --verbose
    python3 scripts/kf_ingest.py data/companies.json --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys

# Make the `pipeline` package importable whether or not it's pip-installed.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(ROOT, "pipeline")
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

from pipeline.adapters.structured import StructuredAdapter  # noqa: E402
from pipeline.errors import ValidationError  # noqa: E402
from pipeline.models import StructuredRequest  # noqa: E402
from pipeline.router import route  # noqa: E402

RESERVED_CSV_COLUMNS = {
    "label",
    "type",
    "canonical_key",
    "occurred_at",
    "access_class",
    "metadata_json",
}


def load_items_from_file(path: str, fmt: str) -> dict:
    """Read the file into a dict shaped like StructuredRequest kwargs."""
    if fmt == "json":
        return _load_json(path)
    if fmt == "csv":
        return _load_csv(path)
    raise ValidationError(f"Unknown format: {fmt}")


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"items": data}
    if isinstance(data, dict):
        if "items" not in data:
            raise ValidationError(
                "JSON object must have an 'items' array (or pass a bare array)."
            )
        return data
    raise ValidationError("JSON must be an array of items or an object with 'items'.")


def _load_csv(path: str) -> dict:
    items: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):  # row 1 is the header
            item: dict = {}
            attributes: list[dict] = []
            for col, raw in row.items():
                if col is None:
                    continue
                value = (raw or "").strip()
                if value == "":
                    continue
                if col == "metadata_json":
                    try:
                        item["metadata"] = json.loads(value)
                    except json.JSONDecodeError as exc:
                        raise ValidationError(
                            f"Row {row_num}: metadata_json is not valid JSON: {exc}"
                        ) from exc
                elif col in RESERVED_CSV_COLUMNS:
                    item[col] = value
                else:
                    attributes.append(
                        {"key": col, "value": value, "data_type": "string"}
                    )
            if attributes:
                item["attributes"] = attributes
            if item:
                items.append(item)
    if not items:
        raise ValidationError("CSV produced no rows.")
    return {"items": items}


def build_request(raw: dict, source: str | None, access_class: str | None,
                  limit: int | None) -> StructuredRequest:
    if limit is not None:
        raw = {**raw, "items": raw.get("items", [])[:limit]}
    if source is not None:
        raw["source"] = source
    if access_class is not None:
        raw["access_class"] = access_class
    return StructuredRequest(**raw)


def print_dry_run(items) -> None:
    print(f"[dry-run] {len(items)} item(s) would be ingested:\n")
    for i, item in enumerate(items):
        attrs = item.attributes or []
        print(f"  [{i}] {item.type:<14} {item.label}")
        if item.canonical_key:
            print(f"        canonical_key: {item.canonical_key}")
        if item.access_class:
            print(f"        access_class:  {item.access_class}")
        if attrs:
            keys = ", ".join(a.key for a in attrs)
            print(f"        attributes:    {keys}")
    print("\n[dry-run] No edge functions called.")


def _load_pipeline_env() -> None:
    """Load pipeline/.env into os.environ so pipeline.config.settings resolves
    regardless of the current working directory (settings reads a relative
    '.env'). Existing env vars take precedence and are never overwritten."""
    env_path = os.path.join(PIPELINE_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = val.strip().strip('"').strip("'")


async def run_ingest(items, verbose: bool) -> int:
    """Ingest via the edge functions. Returns a process exit code."""
    import httpx

    _load_pipeline_env()
    from pipeline.client import EdgeFunctionClient
    from pipeline.config import settings

    async with httpx.AsyncClient(timeout=30) as http:
        client = EdgeFunctionClient(
            http=http,
            supabase_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            max_retries=settings.max_retries,
            retry_backoff_base=settings.retry_backoff_base,
        )
        results, errors = await route(items, client)

    # Summary mirroring IngestResponse.
    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    print(f"\nitems_produced: {len(items)}")
    print(f"succeeded:      {len(results)}")
    for status in ("created", "merged", "pending_review", "unknown"):
        if status in status_counts:
            print(f"  {status:<15} {status_counts[status]}")
    for status, count in status_counts.items():
        if status not in ("created", "merged", "pending_review", "unknown"):
            print(f"  {status:<15} {count}")
    print(f"errors:         {len(errors)}")

    if verbose:
        for r in results:
            pid = r.pointer_id or "-"
            print(f"  [{r.index}] {r.status:<15} {pid}")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  [{e.index}] {e.error_type}: {e.message}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest structured entities from a JSON/CSV file via the "
        "KnowledgeForest edge functions (dedup applied).",
    )
    parser.add_argument("file", help="path to a .json or .csv file")
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        help="override format inference from the file extension",
    )
    parser.add_argument("--source", help="request-level source override")
    parser.add_argument("--access-class", help="request-level access_class override")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and validate only; do not call edge functions",
    )
    parser.add_argument("--limit", type=int, help="ingest only the first N items")
    parser.add_argument(
        "--verbose", action="store_true", help="print per-item status"
    )
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}", file=sys.stderr)
        return 2

    fmt = args.format
    if fmt is None:
        ext = os.path.splitext(args.file)[1].lower()
        fmt = {".json": "json", ".csv": "csv"}.get(ext)
        if fmt is None:
            print(
                f"Cannot infer format from '{args.file}'; pass --format json|csv.",
                file=sys.stderr,
            )
            return 2

    try:
        raw = load_items_from_file(args.file, fmt)
        request = build_request(raw, args.source, args.access_class, args.limit)
        items = StructuredAdapter().process(request)  # validates pointer types
    except ValidationError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pydantic ValidationError, JSON errors, etc.
        print(f"Failed to parse input: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print_dry_run(items)
        return 0

    return asyncio.run(run_ingest(items, args.verbose))


if __name__ == "__main__":
    sys.exit(main())
