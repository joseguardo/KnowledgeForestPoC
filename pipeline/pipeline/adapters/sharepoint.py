# ── Azure App Registration Setup (one-time) ──────────────────────────────────
#
# 1. Go to https://portal.azure.com → Azure Active Directory → App registrations
# 2. Click "New registration"
#    - Name: e.g. "PortCo-KPI-Sync"
#    - Supported account types: "Accounts in this organizational directory only"
#    - Redirect URI: leave blank
# 3. After creation, copy:
#    - Application (client) ID  → AZURE_CLIENT_ID in .env
#    - Directory (tenant) ID    → AZURE_TENANT_ID in .env
# 4. Go to "Certificates & secrets" → New client secret
#    - Copy the value immediately → AZURE_CLIENT_SECRET in .env
# 5. Go to "API permissions" → Add a permission → Microsoft Graph
#    - Application permissions → Sites.Read.All
#    - Click "Grant admin consent" (requires Global Admin or SharePoint Admin)
#
# This module is the canonical home of the SharePoint Graph client. The standalone
# scripts (scripts/sharepoint_client.py) re-export from here so there is one source
# of truth; the MCP server's fetch_document tool imports it directly.
# ─────────────────────────────────────────────────────────────────────────────
import re
from urllib.parse import unquote, urlparse

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class SharePointClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self._app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        self._token: str | None = None

    def get_latest_excel(
        self, site_url: str, base_path: str, file_match: str = "KPIs Financieros"
    ) -> tuple[bytes, str, str]:
        """Return (file_bytes, filename, yyyymm) for the most recent KPI Excel.

        Supports two folder layouts:
          - Flat:   base_path/YYYYMM/          (e.g. White Vega: 202602/)
          - Nested: base_path/YYYY/YYYY MM/    (e.g. Azenea: 2026/2026 02/)

        The first segment of base_path may be a SharePoint document library name
        (e.g. "Documentos compartidos"). If it matches a named library, that drive
        is used automatically — no config change required.
        """
        site_id = self._get_site_id(site_url)
        drive_id, folder_path = self._resolve_drive(site_id, base_path)
        month_path, yyyymm = self._resolve_latest_month_folder(drive_id, folder_path)
        subfolder_items = self._list_folder(drive_id, month_path)
        excel_files = [
            f for f in subfolder_items
            if (not file_match or file_match in f["name"])
            and f["name"].lower().endswith((".xlsx", ".xls", ".xlsm"))
        ]
        if len(excel_files) == 0:
            label = f"'{file_match}' " if file_match else ""
            raise FileNotFoundError(
                f"No {label}Excel file found in {month_path}"
            )
        if len(excel_files) > 1:
            excel_files = [max(excel_files, key=lambda f: f.get("size", 0))]
            print(f"Multiple Excel files found — picking largest: {excel_files[0]['name']}")
        file_item = excel_files[0]
        file_bytes = self._download_file(drive_id, file_item["id"])
        return file_bytes, file_item["name"], yyyymm

    def find_sites(self, search_term: str) -> list[dict]:
        """Search SharePoint sites by name. Returns matching sites.

        Each dict has keys: name, displayName, webUrl, id.
        """
        url = f"{GRAPH_BASE}/sites?search={search_term}"
        sites = []
        while url:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for s in data.get("value", []):
                sites.append({
                    "name": s.get("name", ""),
                    "displayName": s.get("displayName", ""),
                    "webUrl": s.get("webUrl", ""),
                    "id": s.get("id", ""),
                })
            url = data.get("@odata.nextLink")
        return sites

    def list_drives(self, site_url: str) -> list[dict]:
        """List the document libraries (drives) of a site.

        Returns list of dicts with keys: name, id.
        """
        site_id = self._get_site_id(site_url)
        resp = requests.get(
            f"{GRAPH_BASE}/sites/{site_id}/drives",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return [
            {"name": d["name"], "id": d["id"]}
            for d in resp.json().get("value", [])
        ]

    def list_files(self, site_url: str, folder_path: str, name_prefix: str = "") -> list[dict]:
        """List files in a SharePoint folder, optionally filtered by name prefix.
        Returns list of dicts with keys: name, id, size.
        """
        site_id = self._get_site_id(site_url)
        drive_id, rel_path = self._resolve_drive(site_id, folder_path)
        items = self._list_folder(drive_id, rel_path)
        files = [i for i in items if i.get("file") is not None]
        if name_prefix:
            files = [f for f in files if f["name"].startswith(name_prefix)]
        return [{"name": f["name"], "id": f["id"], "size": f.get("size", 0)} for f in files]

    def download_file(self, site_url: str, folder_path: str, file_name: str) -> bytes:
        """Download a specific file by name from a SharePoint folder."""
        site_id = self._get_site_id(site_url)
        drive_id, rel_path = self._resolve_drive(site_id, folder_path)
        items = self._list_folder(drive_id, rel_path)
        match = next((i for i in items if i["name"] == file_name), None)
        if not match:
            raise FileNotFoundError(f"{file_name} not found in {folder_path}")
        return self._download_file(drive_id, match["id"])

    def _resolve_drive(self, site_id: str, base_path: str) -> tuple[str, str]:
        """Return (drive_id, relative_path_within_drive).

        If the first segment of base_path matches a named document library, that
        library's drive ID is returned and the segment is stripped from the path.
        Otherwise the site's default drive is used and base_path is unchanged.
        """
        parts = base_path.split("/", 1)
        first_segment = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        # Check all drives for the site
        drives_resp = requests.get(
            f"{GRAPH_BASE}/sites/{site_id}/drives",
            headers=self._headers(),
            timeout=30,
        )
        drives_resp.raise_for_status()
        drives = drives_resp.json().get("value", [])

        for drive in drives:
            if drive["name"].lower() == first_segment.lower():
                return drive["id"], rest

        # No named library matched — fall back to the site default drive with full path
        default_resp = requests.get(
            f"{GRAPH_BASE}/sites/{site_id}/drive",
            headers=self._headers(),
            timeout=30,
        )
        default_resp.raise_for_status()
        return default_resp.json()["id"], base_path

    def _resolve_latest_month_folder(self, drive_id: str, base_path: str) -> tuple[str, str]:
        """Return (folder_path, yyyymm) for the most recent month folder.

        Tries flat layout (YYYYMM) first, then nested (YYYY/YYYY MM).
        """
        items = self._list_folder(drive_id, base_path)
        folders = [i for i in items if i.get("folder") is not None]

        # Flat layout: direct YYYYMM subfolders (e.g. 202602/)
        flat = [f for f in folders if re.fullmatch(r"\d{6}", f["name"])]
        if flat:
            latest = max(flat, key=lambda f: f["name"])
            yyyymm = latest["name"]
            return f"{base_path}/{yyyymm}", yyyymm

        # Nested layout: YYYY/ year folders containing YYYY MM/ month folders
        year_folders = [f for f in folders if re.fullmatch(r"\d{4}", f["name"])]
        if year_folders:
            latest_year = max(year_folders, key=lambda f: f["name"])
            year_path = f"{base_path}/{latest_year['name']}"
            month_items = self._list_folder(drive_id, year_path)
            month_folders = [
                f for f in month_items
                if f.get("folder") is not None and re.fullmatch(r"\d{4} \d{2}", f["name"])
            ]
            if month_folders:
                latest_month = max(month_folders, key=lambda f: f["name"])
                yyyymm = latest_month["name"].replace(" ", "")  # "2026 02" → "202602"
                return f"{year_path}/{latest_month['name']}", yyyymm

        raise FileNotFoundError(
            f"No YYYYMM or YYYY/YYYY MM folders found under {base_path}"
        )

    def _get_token(self) -> str:
        result = self._app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise RuntimeError(
                f"Azure auth failed: {result.get('error_description', result)}"
            )
        return result["access_token"]

    def _headers(self) -> dict:
        if not self._token:
            self._token = self._get_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _get_site_id(self, site_url: str) -> str:
        parsed = urlparse(site_url)
        url = f"{GRAPH_BASE}/sites/{parsed.hostname}:{parsed.path}"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()["id"]

    def _list_folder(self, drive_id: str, folder_path: str) -> list[dict]:
        if folder_path:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{folder_path}:/children"
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"
        items = []
        while url:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items

    def _download_file(self, drive_id: str, file_id: str) -> bytes:
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{file_id}/content"
        resp = requests.get(url, headers=self._headers(), allow_redirects=True, timeout=30)
        resp.raise_for_status()
        return resp.content

    # ── Folder tree traversal ─────────────────────────────────────────────────

    def traverse_folder(self, site_url: str, folder_path: str) -> list[dict]:
        """Recursively traverse a folder tree. Returns a flat list of all items.

        Each item dict contains:
          id, name, type ('file'|'folder'), webUrl, lastModifiedDateTime,
          sp_path (relative to the root folder), parent_id (SP item ID of parent)
        """
        site_id = self._get_site_id(site_url)
        drive_id, rel_path = self._resolve_drive(site_id, folder_path)
        root = self._get_item_by_path(drive_id, rel_path)
        results: list[dict] = []
        self._traverse_recursive(drive_id, root["id"], "", results)
        return results

    def enumerate_drive(self, drive_id: str) -> list[dict]:
        """Enumerate EVERY item in a drive via the delta endpoint.

        Graph returns all folders and files as one flat, paginated stream
        (~hundreds per page) instead of one request per folder. Far fewer
        round-trips than recursive child listing, so it's dramatically faster
        for full-tree extraction. Each item carries parentReference.path, from
        which sp_path is reconstructed client-side.

        Returns the same shape as `traverse_folder`:
          id, name, type ('file'|'folder'), webUrl, lastModifiedDateTime,
          size, sp_path (relative to the drive root), parent_id.
        """
        url = (
            f"{GRAPH_BASE}/drives/{drive_id}/root/delta"
            "?$select=id,name,folder,file,size,webUrl,lastModifiedDateTime,parentReference"
            "&$top=500"
        )
        # A delta feed may emit the same item more than once; Graph requires the
        # caller to dedupe by id and keep the last occurrence. Keyed dict does both.
        by_id: dict[str, dict] = {}
        while url:
            resp = requests.get(url, headers=self._headers(), timeout=60)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("value", []):
                # Skip the drive root itself and tombstones for deleted items.
                if "root" in item or "deleted" in item:
                    continue
                parent_ref = item.get("parentReference") or {}
                # parent path looks like "/drive/root:/Folder/Sub" (URL-encoded);
                # the segment after "root:" is the parent's path within the drive.
                parent_path = parent_ref.get("path", "") or ""
                rel_parent = ""
                if "root:" in parent_path:
                    rel_parent = unquote(parent_path.split("root:", 1)[1]).lstrip("/")
                name = item["name"]
                sp_path = f"{rel_parent}/{name}" if rel_parent else name
                item_type = "folder" if "folder" in item else "file"
                by_id[item["id"]] = {
                    "id": item["id"],
                    "name": name,
                    "type": item_type,
                    "webUrl": item.get("webUrl", ""),
                    "lastModifiedDateTime": item.get("lastModifiedDateTime", ""),
                    "size": item.get("size", 0),
                    "sp_path": sp_path,
                    "parent_id": parent_ref.get("id", ""),
                }
            # delta paginates with @odata.nextLink and ends with @odata.deltaLink.
            url = data.get("@odata.nextLink")
        return list(by_id.values())

    def _get_item_by_path(self, drive_id: str, item_path: str) -> dict:
        if item_path:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{item_path}"
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _get_item_by_id(self, drive_id: str, item_id: str) -> dict:
        """Fetch a driveItem's metadata by ID (name, size, file/folder facet,
        webUrl, parentReference.path). The parent path is what callers use to
        verify which folder the item lives under before downloading it."""
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _traverse_recursive(
        self, drive_id: str, folder_id: str, current_path: str, results: list
    ) -> None:
        children = self._list_folder_by_id(drive_id, folder_id)
        for item in children:
            item_path = f"{current_path}/{item['name']}" if current_path else item["name"]
            item_type = "folder" if "folder" in item else "file"
            results.append({
                "id": item["id"],
                "name": item["name"],
                "type": item_type,
                "webUrl": item.get("webUrl", ""),
                "lastModifiedDateTime": item.get("lastModifiedDateTime", ""),
                "size": item.get("size", 0),
                "sp_path": item_path,
                "parent_id": folder_id,
            })
            if item_type == "folder":
                self._traverse_recursive(drive_id, item["id"], item_path, results)

    def _list_folder_by_id(self, drive_id: str, folder_id: str) -> list[dict]:
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{folder_id}/children?$top=500"
        items = []
        while url:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items
