from __future__ import annotations

import time

import httpx
import jwt
import pytest
from starlette.requests import Request
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from pipeline.config import settings
from pipeline.mcp_server import _runtime
from pipeline.mcp_server.auth import AuthError, AuthUser, user_from_token
from pipeline.mcp_server.oauth_provider import KiboOAuthProvider
from pipeline.mcp_server.runner import CallerContext


HS_SECRET = "test-jwt-secret-0123456789-abcdefghij"  # ≥32 bytes (HS256 hygiene)


@pytest.fixture(autouse=True)
def _anon_key(monkeypatch):
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    monkeypatch.setattr(settings, "supabase_jwt_secret", HS_SECRET)
    monkeypatch.setattr(settings, "mcp_allowed_email_domains", "kiboventures.com,nzalpha.com")


def _make_token(
    secret=HS_SECRET, *, sub="u1", email="Alice@kiboventures.com", aud="authenticated", exp_delta=3600
):
    payload = {"sub": sub, "email": email, "aud": aud, "exp": int(time.time()) + exp_delta}
    return jwt.encode(payload, secret, algorithm="HS256")


def _use_mock_http(monkeypatch, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(_runtime, "_http", client)
    return client


def _mem_storage(monkeypatch, module):
    """Patch a module's storage.{get,put,delete} with an in-memory dict."""
    store: dict[str, dict] = {}

    async def put(kind, id, data, ttl_seconds=None):
        store[id] = {"kind": kind, "data": data}

    async def get(id):
        row = store.get(id)
        return row["data"] if row else None

    async def delete(id):
        store.pop(id, None)

    monkeypatch.setattr(module, "get", get)
    monkeypatch.setattr(module, "put", put)
    monkeypatch.setattr(module, "delete", delete)
    return store


# ── auth.user_from_token (local JWT decode, HS256) ──────────────────


@pytest.mark.asyncio
async def test_user_from_token_valid():
    user = await user_from_token(_make_token())
    assert user == AuthUser(uid="u1", email="alice@kiboventures.com")  # email lowercased


@pytest.mark.asyncio
async def test_user_from_token_bad_signature_is_none():
    assert await user_from_token(_make_token(secret="wrong-secret-0123456789-abcdefghij")) is None


@pytest.mark.asyncio
async def test_user_from_token_wrong_audience_is_none():
    assert await user_from_token(_make_token(aud="anon")) is None


@pytest.mark.asyncio
async def test_user_from_token_expired_is_none():
    assert await user_from_token(_make_token(exp_delta=-10)) is None


@pytest.mark.asyncio
async def test_user_from_token_disallowed_domain_raises():
    with pytest.raises(AuthError):
        await user_from_token(_make_token(email="x@evil.com"))


# ── tool: query_knowledge forwards the caller JWT ───────────────────


@pytest.mark.asyncio
async def test_query_knowledge_forwards_user_jwt(monkeypatch):
    from pipeline.mcp_server.tools import query_knowledge as qk

    monkeypatch.setattr(
        qk, "caller", lambda: CallerContext(token="JWT123", uid="u1", email="a@kiboventures.com")
    )

    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/functions/v1/query-knowledge")
        seen["auth"] = req.headers.get("Authorization")
        seen["apikey"] = req.headers.get("apikey")
        return httpx.Response(
            200,
            json={
                "answer": "hi",
                "results": [{"id": "p1"}],
                "suggestions": ["next?"],
                "result_count": 1,
                "plan": {"internal": True},
                "context": {"secret": "x"},
            },
        )

    _use_mock_http(monkeypatch, handler)
    out = await qk.query_knowledge(query="what?", mode="answer")
    assert seen["auth"] == "Bearer JWT123"  # caller's JWT, not service role
    assert seen["apikey"] == "anon-key"
    # trimmed: internal planner/context dropped
    assert out == {"answer": "hi", "results": [{"id": "p1"}], "suggestions": ["next?"], "result_count": 1}
    assert "plan" not in out and "context" not in out


# ── tool: ingest_document tags the caller's private class ───────────


@pytest.mark.asyncio
async def test_ingest_document_uses_per_user_class(monkeypatch):
    from pipeline.mcp_server.tools import ingest_document as ing

    monkeypatch.setattr(
        ing, "caller", lambda: CallerContext(token="JWT", uid="u9", email="a@kiboventures.com")
    )

    calls = {}

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def ingest_document(self, *, title, content, access_class):
            calls["access_class"] = access_class
            return {"status": "created", "pointer_id": "ptr-1", "chunks_inserted": 2}

    monkeypatch.setattr(ing, "EdgeFunctionClient", FakeClient)
    monkeypatch.setattr(_runtime, "_http", httpx.AsyncClient())

    out = await ing.ingest_document(title="Note", content="body")
    # access_class user:{uid} → acl=[uid] at the write boundary (never public)
    assert calls["access_class"] == "user:u9"
    assert out["access_class"] == "user:u9"
    assert out["pointer_id"] == "ptr-1"


# ── OAuth provider ──────────────────────────────────────────────────


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="c1", redirect_uris=[AnyUrl("http://127.0.0.1:9/cb")], scope="mcp"
    )


@pytest.mark.asyncio
async def test_provider_register_and_get_client(monkeypatch):
    import pipeline.mcp_server.oauth_provider as op

    _mem_storage(monkeypatch, op.storage)
    p = KiboOAuthProvider()
    await p.register_client(_client())
    got = await p.get_client("c1")
    assert got is not None and got.client_id == "c1"
    assert await p.get_client("missing") is None


@pytest.mark.asyncio
async def test_provider_authorize_redirects_to_google(monkeypatch):
    import pipeline.mcp_server.oauth_provider as op

    store = _mem_storage(monkeypatch, op.storage)
    p = KiboOAuthProvider()
    params = AuthorizationParams(
        state="st",
        scopes=["mcp"],
        code_challenge="client-challenge",
        redirect_uri=AnyUrl("http://127.0.0.1:9/cb"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    url = await p.authorize(_client(), params)
    assert "/auth/v1/authorize" in url and "provider=google" in url and "flow_type=pkce" in url
    # forces Google's account chooser so switching accounts can't silently reuse
    # the device's existing Google session
    assert "prompt=select_account" in url
    # a pending session was stored with the client's challenge + a supabase verifier
    sessions = [v for v in store.values() if v["kind"] == "session"]
    assert len(sessions) == 1
    assert sessions[0]["data"]["client_code_challenge"] == "client-challenge"
    assert sessions[0]["data"]["supabase_code_verifier"]


@pytest.mark.asyncio
async def test_provider_exchange_authorization_code_returns_supabase_tokens(monkeypatch):
    import pipeline.mcp_server.oauth_provider as op

    store = _mem_storage(monkeypatch, op.storage)
    await store_put_auth_code(op, store)
    p = KiboOAuthProvider()

    code_obj = await p.load_authorization_code(_client(), "mcpcode")
    assert code_obj is not None and code_obj.code_challenge == "client-challenge"

    token = await p.exchange_authorization_code(_client(), code_obj)
    assert token.access_token == "sb-access" and token.refresh_token == "sb-refresh"
    # one-time: code consumed
    assert "mcpcode" not in store


async def store_put_auth_code(op, store):
    await op.storage.put(
        "auth_code",
        "mcpcode",
        {
            "client_id": "c1",
            "redirect_uri": "http://127.0.0.1:9/cb",
            "redirect_uri_provided_explicitly": True,
            "client_code_challenge": "client-challenge",
            "scopes": ["mcp"],
            "resource": None,
            "expires_at": time.time() + 60,
            "subject": "u1",
            "email": "a@kiboventures.com",
            "supabase_access": "sb-access",
            "supabase_refresh": "sb-refresh",
            "supabase_expires_in": 3600,
        },
    )


@pytest.mark.asyncio
async def test_provider_load_access_token(monkeypatch):
    import pipeline.mcp_server.oauth_provider as op

    async def fake_user(token):
        assert token == "tok"
        return AuthUser(uid="u1", email="a@kiboventures.com")

    monkeypatch.setattr(op, "user_from_token", fake_user)
    p = KiboOAuthProvider()
    access = await p.load_access_token("tok")
    assert access is not None and access.subject == "u1"
    assert access.claims["email"] == "a@kiboventures.com"


@pytest.mark.asyncio
async def test_provider_refresh_forwards_to_supabase(monkeypatch):
    import pipeline.mcp_server.oauth_provider as op
    from mcp.server.auth.provider import RefreshToken

    async def fake_refresh(rt):
        assert rt == "old-refresh"
        return {"access_token": "new-acc", "refresh_token": "new-ref", "expires_in": 3600}

    monkeypatch.setattr(op.supabase_oauth, "refresh", fake_refresh)
    p = KiboOAuthProvider()
    rt = RefreshToken(token="old-refresh", client_id="c1", scopes=["mcp"], expires_at=None)
    token = await p.exchange_refresh_token(_client(), rt, ["mcp"])
    assert token.access_token == "new-acc" and token.refresh_token == "new-ref"


# ── email → tenant auto-assignment ──────────────────────────────────


def test_resolve_tenants_rules(monkeypatch):
    from pipeline.mcp_server.tenant_map import KIBO_TENANT, NZYME_TENANT, resolve_tenants

    monkeypatch.setattr(settings, "mcp_tenant_firms", None)  # use baked-in defaults
    assert resolve_tenants("reyes@kiboventures.com") == [NZYME_TENANT]  # Nzyme list only
    assert resolve_tenants("nacho@kiboventures.com") == [KIBO_TENANT]  # Kibo list only
    assert set(resolve_tenants("niklas@kiboventures.com")) == {KIBO_TENANT, NZYME_TENANT}  # both
    assert set(resolve_tenants("juan@kiboventures.com")) == {KIBO_TENANT, NZYME_TENANT}  # both lists
    assert resolve_tenants("someone@nzalpha.com") == [NZYME_TENANT]  # domain
    assert resolve_tenants("juan@aallende.com") == [KIBO_TENANT]  # non-kibo domain, on Kibo list
    assert resolve_tenants("x@gmail.com") == []  # no match
    assert resolve_tenants("NACHO@KiboVentures.com") == [KIBO_TENANT]  # case-insensitive


@pytest.mark.asyncio
async def test_ensure_tenant_member_upserts():
    from pipeline.access import ensure_tenant_member

    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/rest/v1/tenant_members")
        assert "on_conflict=user_id,tenant_id" in str(req.url)
        assert req.headers.get("Prefer") == "resolution=ignore-duplicates"
        import json as _json

        seen["payload"] = _json.loads(req.content)
        return httpx.Response(201, json=[])

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await ensure_tenant_member(http, "uid-1", "tenant-9")
    await http.aclose()
    assert seen["payload"] == {"user_id": "uid-1", "tenant_id": "tenant-9", "role": "viewer"}


@pytest.mark.asyncio
async def test_callback_auto_assigns_tenants(monkeypatch):
    import pipeline.mcp_server.server as srv
    from pipeline.mcp_server.tenant_map import KIBO_TENANT, NZYME_TENANT

    session = {
        "client_id": "c1",
        "redirect_uri": "http://localhost:12629/oauth/callback",
        "redirect_uri_provided_explicitly": True,
        "client_state": "st",
        "client_code_challenge": "chal",
        "scopes": ["mcp"],
        "resource": None,
        "supabase_code_verifier": "verifier",
    }

    async def fake_state_get(id):
        return session

    async def fake_exchange(code, verifier):
        return {
            "access_token": "acc",
            "refresh_token": "ref",
            "expires_in": 3600,
            "user": {"id": "uid-7", "email": "niklas@kiboventures.com"},  # on BOTH lists
        }

    members: list[tuple[str, str]] = []

    async def fake_ensure_member(http, user_id, tenant_id, role="viewer"):
        members.append((user_id, tenant_id))

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(srv, "state_get", fake_state_get)
    monkeypatch.setattr(srv, "exchange_code", fake_exchange)
    monkeypatch.setattr(srv, "ensure_tenant_member", fake_ensure_member)
    monkeypatch.setattr(srv, "state_put", _noop)
    monkeypatch.setattr(srv, "state_delete", _noop)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/mcp/supabase-callback",
        "query_string": b"code=abc&session_id=sid",
        "headers": [],
    }
    resp = await srv._supabase_callback(Request(scope))

    assert resp.status_code == 302  # redirects back to the client with the code
    # niklas is on both lists → member of both tenants (additive)
    assert {t for _, t in members} == {KIBO_TENANT, NZYME_TENANT}
    assert all(uid == "uid-7" for uid, _ in members)
