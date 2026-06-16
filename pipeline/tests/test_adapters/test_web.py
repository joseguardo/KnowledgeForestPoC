import pytest
import httpx

from pipeline.adapters.web import WebAdapter, _extract, _validate_url
from pipeline.errors import AdapterError
from pipeline.models import WebRequest


def test_extract_simple_html():
    html = """
    <html>
      <head><title>Test Page</title></head>
      <body>
        <nav>Navigation stuff</nav>
        <article>
          <h1>Article Title</h1>
          <p>First paragraph.</p>
          <p>Second paragraph.</p>
        </article>
        <footer>Footer stuff</footer>
      </body>
    </html>
    """
    title, content = _extract(html)
    assert title == "Test Page"
    assert "First paragraph." in content
    assert "Second paragraph." in content
    assert "Navigation stuff" not in content
    assert "Footer stuff" not in content


def test_extract_no_article_falls_back_to_body():
    html = "<html><body><p>Hello world</p></body></html>"
    title, content = _extract(html)
    assert "Hello world" in content
    assert title == "Untitled"


def test_extract_h1_title_fallback():
    html = "<html><body><h1>Page Title</h1><p>Content</p></body></html>"
    title, content = _extract(html)
    assert title == "Page Title"


def test_extract_strips_scripts():
    html = """
    <html><body>
      <script>var x = 1;</script>
      <p>Visible text</p>
      <style>.hidden { display: none; }</style>
    </body></html>
    """
    title, content = _extract(html)
    assert "var x" not in content
    assert "hidden" not in content
    assert "Visible text" in content


@pytest.mark.asyncio
async def test_web_adapter_success():
    html = "<html><head><title>Example</title></head><body><p>Page content here.</p></body></html>"

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    http = httpx.AsyncClient(transport=transport)

    adapter = WebAdapter()
    req = WebRequest(url="https://example.com")
    items = await adapter.process(req, http=http)

    assert len(items) == 1
    assert items[0].kind == "document"
    assert items[0].label == "Example"
    assert "Page content here." in items[0].content
    assert items[0].metadata["source_url"] == "https://example.com"
    assert items[0].source == "web-scrape"

    await http.aclose()


# ── SSRF guard (_validate_url) ──────────────────────────────────────
# The autouse _stub_dns fixture resolves IP literals to themselves, so
# loopback/metadata/private addresses are blocked without real DNS.


def test_validate_url_rejects_non_http_scheme():
    with pytest.raises(AdapterError, match="scheme"):
        _validate_url("file:///etc/passwd")
    with pytest.raises(AdapterError, match="scheme"):
        _validate_url("ftp://example.com/x")


def test_validate_url_rejects_loopback():
    with pytest.raises(AdapterError, match="internal"):
        _validate_url("http://127.0.0.1:8000/")


def test_validate_url_rejects_cloud_metadata():
    with pytest.raises(AdapterError, match="internal"):
        _validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_rejects_private_range():
    with pytest.raises(AdapterError, match="internal"):
        _validate_url("http://10.0.0.5/admin")


def test_validate_url_allows_public_host():
    # Stubbed DNS resolves hostnames to a public IP — must not raise.
    _validate_url("https://example.com/article")


@pytest.mark.asyncio
async def test_web_endpoint_blocks_internal_url(async_client):
    resp = await async_client.post("/api/v1/ingest/web", json={
        "url": "http://169.254.169.254/latest/meta-data/",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_web_adapter_non_html_raises():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"binary data", headers={"content-type": "application/pdf"}
        )
    )
    http = httpx.AsyncClient(transport=transport)

    adapter = WebAdapter()
    req = WebRequest(url="https://example.com/file.pdf")
    with pytest.raises(AdapterError, match="Expected HTML"):
        await adapter.process(req, http=http)

    await http.aclose()
