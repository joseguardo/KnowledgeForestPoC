from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import unquote

from pydantic import Field

from pipeline.adapters.docling_extract import extract
from pipeline.adapters.document import DocumentAdapter
from pipeline.adapters.sharepoint import SharePointClient
from pipeline.config import settings

from ..instance import mcp
from ..runner import NotAuthenticated, caller
from ..tenant_map import KIBO_TENANT, resolve_tenants

# Formats Docling parses server-side into rich markdown + financial facts.
_DOCLING_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".html", ".htm"}

# Lazily-built, process-wide client. msal caches the app token on the instance,
# so reusing it avoids re-authenticating to Azure on every call.
_client: SharePointClient | None = None


def _sharepoint() -> SharePointClient:
    global _client
    if _client is None:
        missing = [
            name
            for name in ("azure_tenant_id", "azure_client_id", "azure_client_secret")
            if not getattr(settings, name)
        ]
        if missing:
            raise RuntimeError(
                f"SharePoint is not configured; set {', '.join(m.upper() for m in missing)} "
                "in the pipeline .env."
            )
        _client = SharePointClient(
            settings.azure_tenant_id,  # type: ignore[arg-type]
            settings.azure_client_id,  # type: ignore[arg-type]
            settings.azure_client_secret,  # type: ignore[arg-type]
        )
    return _client


def _portfolio_path(item: dict) -> str:
    """Return the item's drive-relative path, asserting it lives under the
    Portfolio root. parentReference.path looks like
    "/drives/{id}/root:/02_Portfolio/2.4 …" (URL-encoded); the segment after
    "root:" is the parent folder path within the drive."""
    parent_path = (item.get("parentReference") or {}).get("path", "") or ""
    rel_parent = ""
    if "root:" in parent_path:
        rel_parent = unquote(parent_path.split("root:", 1)[1]).lstrip("/")
    root = settings.sharepoint_portfolio_root
    first_segment = rel_parent.split("/", 1)[0] if rel_parent else ""
    if first_segment.lower() != root.lower():
        raise PermissionError(
            f"item is not inside the Portfolio folder ('{root}/…'); "
            "fetch_document only serves Portfolio documents."
        )
    return f"{rel_parent}/{item['name']}" if rel_parent else item["name"]


@mcp.tool()
async def fetch_document(
    drive_id: Annotated[str, Field(description="SharePoint drive (document library) ID.")],
    item_id: Annotated[str, Field(description="SharePoint driveItem ID of the document to fetch.")],
) -> dict[str, Any]:
    """Fetch a document from the Kibo Portfolio folder on SharePoint and return
    clean markdown plus extracted financial facts. Scoped EXCLUSIVELY to the
    Portfolio library: the drive must be the Portfolio drive and the item must
    live under the Portfolio root folder, otherwise the request is rejected.
    Restricted to Kibo tenant members.

    PDFs, Word (.docx), PowerPoint (.pptx), Excel (.xlsx/.xlsm) and HTML are
    parsed server-side by Docling into markdown and structured financial facts
    (with a quality grade, page count, and a needs_review flag); if Docling
    fails on a given document the tool falls back to a lightweight text
    extractor. Emails (.eml/.msg) and text/markdown (.txt/.md) are read with the
    lightweight extractor and return markdown only (no facts).

    Returns a dict with: name, title, sp_path, web_url, size, grade (str|None),
    pages (int|None), markdown (str, capped), markdown_truncated (bool), facts
    (capped list[dict]), fact_count (int, full pre-cap count), facts_truncated
    (bool), needs_review (bool), warning (str|None), and text (DEPRECATED alias
    of markdown)."""
    ctx = caller()
    if KIBO_TENANT not in resolve_tenants(ctx.email):
        raise NotAuthenticated("fetch_document is restricted to Kibo tenant members.")

    # Guard 1: pin the drive to the Portfolio library.
    if drive_id != settings.sharepoint_portfolio_drive_id:
        raise PermissionError("drive_id is not the Portfolio drive.")

    client = _sharepoint()
    # Guard 2: the item must be a file living under the Portfolio root folder.
    item = await asyncio.to_thread(client._get_item_by_id, drive_id, item_id)
    if item.get("folder") is not None:
        raise ValueError("item is a folder, not a document.")
    sp_path = _portfolio_path(item)

    size = int(item.get("size", 0) or 0)
    if size > settings.max_upload_bytes:
        raise ValueError(
            f"document is {size:,} bytes, over the {settings.max_upload_bytes:,}-byte limit."
        )

    data = await asyncio.to_thread(client._download_file, drive_id, item_id)

    # Step 6: parse by extension. Docling formats get rich markdown + facts;
    # everything else (emails, text/markdown) goes through the lightweight
    # DocumentAdapter and returns markdown only.
    ext = Path(item["name"]).suffix.lower()
    markdown = ""
    grade: str | None = None
    pages: int | None = None
    facts: list[dict] = []
    fact_count = 0
    needs_review = False
    warning: str | None = None

    if ext in _DOCLING_EXTS:
        result = await extract(item["name"], data, minimum_grade=settings.docling_min_grade)
        if "error" in result:
            # Docling failed on this document: fall back to the lightweight
            # extractor so the tool stays resilient. If that ALSO raises, let it
            # propagate as a clean error.
            normalized = DocumentAdapter().process_file(item["name"], data)[0]
            markdown = normalized.content
            warning = f"docling failed ({result['error']}); used fallback extractor"
        else:
            markdown = result["markdown"]
            facts = result["facts"]
            fact_count = result["fact_count"]
            grade = result["grade"]
            pages = result["pages"]
            needs_review = result["needs_review"]
            warning = result["warning"]
    else:
        # Emails (.eml/.msg) and text/markdown (.txt/.md/.markdown), plus any
        # other non-Docling extension: lightweight extractor, markdown only.
        normalized = DocumentAdapter().process_file(item["name"], data)[0]
        markdown = normalized.content

    # MCP inline caps (owned here, not by extract()).
    md = markdown or ""
    markdown_truncated = len(md) > settings.docling_markdown_inline_cap
    if markdown_truncated:
        md = md[: settings.docling_markdown_inline_cap]

    facts_full = facts or []
    facts_truncated = len(facts_full) > settings.docling_facts_inline_cap
    facts = facts_full[: settings.docling_facts_inline_cap]

    return {
        "name": item["name"],
        "title": Path(item["name"]).stem,
        "sp_path": sp_path,
        "web_url": item.get("webUrl", ""),
        "size": size,
        "grade": grade,
        "pages": pages,
        "markdown": md,
        "markdown_truncated": markdown_truncated,
        "facts": facts,
        "fact_count": fact_count,
        "facts_truncated": facts_truncated,
        "needs_review": needs_review,
        "warning": warning,
        # DEPRECATED back-compat alias of `markdown`; kept until consumers are
        # migrated (DD-D1 to grep for readers of result["text"]).
        "text": md,
    }
