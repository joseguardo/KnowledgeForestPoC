"""Opt-in live check of the Gmail connector against the real Gmail API.

Skipped unless GMAIL_LIVE_TEST=1 and GMAIL_FIRMS is set, so it never runs during
the normal mocked suite. Run it explicitly:

    GMAIL_LIVE_TEST=1 pytest tests/test_adapters/test_gmail_live.py -v -s
"""
import os

import httpx
import pytest

from pipeline.adapters.gmail import GmailAdapter, load_firms
from pipeline.config import settings

pytestmark = pytest.mark.skipif(
    not (os.getenv("GMAIL_LIVE_TEST") == "1" and settings.gmail_firms),
    reason="set GMAIL_LIVE_TEST=1 and GMAIL_FIRMS (per-firm config)",
)


@pytest.fixture(autouse=True)
def _stub_dns():
    """Override conftest's autouse DNS-stubbing fixture so this test reaches the
    real Gmail/OAuth endpoints instead of the 93.184.216.34 SSRF-guard stand-in."""
    yield


@pytest.mark.asyncio
async def test_gmail_live_pull():
    """Mint a delegated token and pull a few recent threads from the real API."""
    firm = load_firms()[0]
    mailbox = firm.mailboxes[0]
    async with httpx.AsyncClient() as http:
        threads = await GmailAdapter().fetch_threads(
            firm, mailbox, http, query="newer_than:30d", max_results=3
        )

    assert isinstance(threads, list)  # no exception == DWD auth + API access work
    print(f"\nGmail OK — pulled {len(threads)} thread(s) for {mailbox}")
    for t in threads:
        assert t.tenant_id == firm.tenant_id
        assert t.metadata.get("gmail_thread_id")
        print(f"  - {t.event_label}")
