#!/usr/bin/env python3
"""
kf_ingest_sharepoint.py — ingest the SharePoint *skeleton* (folders + files as
body-less pointers + hierarchy/reconciliation edges) into KnowledgeForest.

Reuses the Graph client (pipeline.adapters.sharepoint.SharePointClient), the
skeleton adapter (pipeline.adapters.sharepoint_skeleton), and the edge functions
(ingest-batch + link-pointers) via pipeline.client.EdgeFunctionClient.

CREDENTIALS
-----------
  .env.local        AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET (Graph)
  pipeline/.env     SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (graph DB + edge funcs)

EXAMPLES
--------
  # Dry-run a single company (no writes); caches the drive enumeration for speed:
  pipeline/.venv/bin/python scripts/kf_ingest_sharepoint.py \
      --company Carto --dry-run --cache /tmp/kibo_drive.json

  # Real load of one company:
  pipeline/.venv/bin/python scripts/kf_ingest_sharepoint.py --company Carto
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(ROOT, "pipeline")
for p in (os.path.join(ROOT, "scripts"), PIPELINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline.adapters import sharepoint_skeleton as sk  # noqa: E402
from sharepoint_client import SharePointClient  # noqa: E402

SITE_SEARCH = "Kibo"
SITE_NAME = "Kibo Ventures"
LIBRARY = "Kibo_Ventures"
PORTFOLIO_ROOT = "02_Portfolio"
ACL_KIBO_TENANT = "ca61f0e5-563e-5894-954f-38f5a9e0eabc"  # naluat.KIBO_TENANT


# ── env loading (both files) ────────────────────────────────────────────────
def _load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip().strip('"').strip("'")


# ── company label -> canonical_key index (read-only, via PostgREST) ───────────
def fetch_company_index() -> dict[str, str]:
    import httpx

    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/pointers"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    index: dict[str, str] = {}
    offset = 0
    with httpx.Client(timeout=30) as http:
        while True:
            resp = http.get(
                url,
                headers=headers,
                params={
                    "type": "eq.company",
                    "select": "label,canonical_key",
                    "limit": 1000,
                    "offset": offset,
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            for r in rows:
                index.setdefault(sk.normalize(r["label"]), r["canonical_key"])
            if len(rows) < 1000:
                break
            offset += 1000
    return index


# ── enumeration (with cache) ──────────────────────────────────────────────────
def enumerate_library(client: SharePointClient, site_url: str, cache: str | None) -> list[dict]:
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    drives = client.list_drives(site_url)
    drive = next((d for d in drives if d["name"] == LIBRARY), None)
    if not drive:
        raise SystemExit(f"Library {LIBRARY!r} not found. Drives: {[d['name'] for d in drives]}")
    items = client.enumerate_drive(drive["id"])
    if cache:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(items, f)
    return items


def slice_items(items: list[dict], company: str | None) -> list[dict]:
    """Keep the 02_Portfolio subtree; if a company is given, only that company's
    folder subtree(s)."""
    portfolio = [
        it for it in items
        if it["sp_path"] == PORTFOLIO_ROOT or it["sp_path"].startswith(PORTFOLIO_ROOT + "/")
    ]
    if not company:
        return portfolio
    want = sk.normalize(company)
    return [it for it in portfolio
            if (sk.portfolio_context(it["sp_path"]).company_name
                and sk.normalize(sk.portfolio_context(it["sp_path"]).company_name) == want)]


def print_dry_run(plan: sk.SkeletonPlan) -> None:
    folders = sum(1 for p in plan.pointers if p["type"] == "folder")
    docs = sum(1 for p in plan.pointers if p["type"] == "document")
    print(f"[dry-run] pointers: {len(plan.pointers)}  ({folders} folder, {docs} document)")
    print(f"[dry-run] edges:    {len(plan.edges)}")
    by_rel: dict[str, int] = {}
    recon = [e for e in plan.edges if e.why in ("fund_documents", "company_documents")]
    for e in plan.edges:
        by_rel[e.relationship_type] = by_rel.get(e.relationship_type, 0) + 1
    for rel, n in sorted(by_rel.items()):
        print(f"            {rel:<14} {n}")
    print("\n[dry-run] sample pointers:")
    for p in plan.pointers[:12]:
        print(f"  {p['type']:<8} {p['label']}")
        print(f"           key: {p['canonical_key']}")
    print("\n[dry-run] reconciliation edges (folder -> entity):")
    for e in recon:
        print(f"  {e.source_key}\n     --folder_of [{e.why}]--> {e.target_key}")
    if plan.unresolved_companies:
        print(f"\n[dry-run] UNRESOLVED companies (no pointer / alias): "
              f"{sorted(set(plan.unresolved_companies))}")
    if plan.unresolved_funds:
        print(f"[dry-run] funds with no entity (folder created, unlinked): "
              f"{sorted(set(plan.unresolved_funds))}")
    print("\n[dry-run] no edge functions called.")


def _rest_base() -> tuple[str, dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/pointers"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return url, {"apikey": key, "Authorization": f"Bearer {key}"}


def _fetch_existing_skeleton_ids() -> dict[str, str]:
    """canonical_key -> id for every sharepoint_skeleton pointer already in the DB.
    Lets the bulk insert skip rows that exist (idempotent without a unique constraint)."""
    import httpx
    url, h = _rest_base()
    out: dict[str, str] = {}
    offset = 0
    with httpx.Client(timeout=60) as http:
        while True:
            r = http.get(url, headers=h, params={
                "select": "canonical_key,id", "metadata->>source": "eq.sharepoint_skeleton",
                "limit": 1000, "offset": offset,
            })
            r.raise_for_status()
            rows = r.json()
            for row in rows:
                if row.get("canonical_key"):
                    out[row["canonical_key"]] = row["id"]
            if len(rows) < 1000:
                break
            offset += 1000
    return out


def _bulk_insert(pointers: list[dict]) -> dict[str, str]:
    """Plain bulk INSERT (no similarity dedup, no embedding) in chunks; returns the
    new canonical_key -> id map. Caller guarantees these keys don't already exist."""
    import httpx
    url, h = _rest_base()
    h = {**h, "Content-Type": "application/json", "Prefer": "return=representation"}
    out: dict[str, str] = {}
    CHUNK = 500
    with httpx.Client(timeout=120) as http:
        for i in range(0, len(pointers), CHUNK):
            chunk = pointers[i:i + CHUNK]
            rows = [{
                "label": p["label"], "type": p["type"], "canonical_key": p["canonical_key"],
                "metadata": p["metadata"], "occurred_at": p.get("occurred_at"),
                "acl": p["principals"],
            } for p in chunk]
            r = http.post(url, headers=h, json=rows)
            r.raise_for_status()
            for row in r.json():
                out[row["canonical_key"]] = row["id"]
            print(f"  inserted {min(i + CHUNK, len(pointers))}/{len(pointers)}")
    return out


async def run_ingest(
    plan: sk.SkeletonPlan, verbose: bool,
    *, edge_concurrency: int = 16,
) -> int:
    """Bulk-insert pointers (skip-if-exists), then create edges concurrently.

    Pointers go in via a direct PostgREST bulk INSERT keyed on the exact
    canonical_key — NOT insert_pointer_with_dedup, whose per-item vector-similarity
    search does not scale to ~30k rows (it decelerates and times out). The skeleton
    only needs exact-key identity, so the similarity search is pure overhead.
    Embeddings/search_text are left null and backfilled separately (option A).
    """
    import httpx

    from pipeline.access import resolve_pointer_id
    from pipeline.client import EdgeFunctionClient
    from pipeline.errors import EdgeFunctionError
    from pipeline.config import settings

    # 1) Pointers: fetch existing, insert only the missing ones.
    existing = _fetch_existing_skeleton_ids()
    key_to_id: dict[str, str | None] = dict(existing)
    missing = [p for p in plan.pointers if p["canonical_key"] not in existing]
    already = len(plan.pointers) - len(missing)
    print(f"  pointers: {already} already present, inserting {len(missing)} new")
    if missing:
        key_to_id.update(_bulk_insert(missing))
    created, merged, errors = len(missing), already, 0

    async with httpx.AsyncClient(timeout=60) as http:
        client = EdgeFunctionClient(
            http=http,
            supabase_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            max_retries=settings.max_retries,
            retry_backoff_base=settings.retry_backoff_base,
        )

        # 2) Resolve edge endpoints not produced above (existing fund/company entities).
        for e in plan.edges:
            for k in (e.source_key, e.target_key):
                if k not in key_to_id:
                    key_to_id[k] = await resolve_pointer_id(http, k)

        # 3) Create edges concurrently. 409 == edge already exists -> idempotent skip.
        edge_ok = edge_exists = edge_skip = 0
        sem_e = asyncio.Semaphore(edge_concurrency)

        async def do_edge(e: sk.EdgeSpec) -> None:
            nonlocal edge_ok, edge_exists, edge_skip
            sid, tid = key_to_id.get(e.source_key), key_to_id.get(e.target_key)
            if not sid or not tid:
                edge_skip += 1
                if verbose:
                    print(f"  edge skipped (unresolved): {e.source_key} -> {e.target_key}")
                return
            async with sem_e:
                try:
                    await client.link_pointers(
                        source_id=sid, target_id=tid,
                        relationship_type=e.relationship_type, why=e.why,
                    )
                    edge_ok += 1
                except EdgeFunctionError as exc:
                    if exc.status_code == 409:
                        edge_exists += 1
                    else:
                        raise

        await asyncio.gather(*(do_edge(e) for e in plan.edges))

    print(f"\npointers: inserted={created} already_present={merged} errors={errors}")
    print(f"edges:    created={edge_ok} already_exists={edge_exists} unresolved={edge_skip}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", help="restrict to one company folder (e.g. Carto)")
    parser.add_argument("--dry-run", action="store_true", help="build & print the plan; no writes")
    parser.add_argument("--cache", help="path to cache/load the drive enumeration JSON")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _load_env(os.path.join(ROOT, ".env.local"))
    _load_env(os.path.join(PIPELINE_DIR, ".env"))

    entra_tenant = os.environ.get("AZURE_TENANT_ID")
    if not entra_tenant:
        print("AZURE_TENANT_ID missing (.env.local)", file=sys.stderr)
        return 2

    client = SharePointClient(
        entra_tenant, os.environ["AZURE_CLIENT_ID"], os.environ["AZURE_CLIENT_SECRET"]
    )
    sites = client.find_sites(SITE_SEARCH)
    site = next((s for s in sites if s["displayName"] == SITE_NAME or s["name"] == SITE_NAME), None)
    if not site:
        print(f"Site {SITE_NAME!r} not found in {[s['displayName'] for s in sites]}", file=sys.stderr)
        return 2
    site_url = site["webUrl"]

    items = slice_items(enumerate_library(client, site_url, args.cache), args.company)
    if not items:
        print(f"No items matched (company={args.company!r}).", file=sys.stderr)
        return 1
    print(f"matched {len(items)} drive items under {PORTFOLIO_ROOT}"
          + (f" / {args.company}" if args.company else ""))

    drives = client.list_drives(site_url)
    drive_id = next(d["id"] for d in drives if d["name"] == LIBRARY)

    company_index = fetch_company_index()
    print(f"company index: {len(company_index)} existing company pointers")

    plan = sk.build_skeleton(
        items,
        drive_id=drive_id,
        drive_name=LIBRARY,
        entra_tenant=entra_tenant,
        acl_principal=ACL_KIBO_TENANT,
        resolve_company=lambda n: company_index.get(sk.normalize(n)),
    )

    if args.dry_run:
        print_dry_run(plan)
        return 0
    return asyncio.run(run_ingest(plan, args.verbose))


if __name__ == "__main__":
    sys.exit(main())
