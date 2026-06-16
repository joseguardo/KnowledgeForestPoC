import pytest
import httpx

from pipeline.client import EdgeFunctionClient
from pipeline.errors import EdgeFunctionError


def _make_client(transport: httpx.MockTransport) -> tuple[httpx.AsyncClient, EdgeFunctionClient]:
    http = httpx.AsyncClient(transport=transport)
    client = EdgeFunctionClient(
        http=http,
        supabase_url="https://test.supabase.co",
        service_role_key="test-key",
        max_retries=2,
        retry_backoff_base=0.01,  # fast retries for tests
    )
    return http, client


@pytest.mark.asyncio
async def test_insert_pointer_success():
    response_data = {"status": "created", "pointer_id": "abc-123"}
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=response_data)
    )
    http, client = _make_client(transport)
    result = await client.insert_pointer(label="Test", type="company")
    assert result["status"] == "created"
    await http.aclose()


@pytest.mark.asyncio
async def test_ingest_document_success():
    response_data = {"status": "created", "pointer_id": "doc-1", "chunks_total": 2}
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=response_data)
    )
    http, client = _make_client(transport)
    result = await client.ingest_document(title="Test", content="Hello world")
    assert result["pointer_id"] == "doc-1"
    await http.aclose()


@pytest.mark.asyncio
async def test_4xx_not_retried():
    call_count = 0

    def handler(req):
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, json={"error": "bad request"})

    transport = httpx.MockTransport(handler)
    http, client = _make_client(transport)

    with pytest.raises(EdgeFunctionError) as exc_info:
        await client.insert_pointer(label="X", type="company")

    assert exc_info.value.status_code == 400
    assert call_count == 1  # no retry on 4xx
    await http.aclose()


@pytest.mark.asyncio
async def test_5xx_retried():
    call_count = 0

    def handler(req):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return httpx.Response(500, json={"error": "server error"})
        return httpx.Response(200, json={"status": "created", "pointer_id": "p-1"})

    transport = httpx.MockTransport(handler)
    http, client = _make_client(transport)

    result = await client.insert_pointer(label="X", type="company")
    assert result["status"] == "created"
    assert call_count == 2
    await http.aclose()


@pytest.mark.asyncio
async def test_retries_exhausted():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(500, json={"error": "down"})
    )
    http, client = _make_client(transport)

    with pytest.raises(EdgeFunctionError) as exc_info:
        await client.insert_pointer(label="X", type="company")

    assert exc_info.value.status_code == 500
    await http.aclose()


@pytest.mark.asyncio
async def test_network_error_retried_then_surfaced():
    """Non-timeout transport errors are retried, then surfaced as a 502-mapped
    EdgeFunctionError instead of escaping uncaught."""
    call_count = 0

    def handler(req):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    http, client = _make_client(transport)  # max_retries=2

    with pytest.raises(EdgeFunctionError) as exc_info:
        await client.insert_pointer(label="X", type="company")

    assert exc_info.value.status_code == 502
    assert call_count == 2  # retried, not raised on first failure
    await http.aclose()


@pytest.mark.asyncio
async def test_network_error_then_success():
    call_count = 0

    def handler(req):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"status": "created", "pointer_id": "p-1"})

    transport = httpx.MockTransport(handler)
    http, client = _make_client(transport)

    result = await client.insert_pointer(label="X", type="company")
    assert result["status"] == "created"
    assert call_count == 2
    await http.aclose()


@pytest.mark.asyncio
async def test_auth_header_set():
    def handler(req: httpx.Request):
        assert req.headers["authorization"] == "Bearer test-key"
        assert req.headers["content-type"] == "application/json"
        return httpx.Response(200, json={"status": "created", "pointer_id": "p-1"})

    transport = httpx.MockTransport(handler)
    http, client = _make_client(transport)
    await client.insert_pointer(label="X", type="company")
    await http.aclose()
