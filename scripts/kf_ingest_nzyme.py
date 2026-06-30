#!/usr/bin/env python3
"""
kf_ingest_nzyme.py — ingest the *Nzyme* SharePoint skeleton (folders + files as
body-less pointers + hierarchy edges) into KnowledgeForest, with an optional
reconciliation pass linking deal/portfolio folders to existing Nzyme
`opportunity`/`company` pointers.

This is the Nzyme sibling of scripts/kf_ingest_sharepoint.py (Kibo). It reuses the
same proven plumbing — env loading, the Graph client, the skeleton adapter, the
direct PostgREST bulk insert, and the concurrent edge loop with idempotent 409
handling. The Nzyme-specific part is the reconciliation pass, implemented HERE
(sharepoint_skeleton.py is untouched): Nzyme folder paths don't match the Kibo
`portfolio_context` layout, so build_skeleton is called with resolve_company /
resolve_fund returning None (pointers + hierarchy only), and reconciliation
EdgeSpecs are appended to the plan afterwards.

CREDENTIALS
-----------
  .env.local        AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET (Graph)
  pipeline/.env     SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (graph DB + edge funcs)

EXAMPLES
--------
  # Dry-run (no writes); reuses the cached drive enumeration:
  pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py --dry-run

  # Real load — skeleton + hierarchy only (no reconciliation):
  pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py --no-reconcile

  # Real load — skeleton + hierarchy + reconciliation (default):
  pipeline/.venv/bin/python scripts/kf_ingest_nzyme.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.join(ROOT, "pipeline")
for p in (os.path.join(ROOT, "scripts"), PIPELINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline.adapters import sharepoint_skeleton as sk  # noqa: E402
from sharepoint_client import SharePointClient  # noqa: E402

# ── Nzyme constants ───────────────────────────────────────────────────────────
# NB: pipeline.mcp_server.tenant_map.NZYME_TENANT is the source of truth, but
# importing it eagerly pulls in pipeline.config.settings (which validates SUPABASE_*
# at import time, before _load_env runs). The Kibo runner hardcodes its tenant for
# the same reason; we mirror that here.
SITE_SEARCH = "Nzyme"
SITE_NAME = "Nzyme"
LIBRARY = "Documentos"
ROOTS = ["04_Dealflow", "05_Portfolio"]
ACL_NZYME_TENANT = "baa52eca-4c88-4861-9d45-720e743febb4"  # tenant_map.NZYME_TENANT
DEFAULT_CACHE = "/tmp/nzyme_drive.json"

# Dealflow deal folders live exactly 3 segments deep under these prefixes.
DEAL_PREFIXES = (
    "04_Dealflow/01_Open opportunities/",
    "04_Dealflow/02_Discarded and lost opportunities/",
)
# Portfolio company folders live exactly 2 segments deep under 05_Portfolio/.
PORTFOLIO_PREFIX = "05_Portfolio/"
PORTFOLIO_NAME_EXCLUDE = {"z_folder structure", "01_recruiting for portcos"}
_PORTFOLIO_SKIP_RE = re.compile(r"^(z_|a_|b_|0\d_)", re.IGNORECASE)


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


# ── Nzyme entity index: normalize(label) -> [(canonical_key, type), ...] ──────
def fetch_entity_index() -> dict[str, list[tuple[str, str]]]:
    """opportunity + company pointers in the Nzyme tenant, keyed by normalized
    label. Multiple entities can share a normalized label (e.g. an opportunity
    and a company both named "Bip&Drive"), so values are lists."""
    import httpx

    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/pointers"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    index: dict[str, list[tuple[str, str]]] = {}
    with httpx.Client(timeout=30) as http:
        for etype in ("opportunity", "company"):
            offset = 0
            while True:
                resp = http.get(
                    url,
                    headers=headers,
                    params={
                        "type": f"eq.{etype}",
                        "acl": f"cs.{{{ACL_NZYME_TENANT}}}",
                        "select": "label,canonical_key,type",
                        "limit": 1000,
                        "offset": offset,
                    },
                )
                resp.raise_for_status()
                rows = resp.json()
                for r in rows:
                    norm = sk.normalize(r["label"])
                    index.setdefault(norm, []).append((r["canonical_key"], r["type"]))
                if len(rows) < 1000:
                    break
                offset += 1000
    return index


# ── name -> match variants ────────────────────────────────────────────────────
_DATE_PREFIX = re.compile(r"^\s*\d{4}\s*\d{0,2}\s*[_ ]\s*")
_NUM_PREFIX = re.compile(r"^\s*\d+\s*[_.\-)]\s*")
_TRAIL_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_TRAIL_PT = re.compile(r"_pt$", re.IGNORECASE)


def name_variants(name: str) -> list[str]:
    """Generate match variants for a folder name by stripping, in combination,
    a leading date prefix, a generic numeric prefix, a trailing parenthetical,
    and a trailing `_pt`. The original name is always included."""
    seeds = {name or ""}
    # Strip leading prefixes (date first, then generic numeric).
    expanded = set(seeds)
    for s in list(seeds):
        d = _DATE_PREFIX.sub("", s)
        expanded.add(d)
        expanded.add(_NUM_PREFIX.sub("", s))
        expanded.add(_NUM_PREFIX.sub("", d))
    # For each, optionally strip trailing parenthetical and/or trailing _pt,
    # in all combinations.
    out: set[str] = set()
    for s in expanded:
        cands = {s}
        cands.add(_TRAIL_PAREN.sub("", s))
        cands.add(_TRAIL_PT.sub("", s))
        cands.add(_TRAIL_PT.sub("", _TRAIL_PAREN.sub("", s)))
        cands.add(_TRAIL_PAREN.sub("", _TRAIL_PT.sub("", s)))
        out |= {c.strip() for c in cands if c.strip()}
    return [v for v in out if v]


def match_entities(
    name: str, index: dict[str, list[tuple[str, str]]]
) -> list[tuple[str, str]]:
    """Return all (canonical_key, type) entities whose normalized label matches
    ANY variant of the folder name. Deduped, preserving first-seen order."""
    seen: set[str] = set()
    matches: list[tuple[str, str]] = []
    for v in name_variants(name):
        for key, etype in index.get(sk.normalize(v), []):
            if key not in seen:
                seen.add(key)
                matches.append((key, etype))
    return matches


# ── entity-folder selection ─────────────────────────────────────────────────
def deal_folders(items: list[dict]) -> list[dict]:
    """3-segment folders directly under the Open / Discarded dealflow prefixes."""
    out = []
    for it in items:
        if it["type"] != "folder":
            continue
        p = it["sp_path"]
        segs = [s for s in p.split("/") if s]
        if len(segs) == 3 and any(p.startswith(pre) for pre in DEAL_PREFIXES):
            out.append(it)
    return out


def portfolio_folders(items: list[dict]) -> list[dict]:
    """2-segment folders directly under 05_Portfolio/, minus structural folders."""
    out = []
    for it in items:
        if it["type"] != "folder":
            continue
        p = it["sp_path"]
        segs = [s for s in p.split("/") if s]
        if len(segs) != 2 or not p.startswith(PORTFOLIO_PREFIX):
            continue
        name = it["name"]
        low = name.lower()
        if low in PORTFOLIO_NAME_EXCLUDE or _PORTFOLIO_SKIP_RE.match(name):
            continue
        out.append(it)
    return out


def reconcile(
    items: list[dict],
    index: dict[str, list[tuple[str, str]]],
    *,
    entra_tenant: str,
    drive_id: str,
) -> tuple[list[sk.EdgeSpec], list[tuple[dict, list[tuple[str, str]]]], list[dict]]:
    """Build reconciliation EdgeSpecs (folder -> entity) for matched entity
    folders. Returns (edges, matched, unmatched) where `matched` is a list of
    (folder_item, [(entity_label_norm... actually entity_key, type)]) and
    `unmatched` is the list of entity-folder items with no match."""
    entity_folders = deal_folders(items) + portfolio_folders(items)
    edges: list[sk.EdgeSpec] = []
    matched: list[tuple[dict, list[tuple[str, str]]]] = []
    unmatched: list[dict] = []
    for it in entity_folders:
        ents = match_entities(it["name"], index)
        if not ents:
            unmatched.append(it)
            continue
        matched.append((it, ents))
        folder_key = sk.item_key(entra_tenant, drive_id, it["id"])
        for key, etype in ents:
            why = "opportunity_documents" if etype == "opportunity" else "company_documents"
            edges.append(sk.EdgeSpec(folder_key, key, "folder_of", why=why))
    return edges, matched, unmatched


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


def slice_items(items: list[dict], roots: list[str]) -> list[dict]:
    """Keep items whose sp_path is exactly a root or sits under root + '/'."""
    out = []
    for it in items:
        p = it["sp_path"]
        if any(p == r or p.startswith(r + "/") for r in roots):
            out.append(it)
    return out


# ── PostgREST helpers (verbatim from kf_ingest_sharepoint.py) ─────────────────
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
                # ORDER BY is REQUIRED: offset pagination without a stable sort
                # skips/overlaps rows and under-counts the existing set (which made
                # an earlier run try to re-insert existing keys -> 409).
                "order": "canonical_key", "limit": 1000, "offset": offset,
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
    # on_conflict + ignore-duplicates makes the insert idempotent at the DB level
    # (pointers has a UNIQUE index on canonical_key): re-sending an existing key is a
    # no-op instead of a 409, so a stale existing-keys fetch can never crash the run.
    # Pre-existing rows aren't returned here; their ids are resolved in the edge phase.
    h = {**h, "Content-Type": "application/json",
         "Prefer": "resolution=ignore-duplicates,return=representation"}
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
            r = http.post(url, headers=h, params={"on_conflict": "canonical_key"}, json=rows)
            r.raise_for_status()
            for row in r.json():
                out[row["canonical_key"]] = row["id"]
            print(f"  inserted {min(i + CHUNK, len(pointers))}/{len(pointers)}")
    return out


# ── dry-run printout ──────────────────────────────────────────────────────────
def print_dry_run(
    plan: sk.SkeletonPlan,
    matched: list[tuple[dict, list[tuple[str, str]]]],
    unmatched: list[dict],
    reconcile_on: bool,
) -> None:
    folders = sum(1 for p in plan.pointers if p["type"] == "folder")
    docs = sum(1 for p in plan.pointers if p["type"] == "document")
    print(f"[dry-run] pointers: {len(plan.pointers)}  ({folders} folder, {docs} document)")
    print(f"[dry-run] edges:    {len(plan.edges)}")
    by_rel: dict[str, int] = {}
    by_why: dict[str, int] = {}
    for e in plan.edges:
        by_rel[e.relationship_type] = by_rel.get(e.relationship_type, 0) + 1
        if e.why in ("opportunity_documents", "company_documents"):
            by_why[e.why] = by_why.get(e.why, 0) + 1
    for rel, n in sorted(by_rel.items()):
        print(f"            {rel:<14} {n}")

    # Per-root breakdown.
    print("\n[dry-run] per-root pointer counts:")
    for r in ROOTS:
        rf = sum(1 for p in plan.pointers
                 if p["metadata"]["sp_path"] == r or p["metadata"]["sp_path"].startswith(r + "/"))
        rfo = sum(1 for p in plan.pointers
                  if p["type"] == "folder"
                  and (p["metadata"]["sp_path"] == r or p["metadata"]["sp_path"].startswith(r + "/")))
        print(f"  {r:<14} {rf:>7}  ({rfo} folder, {rf - rfo} document)")

    if not reconcile_on:
        print("\n[dry-run] reconciliation: SKIPPED (--no-reconcile)")
        print("\n[dry-run] no edge functions called.")
        return

    print(f"\n[dry-run] reconciliation: {len(matched)} folders matched -> "
          f"{sum(len(e) for _, e in matched)} edges "
          f"({by_why.get('opportunity_documents', 0)} opportunity_documents, "
          f"{by_why.get('company_documents', 0)} company_documents)")
    print("\n[dry-run] matched entity-folders (folder name -> entity[type] {why}):")
    for it, ents in sorted(matched, key=lambda m: m[0]["sp_path"]):
        labels = ", ".join(
            f"{key.split('::')[-1] if '::' in key else key}[{etype}]"
            f"{{{'opportunity_documents' if etype == 'opportunity' else 'company_documents'}}}"
            for key, etype in ents
        )
        root = it["sp_path"].split("/")[0]
        print(f"  [{root}] {it['name']}")
        print(f"        -> {labels}")
    print(f"\n[dry-run] UNMATCHED entity-folders ({len(unmatched)}):")
    for it in sorted(unmatched, key=lambda x: x["sp_path"]):
        root = it["sp_path"].split("/")[0]
        print(f"  [{root}] {it['name']}")
    print("\n[dry-run] no edge functions called.")


# ── real run (insert pointers + concurrent edges) ─────────────────────────────
async def run_ingest(
    plan: sk.SkeletonPlan, verbose: bool,
    *, edge_concurrency: int = 16,
) -> int:
    """Bulk-insert pointers (skip-if-exists), then create edges concurrently.

    Pointers go in via a direct PostgREST bulk INSERT keyed on the exact
    canonical_key — NOT insert_pointer_with_dedup (its per-item vector-similarity
    search does not scale to tens of thousands of rows). Embeddings/search_text
    are left NULL and backfilled separately.
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

        # 2) Resolve edge endpoints not produced above (existing entities).
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
    parser.add_argument("--dry-run", action="store_true",
                        help="build & print the plan (incl. reconciliation matches); no writes")
    parser.add_argument("--no-reconcile", action="store_true",
                        help="skeleton + hierarchy only; skip the reconciliation pass")
    parser.add_argument("--cache", default=DEFAULT_CACHE,
                        help=f"path to cache/load the drive enumeration JSON (default {DEFAULT_CACHE})")
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

    # Enumerate (cache short-circuits any Graph call); resolve site/drive only if
    # we actually need to reach Graph.
    site_url = None
    if not (args.cache and os.path.exists(args.cache)):
        sites = client.find_sites(SITE_SEARCH)
        site = next(
            (s for s in sites if s["displayName"] == SITE_NAME or s["name"] == SITE_NAME), None
        )
        if not site:
            print(f"Site {SITE_NAME!r} not found in {[s['displayName'] for s in sites]}",
                  file=sys.stderr)
            return 2
        site_url = site["webUrl"]

    items = slice_items(enumerate_library(client, site_url, args.cache), ROOTS)
    if not items:
        print(f"No items matched under roots {ROOTS}.", file=sys.stderr)
        return 1
    print(f"matched {len(items)} drive items under {ROOTS}")

    # Resolve drive_id from the cache itself when possible (avoids a Graph call);
    # every skeleton item carries the drive root in its key via item_id only, so
    # we need the drive id explicitly. Derive it from list_drives.
    if site_url is None:
        sites = client.find_sites(SITE_SEARCH)
        site = next(
            (s for s in sites if s["displayName"] == SITE_NAME or s["name"] == SITE_NAME), None
        )
        if not site:
            print(f"Site {SITE_NAME!r} not found.", file=sys.stderr)
            return 2
        site_url = site["webUrl"]
    drives = client.list_drives(site_url)
    drive_id = next(d["id"] for d in drives if d["name"] == LIBRARY)

    # Skeleton: pointers + hierarchy ONLY (no Kibo-style entity edges).
    plan = sk.build_skeleton(
        items,
        drive_id=drive_id,
        drive_name=LIBRARY,  # "Documentos" — isolates Nzyme rows via metadata.library
        entra_tenant=entra_tenant,
        acl_principal=ACL_NZYME_TENANT,
        resolve_company=lambda n: None,
        resolve_fund=lambda n: None,
    )

    matched: list[tuple[dict, list[tuple[str, str]]]] = []
    unmatched: list[dict] = []
    reconcile_on = not args.no_reconcile
    if reconcile_on:
        index = fetch_entity_index()
        n_op = sum(1 for v in index.values() for _, t in v if t == "opportunity")
        n_co = sum(1 for v in index.values() for _, t in v if t == "company")
        print(f"entity index: {n_op} opportunity + {n_co} company pointers (Nzyme tenant)")
        recon_edges, matched, unmatched = reconcile(
            items, index, entra_tenant=entra_tenant, drive_id=drive_id
        )
        plan.edges.extend(recon_edges)

    if args.dry_run:
        print_dry_run(plan, matched, unmatched, reconcile_on)
        return 0
    return asyncio.run(run_ingest(plan, args.verbose))


if __name__ == "__main__":
    sys.exit(main())
