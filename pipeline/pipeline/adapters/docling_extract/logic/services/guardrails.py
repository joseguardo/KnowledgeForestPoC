# Vendored verbatim from PlatformRemote .../pdf_extraction/logic/services/guardrails.py — do not edit here; keep in sync with source.
# Source: backend/app/agents/discovery/pdf_extraction/logic/services/guardrails.py
"""Thin wrapper that runs the deterministic guardrail pass over a converted doc.

Mirrors ``docling_poc/guardrails.py:assess_pdf`` but takes an already-converted
``ConvertedDoc`` (so conversion happens once, in ``docling_converter``) and
returns the same ``assess_document`` report: confidence gate + furniture filter
+ per-table total reconciliation.
"""
from __future__ import annotations

from typing import Any

from . import normalize
from .docling_converter import ConvertedDoc


def assess(converted: ConvertedDoc, *, minimum_grade: str = "GOOD") -> dict[str, Any]:
    """Run the full guardrail pass over a converted document."""
    return normalize.assess_document(
        converted.grade,
        converted.doc.export_to_dict(),
        converted.tables,
        minimum_grade=minimum_grade,
    )
