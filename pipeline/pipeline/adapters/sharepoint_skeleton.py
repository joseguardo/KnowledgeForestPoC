"""
sharepoint_skeleton.py — map a SharePoint drive enumeration into KnowledgeForest
folder/document POINTERS (body-less) + hierarchy/reconciliation EDGES.

This is the "skeleton" / mirror layer: we store STRUCTURE, not contents. Every
folder (type=folder) and file (type=document) becomes its own pointer so each can
carry its own acl and be queried/traversed directly. Bodies are fetched on demand
from Graph — the content URL is derivable from the canonical key, so nothing about
the file is stored beyond metadata.

Pure functions: feed it `SharePointClient.enumerate_drive()` (or `traverse_folder()`)
output — both yield the same item dict shape — plus the drive id, the Entra tenant,
an acl principal, and company/fund resolvers. The runner wires it to the edge funcs.

Key scheme (folders AND files, no special-casing):
    msgraph:{entraTenantId}:drive/{driveId}/item/{itemId}
itemId is stable across rename/move within a drive -> idempotent delta upserts.
Path / name / webUrl are deliberately EXCLUDED (mutable) and live in metadata.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

FOLDER_EMOJI = "📁"

# Portfolio fund folders -> existing `fund` pointer canonical_key.
# Fondo I has no fund pointer in the graph (Naluat never loaded it): None => the
# folder is still created, just not linked to a fund entity.
FUND_FOLDER_MAP: dict[str, str | None] = {
    "2.1 Portfolio Fondo I": None,
    "2.2 Portfolio Fondo II": "fund:naluat:fund-ii",
    "2.3 Portfolio Fondo III": "fund:naluat:fund-iii",
    "2.4 Portfolio Fondo IV": "fund:naluat:fund-iv",
    "2.5 Opportunity Fund I": "fund:naluat:opportunity-fund",
}

# Company folder names whose normalized form doesn't match an existing company
# label (mirrors naluat.RECONCILIATION). Values are canonical_keys or None when no
# pointer exists yet. Folder name here is the EXTRACTED company name (prefix stripped).
COMPANY_ALIAS: dict[str, str] = {
    # filled in as we confirm them, e.g.:
    # "Green Eagle": "company::ca61f0e5-...::greeneaglesolutions.com",
    # "Plenit": "company::ca61f0e5-...::jotelulu.com",
}

_COMPANY_PREFIX = re.compile(r"^\s*\d+\s*[-.]\s*(.+?)\s*$")


@dataclass(frozen=True)
class EdgeSpec:
    source_key: str
    target_key: str
    relationship_type: str
    why: str | None = None


@dataclass
class SkeletonPlan:
    pointers: list[dict]          # ready for ingest-batch BatchItem
    edges: list[EdgeSpec]
    unresolved_companies: list[str]   # company folders we couldn't link
    unresolved_funds: list[str]       # fund folders with no entity


def normalize(name: str) -> str:
    """Lowercase, strip all non-alphanumerics — for company label matching."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def item_key(entra_tenant: str, drive_id: str, item_id: str) -> str:
    return f"msgraph:{entra_tenant}:drive/{drive_id}/item/{item_id}"


def company_name_from_folder(folder_name: str) -> str | None:
    """`021 - CARTO` -> `CARTO`; `001. Theker Robotics` -> `Theker Robotics`.
    Returns None for non-company folders (e.g. `Z1. EXITS`, `Otros`)."""
    m = _COMPANY_PREFIX.match(folder_name or "")
    return m.group(1) if m else None


@dataclass
class PortfolioContext:
    fund_folder: str | None
    company_folder: str | None
    company_name: str | None
    rel_under_company: str   # path beneath the company folder ("" at company root)
    is_fund_folder: bool
    is_company_folder: bool


def portfolio_context(sp_path: str) -> PortfolioContext:
    """Parse a `02_Portfolio/...`-relative path into fund/company structure.

    sp_path is relative to the drive root, e.g.
      02_Portfolio/2.1 Portfolio Fondo I/021 - CARTO/3. RONDAS/term.pdf
    """
    segs = [s for s in (sp_path or "").split("/") if s]
    fund_folder = segs[1] if len(segs) >= 2 else None
    company_folder = segs[2] if len(segs) >= 3 else None
    company_name = company_name_from_folder(company_folder) if company_folder else None
    rel_under_company = "/".join(segs[3:]) if len(segs) >= 4 else ""
    return PortfolioContext(
        fund_folder=fund_folder,
        company_folder=company_folder,
        company_name=company_name,
        rel_under_company=rel_under_company,
        is_fund_folder=(len(segs) == 2 and fund_folder in FUND_FOLDER_MAP),
        is_company_folder=(len(segs) == 3 and company_name is not None),
    )


def _label(item: dict, ctx: PortfolioContext, drive_name: str) -> str:
    """Readable, hierarchy-bearing, says-it's-a-folder label."""
    is_folder = item["type"] == "folder"
    pre = f"{FOLDER_EMOJI} " if is_folder else ""
    sep = " › "
    if ctx.company_name:
        tail = ctx.rel_under_company.replace("/", sep)
        body = f"{ctx.company_name}{sep}{tail}" if tail else ctx.company_name
        return f"{pre}{body}"
    if ctx.fund_folder and len(item["sp_path"].split("/")) == 2:
        return f"{pre}{ctx.fund_folder}"
    # Fallbacks (02_Portfolio root, or non-portfolio paths in a full-drive run).
    return f"{pre}{item['sp_path'].replace('/', sep)}"


def build_skeleton(
    items: Iterable[dict],
    *,
    drive_id: str,
    drive_name: str,
    entra_tenant: str,
    acl_principal: str,
    resolve_company: Callable[[str], str | None],
    resolve_fund: Callable[[str], str | None] | None = None,
    library_root_key: str | None = None,
) -> SkeletonPlan:
    """Turn enumerated drive items into pointers + edges.

    - `resolve_company(company_name)` -> existing company canonical_key or None.
    - `resolve_fund(fund_folder_name)` -> existing fund canonical_key or None
      (defaults to FUND_FOLDER_MAP lookup).
    - `library_root_key`: canonical_key of the drive's root folder pointer; items
      whose parent isn't in this batch link here (full-drive runs). For a company
      slice, leave None — the company folder links to its entity instead.
    """
    items = list(items)
    if resolve_fund is None:
        resolve_fund = FUND_FOLDER_MAP.get

    present: dict[str, dict] = {it["id"]: it for it in items}
    key_of = {it["id"]: item_key(entra_tenant, drive_id, it["id"]) for it in items}

    pointers: list[dict] = []
    edges: list[EdgeSpec] = []
    unresolved_companies: list[str] = []
    unresolved_funds: list[str] = []

    for it in items:
        ctx = portfolio_context(it["sp_path"])
        ckey = key_of[it["id"]]
        ptype = "folder" if it["type"] == "folder" else "document"

        pointers.append({
            "label": _label(it, ctx, drive_name),
            "type": ptype,
            "canonical_key": ckey,
            "occurred_at": it.get("lastModifiedDateTime") or None,
            "principals": [acl_principal],
            "metadata": {
                "source": "sharepoint_skeleton",
                "drive_id": drive_id,
                "item_id": it["id"],
                "library": drive_name,
                "name": it["name"],
                "sp_path": it["sp_path"],
                "web_url": it.get("webUrl", ""),
                "size": it.get("size", 0),
                "last_modified": it.get("lastModifiedDateTime", ""),
                "fund_folder": ctx.fund_folder,
                "company": ctx.company_name,
                "is_folder": it["type"] == "folder",
            },
        })

        # ── Structural edge: child -> its SharePoint parent (if in this batch) ──
        parent_id = it.get("parent_id")
        rel = "folder_of" if it["type"] == "folder" else "documents_of"
        if parent_id in present:
            edges.append(EdgeSpec(ckey, key_of[parent_id], rel, why="sp_hierarchy"))
        elif library_root_key and "/" not in it["sp_path"]:
            # Top-level item of a full-drive run -> the library root pointer.
            edges.append(EdgeSpec(ckey, library_root_key, rel, why="sp_hierarchy"))

        # ── Reconciliation edges (additive): top folders -> their entity ──
        if ctx.is_fund_folder:
            fund_key = resolve_fund(ctx.fund_folder)
            if fund_key:
                edges.append(EdgeSpec(ckey, fund_key, "folder_of", why="fund_documents"))
            else:
                unresolved_funds.append(ctx.fund_folder)
        if ctx.is_company_folder:
            comp_key = COMPANY_ALIAS.get(ctx.company_name) or resolve_company(ctx.company_name)
            if comp_key:
                edges.append(EdgeSpec(ckey, comp_key, "folder_of", why="company_documents"))
            else:
                unresolved_companies.append(ctx.company_name)

    return SkeletonPlan(pointers, edges, unresolved_companies, unresolved_funds)
