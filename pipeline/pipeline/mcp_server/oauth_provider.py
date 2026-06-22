from __future__ import annotations

import logging
import secrets

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from . import storage, supabase_oauth
from .auth import user_from_token

# We are the OAuth 2.1 Authorization Server; Supabase (Google) is the IdP. The
# tokens we issue to MCP clients ARE Supabase JWTs, passed through and never
# stored long-term. Only transient OAuth machinery lives in mcp_oauth_state:
#   client      dynamic registrations (long-lived)
#   session     a pending /authorize, bridging to the Supabase login (TTL 600s)
#   auth_code   the callback->token bridge holding the Supabase tokens (TTL 60s)

log = logging.getLogger(__name__)

REQUIRED_SCOPE = "mcp"
SESSION_TTL = 600
AUTH_CODE_TTL = 60


def _scope_list(client: OAuthClientInformationFull, params_scopes: list[str] | None) -> list[str]:
    return params_scopes or (client.scope.split() if client.scope else [REQUIRED_SCOPE])


class KiboOAuthProvider(OAuthAuthorizationServerProvider):
    # ── client registration (DCR) ──────────────────────────────────
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = await storage.get(client_id)
        if not data:
            return None
        return OAuthClientInformationFull.model_validate(data)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await storage.put("client", client_info.client_id, client_info.model_dump(mode="json"))

    # ── authorize: hand off to Supabase (Google) ───────────────────
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        session_id = secrets.token_urlsafe(24)
        verifier, challenge = supabase_oauth.new_pkce_pair()
        await storage.put(
            "session",
            session_id,
            {
                "client_id": client.client_id,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "client_state": params.state,
                "client_code_challenge": params.code_challenge,
                "scopes": _scope_list(client, params.scopes),
                "resource": params.resource,
                "supabase_code_verifier": verifier,
            },
            ttl_seconds=SESSION_TTL,
        )
        return supabase_oauth.google_authorize_url(challenge, session_id)

    # ── authorization code (minted in the /supabase-callback route) ─
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        data = await storage.get(authorization_code)
        if not data or data.get("client_id") != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=data["scopes"],
            expires_at=data["expires_at"],
            client_id=client.client_id,
            code_challenge=data["client_code_challenge"],
            redirect_uri=AnyUrl(data["redirect_uri"]),
            redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
            resource=data.get("resource"),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        data = await storage.get(authorization_code.code)
        if not data:
            from mcp.server.auth.provider import TokenError

            raise TokenError("invalid_grant", "authorization code expired or already used")
        await storage.delete(authorization_code.code)  # one-time use
        return OAuthToken(
            access_token=data["supabase_access"],
            token_type="Bearer",
            expires_in=data.get("supabase_expires_in"),
            refresh_token=data.get("supabase_refresh"),
            scope=" ".join(authorization_code.scopes),
        )

    # ── refresh: forwarded straight to Supabase ─────────────────────
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        # Refresh tokens are Supabase's; we don't track them. Hand back a stub so
        # the SDK proceeds to exchange_refresh_token, where Supabase validates it.
        return RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=[REQUIRED_SCOPE],
            expires_at=None,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        session = await supabase_oauth.refresh(refresh_token.token)
        return OAuthToken(
            access_token=session["access_token"],
            token_type="Bearer",
            expires_in=session.get("expires_in"),
            refresh_token=session.get("refresh_token"),
            scope=" ".join(scopes or [REQUIRED_SCOPE]),
        )

    # ── per-request validation ──────────────────────────────────────
    async def load_access_token(self, token: str) -> AccessToken | None:
        try:
            user = await user_from_token(token)
        except Exception:
            return None
        if user is None:
            return None
        return AccessToken(
            token=token,
            client_id="mcp",
            scopes=[REQUIRED_SCOPE],
            expires_at=None,  # GoTrue introspection already rejects expired tokens
            resource=None,
            subject=user.uid,
            claims={"email": user.email, "sub": user.uid},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Supabase anon REST has no token-revoke; rely on short expiry. Log + no-op.
        log.info("MCP revoke requested for client %s (no-op)", getattr(token, "client_id", "?"))
