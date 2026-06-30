# Vendored verbatim from PlatformRemote .../pdf_extraction/logic/models/models.py — do not edit here; keep in sync with source.
# Source: backend/app/agents/discovery/pdf_extraction/logic/models/models.py
"""Pydantic output models for the PDF extraction agent.

These are the serialization shapes stored verbatim in ``agent_tasks.output``.
``FinancialFact`` matches ``facts.facts_to_records`` (the ported reference
pipeline) field-for-field; ``GuardrailReport`` matches ``normalize.assess_document``.
The dataclasses in ``logic/services`` stay the working representation — these
models are the boundary that crosses into persistence + the MCP/HTTP surface.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class FinancialFact(BaseModel):
    metric: str
    section: Optional[str] = None
    dimensions: str = ""                       # joined with " / " (matches facts_to_records)
    value: float
    raw: str
    unit: str                                  # billions|millions|thousands|units|percent
    scale_multiplier: float
    currency: Optional[str] = None
    table_index: int
    page: Optional[int] = None
    bbox: Optional[list[float]] = None         # [left, top, right, bottom]
    reconciled: Optional[bool] = None          # True reconciles / False broken / None leaf


class TableIssue(BaseModel):
    table: int
    row: str
    column: str
    expected: float
    got: float


class GuardrailReport(BaseModel):
    grade: str                                 # POOR|FAIR|GOOD|EXCELLENT|UNSPECIFIED
    quality_ok: bool
    furniture_dropped: int
    body_elements: int
    tables_audited: int
    table_issues: list[TableIssue] = Field(default_factory=list)
    passed: bool
    needs_review: bool


class ChunkSummary(BaseModel):
    total: int
    table: int
    narrative: int
    pages: list[int] = Field(default_factory=list)


class FileExtractResult(BaseModel):
    name: str
    pages: Optional[int] = None
    markdown: str = ""
    facts: list[FinancialFact] = Field(default_factory=list)
    guardrails: Optional[GuardrailReport] = None
    chunk_summary: Optional[ChunkSummary] = None
    error: Optional[str] = None                # set when this file failed; siblings still return


class ExtractResult(BaseModel):
    files: list[FileExtractResult] = Field(default_factory=list)
    combined_markdown: str = ""                # all files' markdown, concatenated with headers
    fact_count: int = 0
    needs_review: bool = False                 # any file flagged needs_review
    download_url: Optional[str] = None         # signed bundle link (set by the MCP path)
    platform: Optional[dict[str, Any]] = None  # {agent_id, started_at, finished_at}
