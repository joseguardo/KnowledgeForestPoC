# Vendored verbatim from PlatformRemote .../pdf_extraction/logic/services/normalize.py — do not edit here; keep in sync with source.
# Source: backend/app/agents/discovery/pdf_extraction/logic/services/normalize.py
"""Deterministic guardrail + normalization layer over Docling output.

Operates on Docling's exported structures (markdown strings, the export_to_dict
mapping, table DataFrames) so it is decoupled from running Docling itself.

Ported verbatim from the ``docling_poc`` reference pipeline
(``graphrag-poc/docling_poc/normalize.py``) — pure Python, no docling import,
so it stays unit-testable without the heavy dependency.
"""

# Guarded glyph map: only known font-glyph names are rewritten. Real slash-words
# in text (e.g. "property/casualty", "per /unit") are deliberately left alone.
GLYPH_MAP = {
    "/dollarsign": "$",
    "/parenleft": "(",
    "/parenright": ")",
    "/minus": "−",
    "/percent": "%",
}


def clean_glyphs(text: str) -> str:
    """Rewrite known unmapped font-glyph names to their characters."""
    for glyph, char in GLYPH_MAP.items():
        text = text.replace(glyph, char)
    return text


def parse_number(s: str):
    """Parse a financial cell to a float, or None if it holds no number.

    Handles thousands separators, currency symbols, leaked $ glyphs, and
    accounting-style parenthesized negatives. Blanks and dashes -> None.
    """
    s = clean_glyphs(s).strip()
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    # drop currency symbols, thousands separators, and whitespace
    for ch in ("$", "€", "£", ",", " "):
        s = s.replace(ch, "")
    if not s or not any(c.isdigit() for c in s):
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def split_header_levels(col: str) -> tuple:
    """Split a Docling dot-joined column header into its hierarchy levels.

    Docling flattens multi-level table headers as "Top.Bottom" (e.g.
    "Three Months Ended.September 28, 2024"). Returns the levels as a tuple,
    suitable for building a pandas MultiIndex.
    """
    return tuple(part.strip() for part in col.split("."))


def body_elements(doc: dict, keys=("texts", "tables", "pictures")) -> list:
    """Return content elements in the body layer, dropping `furniture`.

    Docling tags running headers/footers, page numbers and similar boilerplate
    as content_layer == "furniture". This is the deterministic noise filter.
    """
    out = []
    for key in keys:
        for item in doc.get(key, []):
            if item.get("content_layer") != "furniture":
                out.append(item)
    return out


# Docling QualityGrade ordering, worst to best.
_GRADE_ORDER = ["POOR", "FAIR", "GOOD", "EXCELLENT"]


def passes_quality_gate(grade, minimum: str = "GOOD") -> bool:
    """Whether a Docling confidence grade meets a minimum bar.

    Accepts a grade name, a QualityGrade enum, or its "QualityGrade.X" repr.
    Unknown grades fail closed (route to review).
    """
    name = str(grade).split(".")[-1].upper()
    if name not in _GRADE_ORDER or minimum.upper() not in _GRADE_ORDER:
        return False
    return _GRADE_ORDER.index(name) >= _GRADE_ORDER.index(minimum.upper())


def reconcile(components, total, tol: float = 0.5) -> bool:
    """Whether component values sum to a stated total within tolerance.

    None components are ignored (blank/non-numeric cells). This catches the
    column-shift and cell-merge errors that OCR and table-structure mistakes
    introduce — the numbers stop adding up.
    """
    if total is None:
        return False
    subtotal = sum(c for c in components if c is not None)
    return abs(subtotal - total) <= tol


def audit_table(df, tol: float = 0.5) -> list:
    """Flag 'Total' rows that don't equal the numeric rows directly above them.

    Heuristic: a row whose label starts with 'total' is reconciled, per value
    column, against the contiguous run of numeric rows immediately above it
    (the run stops at a section header / blank row or a prior total). Returns a
    list of discrepancies: {row, column, expected, got}.

    This catches column-shift and cell-merge errors where the math breaks. It is
    a heuristic — deeply nested statements may need explicit component mapping.
    """
    labels = df.iloc[:, 0].astype(str).tolist()
    issues = []
    for ci in range(1, df.shape[1]):
        col = df.columns[ci]  # positional access — robust to duplicate headers
        cells = df.iloc[:, ci].astype(str).tolist()
        for i, label in enumerate(labels):
            if not label.strip().lower().startswith("total"):
                continue
            total = parse_number(cells[i])
            if total is None:
                continue
            components = []
            for j in range(i - 1, -1, -1):
                if labels[j].strip().lower().startswith("total"):
                    break
                val = parse_number(cells[j])
                if val is None:  # section header / blank stops the run
                    break
                components.append(val)
            if components and not reconcile(components, total, tol=tol):
                issues.append({
                    "row": label,
                    "column": col,
                    "expected": round(sum(components), 4),
                    "got": total,
                })
    return issues


def assess_document(grade, doc: dict, tables, minimum_grade: str = "GOOD") -> dict:
    """Run the full deterministic guardrail pass over one converted document.

    Combines the confidence gate, furniture noise count, and per-table total
    reconciliation into a single report. `passed` is True only when quality
    clears the bar AND no table fails reconciliation; otherwise `needs_review`.
    """
    quality_ok = passes_quality_gate(grade, minimum=minimum_grade)
    body = body_elements(doc)

    def total_count(key):
        return len(doc.get(key, []))

    furniture_dropped = sum(total_count(k) for k in ("texts", "tables", "pictures")) - len(body)

    table_issues = []
    for idx, df in enumerate(tables):
        for issue in audit_table(df):
            table_issues.append({"table": idx, **issue})

    passed = quality_ok and not table_issues
    return {
        "grade": str(grade).split(".")[-1].upper(),
        "quality_ok": quality_ok,
        "furniture_dropped": furniture_dropped,
        "body_elements": len(body),
        "tables_audited": len(tables),
        "table_issues": table_issues,
        "passed": passed,
        "needs_review": not passed,
    }
