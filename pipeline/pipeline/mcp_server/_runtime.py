from __future__ import annotations

import httpx

from pipeline.config import settings

# Shared async HTTP client + small helpers for the MCP server package. The MCP
# server runs as an ASGI sub-app mounted in the pipeline FastAPI app; its OAuth
# routes and tools all talk to Supabase (PostgREST / GoTrue / edge functions)
# over HTTP, so they share one client created lazily and closed in mcp_lifespan.

_http: httpx.AsyncClient | None = None


def get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=settings.web_scrape_timeout)
    return _http


async def aclose_http() -> None:
    global _http
    if _http is not None and not _http.is_closed:
        await _http.aclose()
    _http = None


def mcp_base_url() -> str:
    """The public OAuth issuer / resource id for the mounted MCP server."""
    return f"{settings.mcp_public_base_url.rstrip('/')}/api/mcp"


def supabase_callback_url() -> str:
    return f"{mcp_base_url()}/supabase-callback"


def allowed_email_domains() -> set[str]:
    return {
        d.strip().lower()
        for d in (settings.mcp_allowed_email_domains or "").split(",")
        if d.strip()
    }


def anon_key() -> str:
    key = settings.supabase_anon_key
    if not key:
        raise RuntimeError(
            "SUPABASE_ANON_KEY is not set; the MCP server needs it to call "
            "query-knowledge and the Supabase auth endpoints."
        )
    return key
