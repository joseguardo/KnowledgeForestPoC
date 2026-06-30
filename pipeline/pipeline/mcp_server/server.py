from __future__ import annotations

import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from pipeline.access import ensure_tenant_member

from ._runtime import aclose_http, allowed_email_domains, get_http, mcp_base_url
from .instance import mcp
from .oauth_provider import AUTH_CODE_TTL, REQUIRED_SCOPE
from .storage import delete as state_delete
from .storage import get as state_get
from .storage import put as state_put
from .supabase_oauth import exchange_code
from .tenant_map import resolve_tenants

log = logging.getLogger(__name__)

MOUNT_PATH = "/api/mcp"
_asgi_app = None


def build_mcp_asgi_app():
    """Build (once) the FastMCP streamable-HTTP Starlette app and append our
    custom /supabase-callback route. Calling this also lazily creates the
    transport session_manager that mcp_lifespan() must run."""
    global _asgi_app
    if _asgi_app is None:
        app = mcp.streamable_http_app()
        app.routes.append(Route("/supabase-callback", _supabase_callback, methods=["GET"]))
        _asgi_app = app
    return _asgi_app


# ── /supabase-callback: Supabase (Google) → one-time auth code → client ──
async def _supabase_callback(request: Request) -> HTMLResponse | RedirectResponse:
    code = request.query_params.get("code")
    session_id = request.query_params.get("session_id")
    err = request.query_params.get("error_description") or request.query_params.get("error")
    if err:
        return HTMLResponse(f"<h1>Login failed</h1><p>{err}</p>", status_code=400)
    if not code or not session_id:
        return HTMLResponse("<h1>Login failed</h1><p>Missing code/session.</p>", status_code=400)

    session = await state_get(session_id)
    if not session:
        return HTMLResponse("<h1>Login expired</h1><p>Please retry.</p>", status_code=400)

    try:
        sess = await exchange_code(code, session["supabase_code_verifier"])
    except Exception as exc:  # AdapterError etc.
        return HTMLResponse(f"<h1>Login failed</h1><p>{exc}</p>", status_code=400)

    user = sess.get("user") or {}
    uid = user.get("id")
    email = (user.get("email") or "").strip().lower()
    allowed = allowed_email_domains()
    if not uid or not email:
        return HTMLResponse("<h1>Login failed</h1><p>No user on session.</p>", status_code=400)
    if allowed and email.split("@")[-1] not in allowed:
        return HTMLResponse(
            f"<h1>Access denied</h1><p>{email} is not in an allowed domain.</p>", status_code=403
        )

    # Auto-assign tenant membership from the email (additive: a user can belong to
    # several firms) so the user immediately sees their firms' data via RLS.
    # Best-effort: a failure here must not block login.
    for tenant in resolve_tenants(email):
        try:
            await ensure_tenant_member(get_http(), uid, tenant)
        except Exception as exc:  # noqa: BLE001 — never block login on this
            log.warning("tenant auto-assign failed for %s → %s: %s", email, tenant, exc)

    mcp_code = secrets.token_urlsafe(32)
    await state_put(
        "auth_code",
        mcp_code,
        {
            "client_id": session["client_id"],
            "redirect_uri": session["redirect_uri"],
            "redirect_uri_provided_explicitly": session["redirect_uri_provided_explicitly"],
            "client_code_challenge": session["client_code_challenge"],
            "scopes": session["scopes"],
            "resource": session.get("resource"),
            "expires_at": time.time() + AUTH_CODE_TTL,  # AuthorizationCode wants epoch float
            "subject": uid,
            "email": email,
            "supabase_access": sess["access_token"],
            "supabase_refresh": sess.get("refresh_token"),
            "supabase_expires_in": sess.get("expires_in"),
        },
        ttl_seconds=AUTH_CODE_TTL,
    )
    await state_delete(session_id)

    redirect = construct_redirect_uri(
        session["redirect_uri"], code=mcp_code, state=session.get("client_state")
    )
    return RedirectResponse(redirect, status_code=302)


# ── OAuth metadata (served at the HOST root, where MCP clients look) ──
def _authorization_server_metadata() -> dict[str, Any]:
    base = mcp_base_url()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "revocation_endpoint": f"{base}/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": [REQUIRED_SCOPE],
    }


def _protected_resource_metadata() -> dict[str, Any]:
    base = mcp_base_url()
    return {
        "resource": base,
        "authorization_servers": [base],
        "scopes_supported": [REQUIRED_SCOPE],
        "bearer_methods_supported": ["header"],
    }


def register_mcp_routes(app: FastAPI) -> None:
    """Mount the MCP ASGI sub-app at /api/mcp and register the host-root OAuth
    metadata overrides + a trailing-slash fix. Call once, after app creation."""
    asgi = build_mcp_asgi_app()

    # A 307 redirect for the missing trailing slash would strip the Authorization
    # header and break MCP clients — rewrite the path instead so /api/mcp and
    # /api/mcp/ behave identically.
    @app.middleware("http")
    async def _mcp_trailing_slash(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.scope["path"] == MOUNT_PATH:
            request.scope["path"] = MOUNT_PATH + "/"
        return await call_next(request)

    async def _as_meta(_request: Request) -> JSONResponse:
        return JSONResponse(_authorization_server_metadata())

    async def _pr_meta(_request: Request) -> JSONResponse:
        return JSONResponse(_protected_resource_metadata())

    # RFC 8414 / 9728 path-insertion: clients fetch these at the host root with
    # the resource path (/api/mcp) appended.
    app.add_route("/.well-known/oauth-authorization-server/api/mcp", _as_meta, methods=["GET"])
    app.add_route("/.well-known/oauth-protected-resource/api/mcp", _pr_meta, methods=["GET"])

    app.mount(MOUNT_PATH, asgi)


async def _warm_docling() -> None:
    """Best-effort warmup of the Docling converter singleton at server boot.

    Runs the (slow, ~4 s, possibly model-downloading) build off the event loop so
    boot isn't blocked, and swallows any error (e.g. docling not installed) — the
    fetch_document tool still works, just paying the build cost lazily on first use.
    """
    from pipeline.adapters.docling_extract.converter import warm_converter

    try:
        await asyncio.to_thread(warm_converter)
        log.info("docling converter warmed at startup")
    except Exception as exc:  # noqa: BLE001 — warmup is best-effort, never crash boot
        log.warning("docling converter warmup failed (will build lazily): %s", exc)


@asynccontextmanager
async def mcp_lifespan():
    """Run the streamable-HTTP transport's session manager. Mounted sub-apps
    don't run their own lifespan, so the parent app must enter this."""
    build_mcp_asgi_app()  # ensure session_manager exists
    # Warm the Docling converter in the background so the model load (~4 s) is paid
    # once at boot, not on the first fetch_document call.
    asyncio.create_task(_warm_docling())
    async with mcp.session_manager.run():
        try:
            yield
        finally:
            await aclose_http()
