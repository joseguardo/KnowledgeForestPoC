from __future__ import annotations

from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token


@dataclass
class CallerContext:
    token: str  # the raw Supabase JWT — forwarded to query-knowledge
    uid: str  # auth.users id — used for the per-user "user:{uid}" class
    email: str


class NotAuthenticated(Exception):
    pass


def caller() -> CallerContext:
    """Resolve the authenticated caller for the current tool invocation. The
    token was already validated by KiboOAuthProvider.load_access_token, so here
    we just read it off the request context. Raises if absent (shouldn't happen
    once auth is enforced, but fail closed)."""
    access = get_access_token()
    if access is None or not access.subject:
        raise NotAuthenticated("no authenticated user on the MCP request")
    claims = access.claims or {}
    return CallerContext(
        token=access.token,
        uid=access.subject,
        email=str(claims.get("email", "")),
    )
