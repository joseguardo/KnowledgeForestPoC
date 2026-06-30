# Vendored verbatim from PlatformRemote .../pdf_extraction/logic/services/facts.py — do not edit here; keep in sync with source.
# Source: backend/app/agents/discovery/pdf_extraction/logic/services/facts.py
"""Deterministic isolation of financial facts from a DoclingDocument's tables.

Every numeric table cell becomes a structured `FinancialFact` (metric, period
dimensions, value, unit/scale, currency, provenance, reconciliation flag). No
LLM: numbers come straight from the parsed/reconciled tables via normalize.py,
so facts are exact and auditable. Scale/currency detection is heuristic and
documented as such.

Ported from the ``docling_poc`` reference pipeline
(``graphrag-poc/docling_poc/facts.py``); the only change is the flat
``import chunking`` / ``from normalize import …`` becoming package-relative
imports.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import chunking
from .normalize import audit_table, clean_glyphs, parse_number, split_header_levels

_SCALE_TOKENS = [
    ("in billions", 1e9, "billions"),
    ("in millions", 1e6, "millions"),
    ("in thousands", 1e3, "thousands"),
]
_CURRENCY_TOKENS = [("$", "USD"), ("usd", "USD"), ("€", "EUR"), ("eur", "EUR"),
                    ("£", "GBP"), ("gbp", "GBP")]


@dataclass(frozen=True)
class Scale:
    multiplier: float
    unit: str            # "billions"|"millions"|"thousands"|"units"|"percent"
    currency: str | None
    source: str          # where the scale was detected


@dataclass(frozen=True)
class FinancialFact:
    metric: str
    section: str | None
    dimensions: tuple[str, ...]
    value: float
    raw: str
    unit: str
    scale_multiplier: float   # value kept as printed; multiplier carried, never auto-applied
    currency: str | None
    table_index: int
    page: int | None
    bbox: tuple[float, float, float, float] | None
    reconciled: bool | None   # True total reconciles / False broken / None leaf


def _detect_currency(*texts: str) -> str | None:
    for t in texts:
        low = t.lower()
        for token, code in _CURRENCY_TOKENS:
            if token in low:
                return code
    return None


def detect_scale(*, caption: str = "", heading: str = "", narrative: str = "",
                 col_header: str = "", row_label: str = "", cell: str = "") -> Scale:
    """Heuristically infer magnitude/unit/currency for a cell.

    Precedence for magnitude: caption -> heading -> narrative -> column -> row.
    Per-share rows and percent columns are never rescaled. This is best-effort;
    mixed-scale tables ("in millions, except per share") rely on the per-share
    guard and may otherwise fall back to plain units.
    """
    currency = _detect_currency(caption, heading, narrative, col_header, row_label, cell)
    row_low, col_low = row_label.lower(), col_header.lower()

    if "%" in col_header or "%" in row_label or "percent" in col_low:
        return Scale(1.0, "percent", currency, "column")
    if "per share" in row_low or "per-share" in row_low or "shares" in row_low:
        return Scale(1.0, "units", currency, "row")

    for label, (name, frag) in [("caption", ("caption", caption)),
                                ("heading", ("heading", heading)),
                                ("narrative", ("narrative", narrative)),
                                ("column", ("column", col_header)),
                                ("row", ("row", row_label))]:
        low = frag.lower()
        for token, mult, unit in _SCALE_TOKENS:
            if token in low:
                return Scale(mult, unit, currency, name)
    return Scale(1.0, "units", currency, "default")


def facts_from_table(df: pd.DataFrame, *, table_index: int = 0, caption: str = "",
                     heading: str = "", narrative: str = "", page: int | None = None,
                     bbox: tuple | None = None) -> list[FinancialFact]:
    """Turn one table (as a DataFrame) into financial facts.

    Col 0 holds row labels; remaining columns are (dot-joined) period headers.
    Rows with no numeric cells are treated as in-table section sub-headers and
    used to disambiguate repeated labels (e.g. Products under Net sales vs Cost
    of sales). Numbers come via parse_number (which also cleans $ glyphs).
    """
    if df.shape[1] < 2:
        return []

    issues = audit_table(df)
    broken = {(i["row"], i["column"]) for i in issues}

    # currency is a table-level property: in financial statements only the first
    # cell of a column prints the symbol, so scan all cells + context once.
    all_cells = " ".join(clean_glyphs(str(x)) for x in df.values.ravel())
    table_currency = _detect_currency(all_cells, caption, heading, narrative)

    labels = df.iloc[:, 0].astype(str).tolist()
    facts: list[FinancialFact] = []
    current_section: str | None = None

    for r, raw_label in enumerate(labels):
        row_cells = [str(df.iloc[r, ci]) for ci in range(1, df.shape[1])]
        has_number = any(parse_number(x) is not None for x in row_cells)
        metric = clean_glyphs(raw_label).strip()

        if not has_number:
            if metric:
                current_section = metric
            continue

        is_total = metric.lower().startswith("total")
        for ci, col in enumerate(df.columns[1:], start=1):
            raw = str(df.iloc[r, ci])
            value = parse_number(raw)
            if value is None:
                continue
            scale = detect_scale(caption=caption, heading=heading, narrative=narrative,
                                 col_header=str(col), row_label=metric, cell=clean_glyphs(raw))
            reconciled = (False if (raw_label, col) in broken else True) if is_total else None
            facts.append(FinancialFact(
                metric=metric,
                section=current_section or (heading or None),
                dimensions=split_header_levels(str(col)),
                value=value,
                raw=raw,
                unit=scale.unit,
                scale_multiplier=scale.multiplier,
                currency=table_currency,
                table_index=table_index,
                page=page,
                bbox=bbox,
                reconciled=reconciled,
            ))
    return facts


def extract_facts(doc) -> list[FinancialFact]:
    """Extract financial facts from every table in a DoclingDocument."""
    chunks = chunking.logical_chunks(doc)
    narr_by_heading: dict[tuple, list[str]] = {}
    for c in chunks:
        if c.kind == "narrative" and c.headings:
            narr_by_heading.setdefault(c.headings, []).append(c.text)

    out: list[FinancialFact] = []
    for t_idx, table in enumerate(doc.tables):
        df = table.export_to_dataframe(doc)

        tchunk = next((c for c in chunks if table.self_ref in c.refs), None)
        heading = tchunk.headings[-1] if (tchunk and tchunk.headings) else ""
        narrative = " ".join(narr_by_heading.get(tchunk.headings, [])) if tchunk else ""
        try:
            caption = table.caption_text(doc)
        except Exception:  # noqa: BLE001
            caption = ""

        prov = table.prov[0] if table.prov else None
        page = prov.page_no if prov else None
        bbox = (prov.bbox.l, prov.bbox.t, prov.bbox.r, prov.bbox.b) if prov else None

        out.extend(facts_from_table(df, table_index=t_idx, caption=caption,
                                    heading=heading, narrative=narrative,
                                    page=page, bbox=bbox))
    return out


def facts_to_records(facts: list[FinancialFact]) -> list[dict]:
    """Flatten facts to tidy long-format dicts (dimensions joined with ' / ')."""
    recs = []
    for f in facts:
        recs.append({
            "metric": f.metric,
            "section": f.section,
            "dimensions": " / ".join(f.dimensions),
            "value": f.value,
            "raw": f.raw,
            "unit": f.unit,
            "scale_multiplier": f.scale_multiplier,
            "currency": f.currency,
            "table_index": f.table_index,
            "page": f.page,
            "bbox": list(f.bbox) if f.bbox else None,
            "reconciled": f.reconciled,
        })
    return recs


def facts_to_dataframe(facts: list[FinancialFact]) -> pd.DataFrame:
    return pd.DataFrame(facts_to_records(facts))
