from __future__ import annotations

import asyncio
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from pipeline.config import settings

from ._runtime import allowed_email_domains

# Local Supabase-JWT verification, mirroring the platform MCP's _decode_token
# (the same validator shape its web UI uses): verify the signature locally —
# HS256 with the legacy shared secret, or ES256/RS256 via the project JWKS —
# enforce aud=authenticated + expiry, then the email-domain allowlist. No
# per-request network hop (JWKS is fetched once and cached).

_AUDIENCE = "authenticated"
_jwks_client: PyJWKClient | None = None


@dataclass
class AuthUser:
    uid: str
    email: str


class AuthError(Exception):
    """Token is missing/invalid/expired, or the user's email domain isn't allowed."""


def _domain_ok(email: str) -> bool:
    allowed = allowed_email_domains()
    if not allowed:
        return True  # no allowlist configured → don't block (demo convenience)
    return email.split("@")[-1].lower() in allowed


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(url, cache_keys=True)
    return _jwks_client


def _decode(token: str) -> dict:
    """Verify the token's signature + standard claims. Raises AuthError for a
    misconfiguration/unsupported alg, or jwt.PyJWTError for an invalid token."""
    alg = jwt.get_unverified_header(token).get("alg", "")
    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise AuthError("HS256 token but SUPABASE_JWT_SECRET is not set")
        key: object = settings.supabase_jwt_secret
    elif alg in ("ES256", "RS256"):
        key = _jwks().get_signing_key_from_jwt(token).key
    else:
        raise AuthError(f"unsupported token alg: {alg!r}")
    return jwt.decode(
        token,
        key,
        algorithms=[alg],
        audience=_AUDIENCE,
        options={"require": ["exp"]},
    )


async def user_from_token(token: str) -> AuthUser | None:
    """Validate a Supabase access token locally. Returns the user on success,
    None if the token is invalid/expired, raises AuthError if the email domain
    isn't allowed (a valid token we still refuse)."""
    try:
        # The asymmetric path may do a one-off (cached) JWKS fetch; keep it off
        # the event loop. HS256 is pure-CPU and returns immediately.
        claims = await asyncio.to_thread(_decode, token)
    except jwt.PyJWTError:
        return None

    uid = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    if not uid or not email:
        return None
    if not _domain_ok(email):
        raise AuthError(f"email domain not allowed: {email}")
    return AuthUser(uid=uid, email=email)
