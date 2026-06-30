# Vendored verbatim from PlatformRemote .../pdf_extraction/logic/services/chunking.py — do not edit here; keep in sync with source.
# Source: backend/app/agents/discovery/pdf_extraction/logic/services/chunking.py
"""Logical, structure-aware chunking of a DoclingDocument.

Wraps Docling's HierarchicalChunker, which segments by document structure
(sections grouped under their headings, each table emitted as its own chunk)
and needs no tokenizer — so there is no model download and the result is
deterministic. HybridChunker would add token-budget splitting but pulls a
HuggingFace tokenizer; reach for it only once a downstream embedding/LLM step
exists and a token budget actually matters.

Ported from the ``docling_poc`` reference pipeline
(``graphrag-poc/docling_poc/chunking.py``). Only ``docling_core`` (cheap, no
model download) is imported here.
"""
from __future__ import annotations

from dataclasses import dataclass

from docling_core.transforms.chunker import HierarchicalChunker
from docling_core.types.doc.document import TableItem


@dataclass(frozen=True)
class LogicalChunk:
    text: str                  # DocChunk.text, kept faithful (clean glyphs only at display)
    headings: tuple[str, ...]  # section heading hierarchy, () if none
    kind: str                  # "table" | "narrative"
    pages: tuple[int, ...]     # sorted unique page numbers across the chunk's items
    refs: tuple[str, ...]      # self_ref of each source item, for provenance
    n_items: int


def logical_chunks(doc) -> list[LogicalChunk]:
    """Segment a DoclingDocument into structure-aware logical chunks."""
    out = []
    for c in HierarchicalChunker().chunk(doc):
        items = c.meta.doc_items
        is_table = any(isinstance(it, TableItem) for it in items)
        pages = tuple(sorted({p.page_no for it in items for p in it.prov}))
        refs = tuple(it.self_ref for it in items)
        out.append(LogicalChunk(
            text=c.text,
            headings=tuple(c.meta.headings or ()),
            kind="table" if is_table else "narrative",
            pages=pages,
            refs=refs,
            n_items=len(items),
        ))
    return out


def chunk_summary(chunks: list[LogicalChunk]) -> dict:
    """Count chunks by kind and collect the page span."""
    pages = sorted({p for c in chunks for p in c.pages})
    return {
        "total": len(chunks),
        "table": sum(1 for c in chunks if c.kind == "table"),
        "narrative": sum(1 for c in chunks if c.kind == "narrative"),
        "pages": pages,
    }
