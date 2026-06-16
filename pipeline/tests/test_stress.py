"""
Stress tests for all ingestion endpoints.
Exercises each endpoint with diverse payloads, edge cases, and volume.
Uses mocked edge function responses (no live Supabase needed).
"""
from __future__ import annotations

import string
import random

import pytest
from httpx import AsyncClient

# ── Helpers ──────────────────────────────────────────────────────────


def _random_text(length: int) -> str:
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
             "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
             "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform",
             "victor", "whiskey", "xray", "yankee", "zulu"]
    result = []
    while len(" ".join(result)) < length:
        result.append(random.choice(words))
    return " ".join(result)[:length]


def _random_label() -> str:
    return f"{''.join(random.choices(string.ascii_uppercase, k=3))}-{random.randint(100,999)}"


# ═══════════════════════════════════════════════════════════════════════
#  /ingest/structured
# ═══════════════════════════════════════════════════════════════════════


class TestStructuredStress:

    @pytest.mark.asyncio
    async def test_single_company(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"label": "Acme Corp", "type": "company"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["items_produced"] == 1
        assert body["source_type"] == "structured"

    @pytest.mark.asyncio
    async def test_single_person(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"label": "Jane Doe", "type": "person"}],
        })
        assert resp.status_code == 200
        assert resp.json()["results"][0]["status"] == "created"

    @pytest.mark.asyncio
    async def test_all_pointer_types(self, async_client: AsyncClient):
        types = [
            "company", "person", "sector", "geography", "regulation",
            "document", "timeseries", "event", "agent", "skill", "tool",
            "flow", "component", "architecture", "best_practice", "meta",
        ]
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"label": f"Entity-{t}", "type": t} for t in types],
        })
        assert resp.status_code == 200
        assert resp.json()["items_produced"] == len(types)

    @pytest.mark.asyncio
    async def test_rich_attributes(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{
                "label": "TechCo International",
                "type": "company",
                "canonical_key": "techco-intl",
                "metadata": {"sector": "SaaS", "hq": "New York", "founded": 2018},
                "occurred_at": "2025-06-01T00:00:00Z",
                "access_class": "confidential",
                "attributes": [
                    {"key": "Stage", "value": "Series C", "data_type": "string"},
                    {"key": "ARR", "value": 45000000, "data_type": "number"},
                    {"key": "Public", "value": False, "data_type": "boolean"},
                    {"key": "Tags", "value": ["AI", "B2B", "Enterprise"], "data_type": "array"},
                ],
            }],
        })
        assert resp.status_code == 200
        assert resp.json()["items_produced"] == 1

    @pytest.mark.asyncio
    async def test_batch_of_50_items(self, async_client: AsyncClient):
        """Max batch size for a single ingest-batch call."""
        items = [{"label": f"Company-{i}", "type": "company", "canonical_key": f"co-{i}"}
                 for i in range(50)]
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": items, "source": "crm-bulk-export",
        })
        assert resp.status_code == 200
        assert resp.json()["items_produced"] == 50

    @pytest.mark.asyncio
    async def test_mixed_types_batch(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [
                {"label": "Acme Corp", "type": "company", "canonical_key": "acme"},
                {"label": "John Smith", "type": "person", "attributes": [
                    {"key": "Role", "value": "CEO"},
                ]},
                {"label": "AI & Machine Learning", "type": "sector"},
                {"label": "North America", "type": "geography"},
                {"label": "GDPR Compliance", "type": "regulation"},
                {"label": "Board Meeting Q4", "type": "event", "occurred_at": "2025-12-15T09:00:00Z"},
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["items_produced"] == 6

    @pytest.mark.asyncio
    async def test_unicode_labels(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [
                {"label": "日本電信電話株式会社", "type": "company"},
                {"label": "São Paulo Ventures", "type": "company"},
                {"label": "Ünternehmen GmbH", "type": "company"},
                {"label": "Компания Альфа", "type": "company"},
                {"label": "شركة التقنية", "type": "company"},
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["items_produced"] == 5

    @pytest.mark.asyncio
    async def test_long_label(self, async_client: AsyncClient):
        long_label = "A" * 500
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"label": long_label, "type": "company"}],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_deeply_nested_metadata(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{
                "label": "Complex Entity",
                "type": "company",
                "metadata": {
                    "financials": {
                        "revenue": {"2023": 1000000, "2024": 2500000},
                        "burn_rate": 150000,
                    },
                    "team": [
                        {"name": "Alice", "role": "CEO"},
                        {"name": "Bob", "role": "CTO"},
                    ],
                    "flags": {"active": True, "verified": False},
                },
            }],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_metadata_and_attributes(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{
                "label": "Minimal Entity",
                "type": "company",
                "metadata": {},
                "attributes": [],
            }],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_type_rejected(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"label": "Bad", "type": "not_a_real_type"}],
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_items_rejected(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [],
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_label_rejected(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"type": "company"}],
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_access_class_propagation(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [
                {"label": "Public Co", "type": "company"},
                {"label": "Secret Co", "type": "company", "access_class": "restricted"},
            ],
            "access_class": "confidential",
        })
        assert resp.status_code == 200
        assert resp.json()["items_produced"] == 2


# ═══════════════════════════════════════════════════════════════════════
#  /ingest/document/json
# ═══════════════════════════════════════════════════════════════════════


class TestDocumentJsonStress:

    @pytest.mark.asyncio
    async def test_short_document(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Quick Note",
            "content": "Buy milk.",
        })
        assert resp.status_code == 200
        assert resp.json()["source_type"] == "document"

    @pytest.mark.asyncio
    async def test_long_document(self, async_client: AsyncClient):
        content = _random_text(100_000)
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Large Research Report",
            "content": content,
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_markdown_document(self, async_client: AsyncClient):
        content = """# Investment Memo: Acme Corp

## Executive Summary

Acme Corp is a Series B SaaS company targeting the enterprise market.
Revenue grew 3x YoY to $12M ARR.

## Market Analysis

The TAM for enterprise workflow automation is estimated at $45B.

### Competitive Landscape

| Competitor | ARR | Stage |
|-----------|-----|-------|
| BigCo | $100M | Public |
| StartupX | $5M | Series A |

## Financial Projections

- 2025: $25M ARR
- 2026: $55M ARR
- 2027: $100M ARR

## Risks

1. Customer concentration (top 3 = 40% revenue)
2. Regulatory uncertainty in EU markets
3. Key-person risk on engineering team
"""
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Investment Memo: Acme Corp",
            "content": content,
            "occurred_at": "2025-03-15T00:00:00Z",
            "metadata": {"type": "memo", "author": "analyst@fund.com"},
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_document_with_link(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Due Diligence Report",
            "content": "Detailed analysis of the target company...\n" * 50,
            "link": {
                "target_canonical_key": "acme-corp",
                "relationship_type": "describes",
                "why": "DD report for Acme Corp acquisition",
            },
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_document_with_chunk_size(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Chunked Doc",
            "content": _random_text(10_000),
            "chunk_size": 500,
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_document_unicode_content(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "多言語ドキュメント",
            "content": "これは日本語のテストです。\n\nCeci est un test en français.\n\nDies ist ein Test auf Deutsch.",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_title_derived_from_content(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "content": "Auto-derived title from first line\n\nThe rest of the document body.",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_content_rejected(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Empty",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_content_rejected(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Blank", "content": "",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_content_with_special_characters(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Special Chars",
            "content": 'Contains "quotes", <tags>, &ampersands, \ttabs, and null bytes: \x00',
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_document_with_access_class(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/document/json", json={
            "title": "Confidential Memo",
            "content": "Sensitive deal terms...",
            "access_class": "confidential",
        })
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
#  /ingest/conversation
# ═══════════════════════════════════════════════════════════════════════


class TestConversationStress:

    @pytest.mark.asyncio
    async def test_simple_chat(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/conversation", json={
            "content": "User: What's the status of the Acme deal?\nAgent: The deal is in due diligence.",
        })
        assert resp.status_code == 200
        assert resp.json()["source_type"] == "conversation"

    @pytest.mark.asyncio
    async def test_meeting_transcript(self, async_client: AsyncClient):
        transcript = """Weekly Investment Committee — 2025-06-10

Attendees: Alice (Partner), Bob (Analyst), Charlie (Associate)

Alice: Let's start with the pipeline review. Bob, where are we on TechCo?

Bob: TechCo is progressing well. We completed the management meetings last week.
Key findings:
- ARR is $12M, growing 150% YoY
- Net revenue retention is 135%
- Customer concentration is improving — top 5 went from 60% to 45%

Charlie: I ran the comparable analysis. At 15x forward ARR, the implied valuation
is $180M. That's in line with recent Series C rounds in the space.

Alice: Good. What about risks?

Bob: Main concerns:
1. The CTO is leaving in Q3 — they have a succession plan but it's untested
2. EU expansion requires GDPR compliance work that could take 6 months
3. Two large enterprise contracts are up for renewal in Q4

Alice: Let's schedule a follow-up with the CEO specifically on the CTO transition.
Charlie, prepare a term sheet draft at $180M pre-money.

Charlie: Will do. Target close date?

Alice: End of July. Let's move to the next item.
"""
        resp = await async_client.post("/api/v1/ingest/conversation", json={
            "content": transcript,
            "title": "IC Meeting — 2025-06-10",
            "source": "zoom",
            "occurred_at": "2025-06-10T14:00:00Z",
            "participants": ["Alice", "Bob", "Charlie"],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_conversation(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/conversation", json={
            "content": (
                "User: Find me all Series B companies in the healthcare sector.\n"
                "Agent: I found 12 companies matching your criteria. Here are the top 5:\n"
                "1. HealthTech Inc — $8M ARR, digital therapeutics\n"
                "2. MedFlow — $5M ARR, clinical workflow automation\n"
                "3. CareAI — $3M ARR, diagnostic AI\n"
                "4. PharmaLink — $6M ARR, supply chain\n"
                "5. BioMetrics — $4M ARR, wearable diagnostics\n"
                "User: Tell me more about HealthTech Inc.\n"
                "Agent: HealthTech Inc was founded in 2021..."
            ),
            "source": "agent-chat",
            "participants": ["analyst@fund.com", "kibo-agent"],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_slack_thread(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/conversation", json={
            "content": (
                "[10:32 AM] alice: Just got off the call with Acme's CFO\n"
                "[10:32 AM] alice: They're open to a bridge round at flat terms\n"
                "[10:33 AM] bob: Interesting. How much are they looking for?\n"
                "[10:34 AM] alice: $5M to extend runway through Q1 2026\n"
                "[10:35 AM] bob: Let me check our reserves. @charlie can you update the model?\n"
                "[10:36 AM] charlie: On it. Will have numbers by EOD.\n"
            ),
            "source": "slack",
            "occurred_at": "2025-06-15T10:32:00Z",
            "participants": ["alice", "bob", "charlie"],
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_long_conversation(self, async_client: AsyncClient):
        """Simulate a long multi-turn conversation."""
        turns = []
        for i in range(100):
            speaker = "User" if i % 2 == 0 else "Agent"
            turns.append(f"{speaker}: {_random_text(200)}")
        content = "\n".join(turns)

        resp = await async_client.post("/api/v1/ingest/conversation", json={
            "content": content,
            "title": "Extended Research Session",
            "source": "agent-chat",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_participants(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/conversation", json={
            "content": "Some conversation without participant info.",
        })
        assert resp.status_code == 200
        # metadata should be None or missing participants key
        body = resp.json()
        assert body["items_produced"] == 1

    @pytest.mark.asyncio
    async def test_conversation_with_link(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/conversation", json={
            "content": "Discussion about the Acme Corp investment thesis.",
            "title": "Acme Discussion",
            "link": {"target_canonical_key": "acme-corp", "relationship_type": "discusses"},
        })
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
#  /ingest/web
# ═══════════════════════════════════════════════════════════════════════


class TestWebStress:

    @pytest.mark.asyncio
    async def test_simple_article(self, async_client: AsyncClient, monkeypatch):
        _mock_fetch(monkeypatch, """
        <html>
          <head><title>Breaking: AI Startup Raises $50M</title></head>
          <body>
            <article>
              <h1>AI Startup Raises $50M Series B</h1>
              <p>TechCo announced today that it has raised $50M in Series B funding
              led by Venture Capital Fund.</p>
              <p>The round values the company at $200M post-money.</p>
            </article>
          </body>
        </html>
        """)

        resp = await async_client.post("/api/v1/ingest/web", json={
            "url": "https://news.example.com/article/123",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_type"] == "web"
        assert body["items_produced"] == 1

    @pytest.mark.asyncio
    async def test_complex_page_with_nav_footer(self, async_client: AsyncClient, monkeypatch):
        _mock_fetch(monkeypatch, """
        <html>
          <head><title>Company Blog</title></head>
          <body>
            <nav><a href="/">Home</a><a href="/about">About</a><a href="/blog">Blog</a></nav>
            <header><h1>Company Blog</h1><p>Latest updates from our team</p></header>
            <main>
              <h2>Product Update: Q2 2025</h2>
              <p>We're excited to announce several new features this quarter.</p>
              <p>Feature 1: Advanced analytics dashboard with real-time metrics.</p>
              <p>Feature 2: API v2 with improved rate limiting and webhooks.</p>
              <p>Feature 3: Multi-language support for 12 new languages.</p>
            </main>
            <footer>
              <p>Copyright 2025 Company Inc.</p>
              <a href="/privacy">Privacy</a>
              <a href="/terms">Terms</a>
            </footer>
          </body>
        </html>
        """)

        resp = await async_client.post("/api/v1/ingest/web", json={
            "url": "https://blog.example.com/q2-update",
            "metadata": {"source_type": "blog"},
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_page_with_scripts_and_styles(self, async_client: AsyncClient, monkeypatch):
        _mock_fetch(monkeypatch, """
        <html>
          <head>
            <title>JS-Heavy Page</title>
            <style>body { font-family: sans-serif; } .hidden { display: none; }</style>
          </head>
          <body>
            <script>var analytics = { track: function() {} }; analytics.track('pageview');</script>
            <script src="https://cdn.example.com/bundle.js"></script>
            <div id="content">
              <h1>Actual Content</h1>
              <p>This is the real text that should be extracted.</p>
            </div>
            <script>document.getElementById('content').addEventListener('click', function() {});</script>
          </body>
        </html>
        """)

        resp = await async_client.post("/api/v1/ingest/web", json={
            "url": "https://app.example.com/page",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_title_override(self, async_client: AsyncClient, monkeypatch):
        _mock_fetch(monkeypatch, """
        <html><head><title>Bad SEO Title | Site Name | Click Here</title></head>
        <body><p>Good content about investment trends.</p></body></html>
        """)

        resp = await async_client.post("/api/v1/ingest/web", json={
            "url": "https://example.com/article",
            "title": "Investment Trends 2025",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_web_with_link(self, async_client: AsyncClient, monkeypatch):
        _mock_fetch(monkeypatch, """
        <html><head><title>Acme Corp Profile</title></head>
        <body><article><p>Acme Corp is a SaaS company...</p></article></body></html>
        """)

        resp = await async_client.post("/api/v1/ingest/web", json={
            "url": "https://crunchbase.com/acme-corp",
            "link": {"target_canonical_key": "acme-corp", "relationship_type": "describes"},
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_large_page(self, async_client: AsyncClient, monkeypatch):
        paragraphs = "\n".join(f"<p>{_random_text(500)}</p>" for _ in range(200))
        _mock_fetch(monkeypatch, f"""
        <html><head><title>Large Document</title></head>
        <body><article>{paragraphs}</article></body></html>
        """)

        resp = await async_client.post("/api/v1/ingest/web", json={
            "url": "https://example.com/long-article",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_minimal_html(self, async_client: AsyncClient, monkeypatch):
        _mock_fetch(monkeypatch, "<p>Just a paragraph, no html/head/body tags.</p>")

        resp = await async_client.post("/api/v1/ingest/web", json={
            "url": "https://example.com/minimal",
        })
        # Might fail because no body/article — depends on BS4 parsing
        # At minimum should not crash
        assert resp.status_code in (200, 422)


# ═══════════════════════════════════════════════════════════════════════
#  /ingest/document (multipart file upload)
# ═══════════════════════════════════════════════════════════════════════


class TestDocumentUploadStress:

    @pytest.mark.asyncio
    async def test_txt_upload(self, async_client: AsyncClient):
        content = "This is a plain text file.\n\nIt has multiple paragraphs.\n\nThird paragraph."
        resp = await async_client.post("/api/v1/ingest/document", files={
            "file": ("notes.txt", content.encode(), "text/plain"),
        })
        assert resp.status_code == 200
        assert resp.json()["items_produced"] == 1

    @pytest.mark.asyncio
    async def test_markdown_upload(self, async_client: AsyncClient):
        md = "# Project Plan\n\n## Phase 1\n\nBuild the ingestion pipeline.\n\n## Phase 2\n\nAdd LLM extraction."
        resp = await async_client.post("/api/v1/ingest/document", files={
            "file": ("plan.md", md.encode(), "text/markdown"),
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_with_form_fields(self, async_client: AsyncClient):
        content = "Document content for testing."
        resp = await async_client.post("/api/v1/ingest/document",
            files={"file": ("report.txt", content.encode(), "text/plain")},
            data={
                "occurred_at": "2025-01-15T00:00:00Z",
                "access_class": "confidential",
                "link_target_canonical_key": "acme-corp",
                "link_relationship_type": "describes",
            },
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_large_txt_upload(self, async_client: AsyncClient):
        content = _random_text(50_000)
        resp = await async_client.post("/api/v1/ingest/document", files={
            "file": ("big_report.txt", content.encode(), "text/plain"),
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_json_body_fallback(self, async_client: AsyncClient):
        """When no file is uploaded, form fields are used as JSON-like input."""
        resp = await async_client.post("/api/v1/ingest/document", data={
            "title": "Form-based Doc",
            "content": "Content submitted via form fields, not file upload.",
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_oversized_upload_rejected(self, async_client: AsyncClient, monkeypatch):
        from pipeline.config import settings

        monkeypatch.setattr(settings, "max_upload_bytes", 100)
        resp = await async_client.post("/api/v1/ingest/document", files={
            "file": ("big.txt", b"x" * 500, "text/plain"),
        })
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
#  Cross-cutting: response timing & structure
# ═══════════════════════════════════════════════════════════════════════


class TestResponseStructure:

    @pytest.mark.asyncio
    async def test_response_has_duration(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"label": "X", "type": "company"}],
        })
        body = resp.json()
        assert "duration_ms" in body
        assert isinstance(body["duration_ms"], int)
        assert body["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_response_envelope_shape(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"label": "X", "type": "company"}],
        })
        body = resp.json()
        assert set(body.keys()) == {"source_type", "items_produced", "results", "errors", "duration_ms"}
        assert isinstance(body["results"], list)
        assert isinstance(body["errors"], list)

    @pytest.mark.asyncio
    async def test_result_has_pointer_id(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/ingest/structured", json={
            "items": [{"label": "X", "type": "company"}],
        })
        result = resp.json()["results"][0]
        assert "pointer_id" in result
        assert "status" in result
        assert "index" in result

    @pytest.mark.asyncio
    async def test_health_endpoint(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════


def _mock_fetch(monkeypatch, html: str):
    """Patch the web adapter's _fetch to return canned HTML."""
    import pipeline.adapters.web as web_mod

    async def fake_fetch(url, http):
        return html

    monkeypatch.setattr(web_mod, "_fetch", fake_fetch)
