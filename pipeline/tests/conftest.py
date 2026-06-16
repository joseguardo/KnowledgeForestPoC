from __future__ import annotations

import ipaddress
import os
import socket
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

# Set required env vars before importing app
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")

from pipeline.client import EdgeFunctionClient  # noqa: E402
from pipeline.main import app  # noqa: E402


def _make_mock_client() -> EdgeFunctionClient:
    mock = AsyncMock(spec=EdgeFunctionClient)
    mock.insert_pointer.return_value = {
        "status": "created",
        "pointer_id": "aaaa-bbbb-cccc-dddd",
    }
    mock.ingest_document.return_value = {
        "status": "created",
        "pointer_id": "dddd-eeee-ffff-0000",
        "canonical_key": "doc:abc123",
        "chunks_total": 3,
        "chunks_inserted": 3,
    }
    mock.ingest_batch.return_value = {
        "summary": {"total": 2, "created": 2, "merged": 0, "pending_review": 0, "errors": 0},
        "results": [
            {"index": 0, "status": "created", "pointer_id": "1111-2222-3333-4444"},
            {"index": 1, "status": "created", "pointer_id": "5555-6666-7777-8888"},
        ],
    }
    return mock


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch) -> None:
    """Keep the web adapter's SSRF guard offline and deterministic: resolve IP
    literals to themselves (so localhost/metadata addresses are still blocked)
    and any hostname to a public stand-in (so domain-based tests pass without
    real DNS)."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            ip = str(ipaddress.ip_address(host))
        except ValueError:
            ip = "93.184.216.34"  # public stand-in for hostnames
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture
def mock_client() -> EdgeFunctionClient:
    return _make_mock_client()


@pytest.fixture
async def async_client() -> AsyncClient:
    app.state.client = _make_mock_client()
    app.state.http = AsyncMock()  # placeholder; web tests monkeypatch _fetch

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
