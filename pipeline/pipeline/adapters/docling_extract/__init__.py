"""Docling extraction adapter — the slim public entrypoint for the vendored pipeline.

This package vendors PlatformRemote's Docling extraction ``logic/`` tree (converter,
guardrails, chunking, facts) plus a warm ``DocumentConverter`` singleton
(``converter.get_converter()``). The single public function here, :func:`extract`,
is the one ``fetch_document`` calls: it runs the full per-document pipeline
(convert → guardrails → chunk → facts) and returns a plain JSON-ready ``dict``.

It mirrors the platform orchestrator's ``_process_one`` but is a single-file,
single-document version — no ProgressEmitter, no agent_tasks, no download bundle.

**Transient by design.** :func:`extract` returns in-memory data only. Nothing here
is persisted to a database, written to disk, or otherwise stored — the caller owns
whatever it does with the returned dict.

Heavy imports (``docling_core``, ``pandas`` via the vendored ``logic`` modules, and
the docling converter) are kept *inside* :func:`extract` so merely importing this
package stays cheap and does not pull in those dependencies.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def extract(name: str, data: bytes, *, minimum_grade: str | None = None) -> dict:
    """Convert one document's bytes and return its extraction result as a dict.

    Runs the vendored pipeline end-to-end on a single file, isolating any failure
    to a returned ``error`` dict (one bad document never raises to the caller).

    Args:
        name: Original filename (drives docling's format detection by extension).
        data: Raw file bytes (PDF, xlsx, docx, … whatever docling accepts).
        minimum_grade: Override the guardrail minimum grade; defaults to
            ``settings.docling_min_grade`` (or ``"GOOD"``). Upper-cased.

    Returns:
        On success, a dict with these keys (the data contract consumed by the
        caller — all values are JSON-ready):
          - ``name`` (str): the input ``name``.
          - ``markdown`` (str): full document markdown (may be large; cap downstream).
          - ``grade`` (str): conversion quality grade, e.g. ``GOOD``/``OK``/``POOR``.
          - ``pages`` (int | None): page count, when docling reports one.
          - ``facts`` (list[dict]): financial facts via ``facts_to_records()`` —
            plain dicts (NOT Pydantic), field-for-field matching the Pydantic
            ``FinancialFact`` model.
          - ``fact_count`` (int): ``len(facts)``.
          - ``guardrails`` (dict): the ``GuardrailReport``-shaped dict from
            ``guardrails.assess()``.
          - ``needs_review`` (bool): convenience copy of ``guardrails["needs_review"]``.
          - ``chunk_summary`` (dict): ``ChunkSummary``-shaped dict from
            ``chunking.chunk_summary()`` (keys: ``total``/``table``/``narrative``/``pages``).
          - ``warning`` (str | None): ``None`` on full success. When the best-effort
            steps (guardrails / chunking / facts) raise, the successfully-converted
            markdown is STILL returned, but ``warning`` carries the failure string and
            the degraded fields take their empty forms: ``facts=[]``, ``fact_count=0``,
            ``guardrails={}``, ``needs_review=False``, ``chunk_summary={}``.

        On empty input or a CONVERSION failure (nothing usable to return), a dict with
        just ``name`` and an ``error`` (str) key (no other keys present).
    """
    if not data:
        return {"error": "empty file (0 bytes)", "name": name}

    # Lazy imports — keep docling_core/pandas/docling out of package import.
    from pipeline.config import settings

    from .converter import get_converter
    from .logic.services import chunking, facts, guardrails
    from .logic.services.docling_converter import convert_bytes

    min_grade = (minimum_grade or settings.docling_min_grade or "GOOD").upper()

    # --- Tier 1: ESSENTIAL — conversion. If this fails, there is nothing to return.
    try:
        converter = get_converter()  # warm singleton — instant after boot
        converted = await asyncio.to_thread(
            convert_bytes, converter, name, data, max_pages=settings.docling_max_pages
        )
    except Exception as e:  # noqa: BLE001 — one bad document must not raise to the caller
        log.warning("docling conversion failed for %s: %s", name, e)
        return {"name": name, "error": str(e)}

    if converted is None:
        log.warning("docling conversion returned no document for %s", name)
        return {"name": name, "error": "conversion produced no document"}

    # --- Tier 2: BEST-EFFORT — guardrails / chunking / facts. A failure here must NOT
    # discard the successfully-converted markdown; we return markdown-only with a warning.
    try:
        report = guardrails.assess(converted, minimum_grade=min_grade)
        chunks = chunking.logical_chunks(converted.doc)
        summary = chunking.chunk_summary(chunks)
        fact_objs = facts.extract_facts(converted.doc)
        records = facts.facts_to_records(fact_objs)

        return {
            "name": name,
            "markdown": converted.markdown,
            "grade": converted.grade,
            "pages": converted.pages,
            "facts": records,
            "fact_count": len(records),
            "guardrails": report,
            "needs_review": bool(report.get("needs_review")),
            "chunk_summary": summary,
            "warning": None,
        }
    except Exception as e:  # noqa: BLE001 — preserve markdown when best-effort steps fail
        warning = f"facts/guardrails extraction failed: {e}; returning markdown only"
        log.warning("docling best-effort steps failed for %s: %s", name, e)
        return {
            "name": name,
            "markdown": converted.markdown,
            "grade": converted.grade,
            "pages": converted.pages,
            "facts": [],
            "fact_count": 0,
            "guardrails": {},
            "needs_review": False,
            "chunk_summary": {},
            "warning": warning,
        }
