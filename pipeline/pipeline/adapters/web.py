from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from pipeline.config import settings
from pipeline.errors import AdapterError
from pipeline.models import NormalizedItem, WebRequest


class WebAdapter:
    async def process(self, request: WebRequest, http: httpx.AsyncClient) -> list[NormalizedItem]:
        _validate_url(request.url)
        html = await _fetch(request.url, http)
        title, content = _extract(html)

        title = request.title or title
        if not content.strip():
            raise AdapterError(f"No extractable text content from {request.url}")

        if len(content) > settings.max_content_length:
            content = content[: settings.max_content_length]

        metadata = dict(request.metadata) if request.metadata else {}
        metadata["source_url"] = request.url

        return [NormalizedItem(
            kind="document",
            label=title,
            type="document",
            content=content,
            metadata=metadata,
            occurred_at=request.occurred_at,
            access_class=request.access_class,
            link=request.link,
            source="web-scrape",
        )]


def _validate_url(url: str) -> None:
    """Reject non-http(s) schemes and hosts that resolve to private/internal
    IPs, to prevent SSRF via user-supplied URLs."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise AdapterError(f"Unsupported URL scheme: {parts.scheme or '(none)'}")
    host = parts.hostname
    if not host:
        raise AdapterError(f"URL has no host: {url}")

    if not settings.block_private_urls:
        return

    try:
        infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise AdapterError(f"Cannot resolve host {host!r}: {exc}")

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise AdapterError(f"Refusing to fetch internal address {ip} for host {host!r}")


async def _fetch(url: str, http: httpx.AsyncClient) -> str:
    try:
        resp = await http.get(
            url,
            follow_redirects=True,
            timeout=settings.web_scrape_timeout,
            headers={"User-Agent": settings.web_scrape_user_agent},
        )
        resp.raise_for_status()
    except httpx.TimeoutException:
        raise AdapterError(f"Timeout fetching {url}")
    except httpx.HTTPStatusError as exc:
        raise AdapterError(f"HTTP {exc.response.status_code} fetching {url}")
    except httpx.RequestError as exc:
        raise AdapterError(f"Failed to fetch {url}: {exc}")

    # Redirects may have landed on an internal host; re-validate the final URL.
    if str(resp.url) != url:
        _validate_url(str(resp.url))

    ct = resp.headers.get("content-type", "")
    if "html" not in ct and "text" not in ct:
        raise AdapterError(f"Expected HTML, got content-type: {ct}")

    return resp.text


def _extract(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Title
    title_tag = soup.find("title")
    h1_tag = soup.find("h1")
    title = "Untitled"
    if title_tag and title_tag.string:
        title = title_tag.string.strip()[:120]
    elif h1_tag:
        title = h1_tag.get_text(strip=True)[:120]

    # Content: prefer <article> or <main>, fall back to <body>
    content_root = soup.find("article") or soup.find("main") or soup.find("body")
    if content_root is None:
        return title, ""

    text = content_root.get_text(separator="\n")
    # Clean up whitespace: collapse multiple blank lines
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(lines)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")

    return title, cleaned.strip()
