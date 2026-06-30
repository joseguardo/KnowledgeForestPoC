# Vendored verbatim from PlatformRemote .../pdf_extraction/logic/services/docling_converter.py — do not edit here; keep in sync with source.
# Source: backend/app/agents/discovery/pdf_extraction/logic/services/docling_converter.py
"""Docling conversion glue — the ONLY module that imports ``docling`` itself.

Conversion is the runtime cost center (~1.4-4.5 s/page born-digital, ~30 s/page
when OCR kicks in) and pulls a large dependency tree (torch + layout/table models
downloaded on first run), so the import is lazy: it happens inside the functions,
not at module import time. That keeps app startup and MCP tool registration cheap
and means a docling install/import problem can't break unrelated agents.

The chunking / facts / guardrails ports operate on the resulting
``DoclingDocument`` and its table DataFrames and never import docling, so they
stay fast and unit-testable on saved fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any


@dataclass
class ConvertedDoc:
    name: str
    markdown: str
    grade: str                      # POOR|FAIR|GOOD|EXCELLENT|UNSPECIFIED
    doc: Any                        # DoclingDocument
    tables: list = field(default_factory=list)   # list[pd.DataFrame]
    pages: int | None = None


def build_converter():
    """Build a single ``DocumentConverter`` to reuse across a batch.

    Instantiation loads the layout/table models, so build once per run and pass
    it to every ``convert_bytes`` call rather than rebuilding per file.
    """
    from docling.document_converter import DocumentConverter

    return DocumentConverter()


def _document_stream(name: str, data: bytes):
    """Wrap raw bytes as a Docling ``DocumentStream`` (no temp file on disk)."""
    # DocumentStream moved modules across docling versions; try the common paths.
    try:
        from docling.datamodel.base_models import DocumentStream
    except ImportError:  # pragma: no cover - version drift fallback
        from docling_core.types.io import DocumentStream  # type: ignore

    return DocumentStream(name=name, stream=BytesIO(data))


def convert_bytes(converter, name: str, data: bytes, *, max_pages: int | None = None) -> ConvertedDoc:
    """Convert one PDF (as bytes) into a ``ConvertedDoc``.

    Returns the rendered markdown, the Docling confidence grade, the
    ``DoclingDocument`` (for chunking / facts), and each table as a DataFrame.
    Synchronous + CPU-heavy — call via ``asyncio.to_thread`` from the orchestrator.
    """
    source = _document_stream(name, data)
    if max_pages:
        result = converter.convert(source, max_num_pages=max_pages)
    else:
        result = converter.convert(source)

    doc = result.document
    grade = getattr(getattr(result, "confidence", None), "mean_grade", "UNSPECIFIED")

    tables = []
    for t in doc.tables:
        try:
            tables.append(t.export_to_dataframe(doc))
        except Exception:  # noqa: BLE001 - a single bad table shouldn't sink the doc
            pass

    pages = len(getattr(doc, "pages", {}) or {}) or None
    return ConvertedDoc(
        name=name,
        markdown=doc.export_to_markdown(),
        grade=str(grade).split(".")[-1].upper(),
        doc=doc,
        tables=tables,
        pages=pages,
    )
