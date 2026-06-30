#!/usr/bin/env python3
"""
sharepoint_fetch_content_example.py — fetch a document from SharePoint via the
Microsoft Graph `/content` endpoint.

Worked example of downloading a file with:

    GET https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content
    Authorization: Bearer {access_token}

It targets   Kibo Ventures → Portfolio → Fund IV → Theker,  discovers the files in
that folder (case-insensitive path walk), picks the most-recently-modified one, and
downloads its bytes through `/content`. Reuses scripts/sharepoint_client.py — no new deps.

CREDENTIALS
-----------
Reads AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET from .env.local
(repo root). Existing environment variables take precedence. The Azure app needs
the Microsoft Graph application permission `Sites.Read.All` (admin-consented).

EXAMPLES
--------
    python3 scripts/sharepoint_fetch_content_example.py
    python3 scripts/sharepoint_fetch_content_example.py "Portfolio/Fondo IV/Theker"
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from sharepoint_client import GRAPH_BASE, SharePointClient  # noqa: E402

SITE_URL = "https://kiboventures.sharepoint.com/sites/Company"
# Folder names carry numeric prefixes on SharePoint (e.g. "02_Portfolio",
# "2.4 Portfolio Fondo IV", "001. Theker Robotics"), so the path below uses
# substring terms that the case-insensitive walk resolves to the real folders.
DEFAULT_PATH = "Portfolio/Fondo IV/Theker"


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


def _match_folder(seg: str, folders: list[dict]) -> dict | None:
    """Find the folder matching `seg`: exact (case-insensitive) first, else a
    unique case-insensitive substring match (folders carry numeric prefixes like
    "02_Portfolio", so "Portfolio" should still resolve)."""
    low = seg.lower()
    exact = [f for f in folders if f["name"].lower() == low]
    if exact:
        return exact[0]
    subs = [f for f in folders if low in f["name"].lower()]
    return subs[0] if len(subs) == 1 else None


def _resolve_path(client: SharePointClient, drive_id: str, segments: list[str]) -> str:
    """Walk `segments` level-by-level, matching each folder case-insensitively.

    Returns the actual (correctly-cased) path within the drive. Raises
    FileNotFoundError listing the available children when a segment can't be found.
    """
    resolved: list[str] = []
    for seg in segments:
        parent = "/".join(resolved)
        children = client._list_folder(drive_id, parent)
        folders = [c for c in children if c.get("folder") is not None]
        match = _match_folder(seg, folders)
        if match is None:
            avail = ", ".join(sorted(f["name"] for f in folders)) or "(empty)"
            where = f"/{parent}" if parent else " (drive root)"
            raise FileNotFoundError(
                f"Folder '{seg}' not found under{where}.\n  Available: {avail}"
            )
        resolved.append(match["name"])
        print(f"  ✓ {'/'.join(resolved)}/")
    return "/".join(resolved)


def main() -> int:
    _load_env_local()

    try:
        client = SharePointClient(
            tenant_id=os.environ["AZURE_TENANT_ID"],
            client_id=os.environ["AZURE_CLIENT_ID"],
            client_secret=os.environ["AZURE_CLIENT_SECRET"],
        )
    except KeyError as e:
        print(f"Missing credential env var: {e}. Set it in .env.local.", file=sys.stderr)
        return 1

    path_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    segments = [s for s in path_arg.split("/") if s]

    # 1. Resolve the site, then the drive (document library) for the first segment.
    print(f"Site: {SITE_URL}")
    site_id = client._get_site_id(SITE_URL)
    drive_id, rel_path = client._resolve_drive(site_id, path_arg)
    # _resolve_drive strips a leading library name; rebuild the remaining segments to walk.
    walk_segments = [s for s in rel_path.split("/") if s]
    print(f"Drive: {drive_id}")

    # 2. Discover: walk the folder path (tolerant of name casing).
    print(f"\nResolving path: {' → '.join(segments)}")
    folder_path = _resolve_path(client, drive_id, walk_segments)

    # 3. List the files in the target folder. If it holds only subfolders,
    #    recurse with traverse_folder to find documents anywhere beneath it.
    items = client._list_folder(drive_id, folder_path)
    files = [
        {"name": i["name"], "id": i["id"], "size": i.get("size", 0),
         "lastModifiedDateTime": i.get("lastModifiedDateTime", ""), "label": i["name"]}
        for i in items if i.get("file") is not None
    ]
    if not files:
        print(f"\nNo direct files in '{folder_path}/' — searching subfolders…")
        files = [
            {"name": it["name"], "id": it["id"], "size": it.get("size", 0),
             "lastModifiedDateTime": it.get("lastModifiedDateTime", ""), "label": it["sp_path"]}
            for it in client.traverse_folder(SITE_URL, folder_path)
            if it["type"] == "file"
        ]
    if not files:
        print(f"\nNo files found under '{folder_path}'.", file=sys.stderr)
        return 1

    print(f"\nFiles found ({len(files)}):")
    for f in sorted(files, key=lambda x: x.get("lastModifiedDateTime", ""), reverse=True)[:15]:
        print(f"  {f.get('lastModifiedDateTime', '?'):25} {f.get('size', 0):>12,} B  {f['label']}")

    # 4. Pick the most-recently-modified file and download it via /content.
    target = max(files, key=lambda f: f.get("lastModifiedDateTime", ""))
    content_url = f"{GRAPH_BASE}/drives/{drive_id}/items/{target['id']}/content"
    print(f"\nDownloading most-recent file: {target['label']}")
    print(f"GET {content_url}")

    data = client._download_file(drive_id, target["id"])  # the /content call

    # 5. Save the bytes.
    out_dir = os.path.join(ROOT, "downloads")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, target["name"])
    with open(out_path, "wb") as fh:
        fh.write(data)
    print(f"\nSaved {len(data):,} bytes → {os.path.relpath(out_path, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
