from __future__ import annotations

from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

from ._runtime import mcp_base_url
from .oauth_provider import REQUIRED_SCOPE, KiboOAuthProvider

# Singleton FastMCP (official mcp SDK). stateless_http=True: each request
# authenticates independently (no server-side session), which suits a mounted
# sub-app. streamable_http_path="/" so, when mounted at /api/mcp, the transport
# endpoint is /api/mcp/ and the OAuth routes are /api/mcp/{authorize,token,…}.

_base = mcp_base_url()

mcp = FastMCP(
    name="kibo-knowledge",
    stateless_http=True,
    streamable_http_path="/",
    auth_server_provider=KiboOAuthProvider(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(_base),
        resource_server_url=AnyHttpUrl(_base),
        required_scopes=[REQUIRED_SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[REQUIRED_SCOPE],
            default_scopes=[REQUIRED_SCOPE],
        ),
        revocation_options=RevocationOptions(enabled=True),
    ),
)

# Register tools by import side-effect (each module uses @mcp.tool()).
from . import tools  # noqa: E402,F401
