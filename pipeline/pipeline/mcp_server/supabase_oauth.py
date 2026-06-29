from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from pipeline.config import settings
from pipeline.errors import AdapterError

from ._runtime import anon_key, get_http, supabase_callback_url


def new_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for the Supabase (Google) login leg."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def google_authorize_url(code_challenge: str, session_id: str) -> str:
    """Supabase GoTrue authorize URL for Google with PKCE. Supabase redirects to
    our /supabase-callback (with session_id) carrying a one-time `code`.

    `prompt=select_account` is forwarded by GoTrue to Google so every MCP
    authorization shows the Google account chooser. Without it, Google silently
    reuses whichever account the device is already signed into — so switching
    Claude accounts on the same device would re-mint a token for the *previous*
    identity instead of the one the user intends to log in as."""
    redirect_to = f"{supabase_callback_url()}?session_id={session_id}"
    params = {
        "provider": "google",
        "flow_type": "pkce",
        "code_challenge": code_challenge,
        "code_challenge_method": "s256",
        "redirect_to": redirect_to,
        "prompt": "select_account",
    }
    return f"{settings.supabase_url}/auth/v1/authorize?{urlencode(params)}"


async def exchange_code(auth_code: str, code_verifier: str) -> dict[str, Any]:
    """Exchange the GoTrue `code` for a Supabase session (PKCE). Returns the
    GoTrue token payload: access_token, refresh_token, expires_in, user{…}."""
    return await _token_request(
        "pkce", {"auth_code": auth_code, "code_verifier": code_verifier}
    )


async def refresh(refresh_token: str) -> dict[str, Any]:
    return await _token_request("refresh_token", {"refresh_token": refresh_token})


async def _token_request(grant_type: str, body: dict[str, str]) -> dict[str, Any]:
    try:
        resp = await get_http().post(
            f"{settings.supabase_url}/auth/v1/token?grant_type={grant_type}",
            headers={"apikey": anon_key(), "Content-Type": "application/json"},
            json=body,
            timeout=settings.web_scrape_timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AdapterError(
            f"Supabase token ({grant_type}) HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.RequestError as exc:
        raise AdapterError(f"Supabase token ({grant_type}) request failed: {exc}")
    return resp.json()
