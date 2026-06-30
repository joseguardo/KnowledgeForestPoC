# Handover 02 — Docling deps / config / env (agent A2)

## What changed (3 files)

### 1. `pipeline/pyproject.toml`
Appended to `[project].dependencies` (after `python-docx>=1.1`):
```
# Docling document parsing (fetch_document) — pulls torch transitively; layout/table models download on first run (pre-bake in deploy image).
"docling>=2.0.0",
"docling-core>=2.0.0",
"pandas>=2.0.0",
```

### 2. `pipeline/pipeline/config.py`
New block in `Settings` (after `sharepoint_portfolio_root`, before `model_config`):
```
docling_min_grade: str = "GOOD"
docling_max_pages: int = 200
docling_do_ocr: bool = False
docling_num_threads: int | None = None
docling_markdown_inline_cap: int = 100_000
docling_facts_inline_cap: int = 200
```
Each carries an explanatory comment matching existing style. `docling_num_threads`
default left as `None` (no `import os` in defaults — converter agent resolves
`os.cpu_count()` at converter-build time). Env loader uppercases field names, so
`docling_min_grade` ← `DOCLING_MIN_GRADE`, etc.

### 3. `pipeline/.env.example`
New commented block immediately after the SharePoint block:
```
# ── Docling document parsing (MCP fetch_document) ──
# fetch_document parses PDFs/Word/PowerPoint/Excel with Docling → markdown + facts.
# Models load at server startup (warm), so per-call overhead is ~0. Tune below.
# DOCLING_MIN_GRADE=GOOD
# DOCLING_MAX_PAGES=200
# DOCLING_DO_OCR=false
# DOCLING_NUM_THREADS=        # blank → os.cpu_count()
# DOCLING_MARKDOWN_INLINE_CAP=100000
# DOCLING_FACTS_INLINE_CAP=200
```

## Data structures
None persisted. Config/deps only. **No DB/schema change, no migration.**

## Verification done
- `tomllib.load(pyproject.toml)` → `pyproject OK`
- `python -m py_compile pipeline/config.py` → OK
- `ruff check pipeline/config.py` → All checks passed!
- Did NOT `pip install` and did NOT start the server (per instructions).

## Interfaces next agents (B1/C1/D1) rely on
New `settings.docling_*` fields and defaults:
- `settings.docling_min_grade: str = "GOOD"` (POOR|FAIR|GOOD|EXCELLENT)
- `settings.docling_max_pages: int = 200`
- `settings.docling_do_ocr: bool = False`
- `settings.docling_num_threads: int | None = None` (None → resolve os.cpu_count() at converter build)
- `settings.docling_markdown_inline_cap: int = 100_000`
- `settings.docling_facts_inline_cap: int = 200`

## Open items
- `docling` / `docling-core` / `pandas` declared but NOT installed yet — intentional;
  Wave 5 installs them. Importing docling in the venv will fail until then.
- Did not touch `pipeline/pipeline/adapters/docling_extract/` (agent A1's territory).
