"""Opt-in network diagnostics for the Gmail OAuth token endpoint.

Localize *where* connectivity to oauth2.googleapis.com breaks, layer by layer.
Skipped unless GMAIL_LIVE_TEST=1, so the normal mocked suite stays offline.

    GMAIL_LIVE_TEST=1 pytest tests/test_adapters/test_gmail_connectivity.py -v -s
"""
import os
import socket
import time

import pytest
import requests

TOKEN_HOST = "oauth2.googleapis.com"
TOKEN_PORT = 443
TOKEN_URL = f"https://{TOKEN_HOST}/token"

pytestmark = pytest.mark.skipif(
    os.getenv("GMAIL_LIVE_TEST") != "1",
    reason="set GMAIL_LIVE_TEST=1 to run network diagnostics",
)


@pytest.fixture(autouse=True)
def _stub_dns():
    """Override conftest's autouse DNS-stubbing fixture so these tests resolve
    real hostnames instead of the 93.184.216.34 SSRF-guard stand-in."""
    yield


def test_step1_dns_resolves():
    """Step 1 — DNS: the host resolves to at least one address."""
    infos = socket.getaddrinfo(TOKEN_HOST, TOKEN_PORT, type=socket.SOCK_STREAM)
    addrs = [("v6" if f == socket.AF_INET6 else "v4", sa[0]) for f, *_, sa in infos]
    print(f"\n[step1] resolved {len(addrs)} address(es): {addrs}")
    assert addrs, "DNS returned no addresses for oauth2.googleapis.com"


def test_step2_raw_tcp_connect():
    """Step 2 — raw TCP: at least one resolved IP accepts a socket in 5s.
    Per-IP results distinguish partial blackholing (some IPs hang) from a full
    block (all fail → likely a per-application firewall/security agent)."""
    infos = socket.getaddrinfo(TOKEN_HOST, TOKEN_PORT, type=socket.SOCK_STREAM)
    any_ok = False
    print()
    for fam, *_, sa in infos:
        ip = sa[0]
        s = socket.socket(fam, socket.SOCK_STREAM)
        s.settimeout(5)
        t = time.time()
        try:
            s.connect((ip, TOKEN_PORT))
            any_ok = True
            print(f"[step2] OK   {ip}  {round(time.time() - t, 2)}s")
        except Exception as e:
            print(f"[step2] FAIL {ip}  {type(e).__name__}  {round(time.time() - t, 2)}s")
        finally:
            s.close()
    assert any_ok, "raw TCP to every resolved IP failed (per-app firewall/agent?)"


def test_step3_requests_post_token():
    """Step 3 — HTTP: requests can POST to the token endpoint (8s timeout, x5).
    Repeated to surface intermittency. A 4xx is success here — we connected and
    Google merely rejected the empty body."""
    ok = 0
    print()
    for i in range(5):
        t = time.time()
        try:
            r = requests.post(TOKEN_URL, timeout=8)
            ok += 1
            print(f"[step3] {i} OK {r.status_code} {round(time.time() - t, 2)}s")
        except Exception as e:
            print(f"[step3] {i} {type(e).__name__} {round(time.time() - t, 2)}s")
    assert ok > 0, "every requests.post to the token endpoint failed/timed out"
