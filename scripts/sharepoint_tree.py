#!/usr/bin/env python3
"""
sharepoint_tree.py — print the full folder/file structure of a SharePoint site.

Discovers the "Kibo Ventures" site by name (Microsoft Graph site search), then
recursively traverses every document library (drive) on it and prints an indented
tree of folders and files. Reuses scripts/sharepoint_client.py — no new deps.

CREDENTIALS
-----------
Reads AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET from .env.local
(repo root). Existing environment variables take precedence.

EXAMPLES
--------
    python3 scripts/sharepoint_tree.py
    python3 scripts/sharepoint_tree.py --search "Kibo"
    python3 scripts/sharepoint_tree.py --site "Kibo Ventures"
    python3 scripts/sharepoint_tree.py --site https://kiboventures.sharepoint.com/sites/KiboVentures
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from sharepoint_client import SharePointClient  # noqa: E402


def _load_env_local() -> None:
    """Load .env.local from the repo root into os.environ (no overwrite)."""
    env_path = os.path.join(ROOT, ".env.local")
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


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _pick_site(sites: list[dict], site_arg: str | None) -> dict | None:
    """Return the chosen site, or None if disambiguation is needed."""
    if not sites:
        return None
    if site_arg:
        needle = site_arg.lower()
        exact = [
            s for s in sites
            if needle in (s["name"].lower(), s["displayName"].lower(), s["webUrl"].lower())
        ]
        if exact:
            return exact[0]
        partial = [
            s for s in sites
            if needle in s["name"].lower()
            or needle in s["displayName"].lower()
            or needle in s["webUrl"].lower()
        ]
        if len(partial) == 1:
            return partial[0]
        return None
    if len(sites) == 1:
        return sites[0]
    return None


def _print_tree(items: list[dict]) -> tuple[int, int]:
    """Print items as an indented tree. Returns (folder_count, file_count)."""
    # Sort by path so each folder is immediately followed by its descendants.
    items = sorted(items, key=lambda it: it["sp_path"].lower())

    folders = files = 0
    for it in items:
        depth = it["sp_path"].count("/")
        indent = "    " * depth
        if it["type"] == "folder":
            folders += 1
            print(f"{indent}{it['name']}/")
        else:
            files += 1
            size = it.get("size")
            suffix = f"  ({_human_size(size)})" if isinstance(size, int) else ""
            print(f"{indent}{it['name']}{suffix}")
    return folders, files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search", default="Kibo", help="site search term (default: Kibo)")
    parser.add_argument(
        "--site",
        help="exact site name / displayName / webUrl to disambiguate multiple matches",
    )
    args = parser.parse_args()

    _load_env_local()
    tenant = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    missing = [
        n for n, v in (
            ("AZURE_TENANT_ID", tenant),
            ("AZURE_CLIENT_ID", client_id),
            ("AZURE_CLIENT_SECRET", secret),
        ) if not v
    ]
    if missing:
        print(f"Missing credentials: {', '.join(missing)} (set in .env.local)", file=sys.stderr)
        return 2

    client = SharePointClient(tenant, client_id, secret)

    sites = client.find_sites(args.search)
    site = _pick_site(sites, args.site)
    if site is None:
        if not sites:
            print(f"No sites matched '{args.search}'.", file=sys.stderr)
            print("Try a different --search term, or pass --site with a full site URL.", file=sys.stderr)
        else:
            print(f"{len(sites)} sites matched '{args.search}' — pass --site to choose one:", file=sys.stderr)
            for s in sites:
                label = s["displayName"] or s["name"]
                print(f"  - {label}  ({s['webUrl']})", file=sys.stderr)
        return 2

    site_url = site["webUrl"]
    label = site["displayName"] or site["name"]
    print(f"Site: {label}")
    print(f"URL:  {site_url}\n")

    drives = client.list_drives(site_url)
    if not drives:
        print("No document libraries found on this site.", file=sys.stderr)
        return 1

    total_folders = total_files = 0
    for drive in drives:
        print(f"=== {drive['name']}/ ===")
        items = client.enumerate_drive(drive["id"])
        f, fl = _print_tree(items)
        total_folders += f
        total_files += fl
        print()

    print(f"Total: {total_folders} folders, {total_files} files "
          f"across {len(drives)} document librar{'y' if len(drives) == 1 else 'ies'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
