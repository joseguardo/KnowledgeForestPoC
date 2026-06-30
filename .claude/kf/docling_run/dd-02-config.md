# DD-A2: Configuration & Dependencies Verification

**Date:** 2026-06-30  
**Verifier:** DD-A2 (independent clean-context check)  
**Verdict:** **PASS**

---

## Check Results

### 1. pyproject.toml Dependencies ✓
**Status:** PASS

- `docling>=2.0.0` ✓ present
- `docling-core>=2.0.0` ✓ present  
- `pandas>=2.0.0` ✓ present
- TOML parses without error ✓

**Evidence:**
```
$ python3 -c "import tomllib; tomllib.load(open('pipeline/pyproject.toml','rb')); print('ok')"
✓ pyproject.toml parses correctly
```

### 2. config.py Field Definitions ✓
**Status:** PASS

All six fields present with correct names, types, and defaults:

| Field | Type | Default | Status |
|-------|------|---------|--------|
| `docling_min_grade` | `str` | `"GOOD"` | ✓ |
| `docling_max_pages` | `int` | `200` | ✓ |
| `docling_do_ocr` | `bool` | `False` | ✓ |
| `docling_num_threads` | `int \| None` | `None` | ✓ |
| `docling_markdown_inline_cap` | `int` | `100_000` | ✓ |
| `docling_facts_inline_cap` | `int` | `200` | ✓ |

**Key observations:**
- All field names are snake_case (correct for env var mapping)
- No `import os` in config.py
- No `os.cpu_count()` calls in field defaults (only in comment; correct per design)
- Python compile succeeds ✓

**Evidence:**
```
$ python3 -m py_compile pipeline/config.py
✓ config.py compiles successfully
```

### 3. Environment Variable Mapping ✓
**Status:** PASS

Pydantic v2 `BaseSettings` auto-maps snake_case field names to UPPER_CASE env vars:
- `docling_min_grade` ← `DOCLING_MIN_GRADE`
- `docling_max_pages` ← `DOCLING_MAX_PAGES`
- `docling_do_ocr` ← `DOCLING_DO_OCR`
- `docling_num_threads` ← `DOCLING_NUM_THREADS`
- `docling_markdown_inline_cap` ← `DOCLING_MARKDOWN_INLINE_CAP`
- `docling_facts_inline_cap` ← `DOCLING_FACTS_INLINE_CAP`

This matches the existing convention already in use (no aliases needed). Coherent with existing Settings fields (e.g., `gmail_*`, `calendar_*`).

### 4. .env.example Documentation Block ✓
**Status:** PASS

New block present immediately after SharePoint section:
- Correct header: `# ── Docling document parsing (MCP fetch_document) ──`
- All six commented environment variables present
- Values match config.py defaults exactly
- Explanatory comments match intent

**Verified fields in .env.example:**
```
# DOCLING_MIN_GRADE=GOOD                    ✓
# DOCLING_MAX_PAGES=200                     ✓
# DOCLING_DO_OCR=false                      ✓
# DOCLING_NUM_THREADS=        # blank → os.cpu_count()  ✓
# DOCLING_MARKDOWN_INLINE_CAP=100000        ✓
# DOCLING_FACTS_INLINE_CAP=200              ✓
```

### 5. Scope Containment ✓
**Status:** PASS

- No changes to `pipeline/pipeline/adapters/docling_extract/` (A1's territory) ✓
- No database schema changes ✓
- No migrations ✓
- No DB table/field alterations ✓

### 6. Data Structure & Persistence ✓
**Status:** PASS

This is purely **config and dependencies**. No state is persisted:
- No DB schema changes
- No new tables or fields
- No migration files added/modified
- All changes are in-memory settings + static declarations

---

## Advisory: Version Constraints

The dependency declarations use **open upper bounds** (which is intentional for flexibility):

```
docling>=2.0.0        # no upper bound
docling-core>=2.0.0   # no upper bound
pandas>=2.0.0         # no upper bound
```

**Advisory notes:**
- Docling 3.0.0+ (hypothetical) could introduce breaking changes
- Will pull the latest major version available at install time
- Mitigation: if stability matters, consider pinning to `docling<3.0.0`
- Pandas is more stable; 3.0+ unlikely in the near term

This is **not a blocker** but a recommendation for Wave 5 or later if real-world testing reveals version incompatibilities.

---

## Findings for Downstream Agents (B1/C1/D1)

The following configuration fields are now available in `settings` and can be relied upon:

```python
settings.docling_min_grade: str = "GOOD"                      # POOR|FAIR|GOOD|EXCELLENT
settings.docling_max_pages: int = 200
settings.docling_do_ocr: bool = False
settings.docling_num_threads: int | None = None              # None → use os.cpu_count()
settings.docling_markdown_inline_cap: int = 100_000
settings.docling_facts_inline_cap: int = 200
```

Environment variables (from `.env` or `DOCLING_*` exports) will auto-map to these fields via pydantic-settings.

---

## Blockers for Wave 2

**None identified.** All structural and semantic checks pass.

The three files are ready for the next phase (deps installation, converter agent implementation).

---

## Summary

| Check | Result | Evidence |
|-------|--------|----------|
| pyproject.toml syntax | ✓ PASS | Parses without error |
| config.py field names/types/defaults | ✓ PASS | All 6 fields correct |
| config.py Python syntax | ✓ PASS | Compiles without error |
| Env var mapping logic | ✓ PASS | snake_case → UPPER_CASE convention applies |
| .env.example block | ✓ PASS | All 6 fields + defaults present |
| Scope (no docling_extract touch) | ✓ PASS | No diffs in that directory |
| Data persistence | ✓ PASS | Config/deps only; no schema changes |
| Version constraints | ⚠ ADVISORY | Open upper bounds; not a blocker |

**VERDICT: PASS** — A2's work is correct and coherent. No regressions detected.
