# Handover 04 — Public extract() entrypoint (agent C1)

Status: COMPLETE. `extract()` written + verified with a REAL SharePoint Portfolio
run (PDF + xlsx). No blockers for D1.

## What changed (1 file)

Filled in `pipeline/pipeline/adapters/docling_extract/__init__.py` — previously an
A1 placeholder docstring, now the single public entrypoint. Mirrors PlatformRemote's
`_process_one` (convert → guardrails → chunk → facts) as a single-file, single-document
version: no ProgressEmitter, no agent_tasks, no download bundle.

Signature:
```python
async def extract(name: str, data: bytes, *, minimum_grade: str | None = None) -> dict
```

Behavior:
- `data` empty → returns `{"error": "empty file (0 bytes)", "name": name}` (no convert).
- `min_grade = (minimum_grade or settings.docling_min_grade or "GOOD").upper()`.
- Gets warm singleton `get_converter()` (instant after boot warmup).
- Conversion runs OFF the loop: `await asyncio.to_thread(convert_bytes, converter, name, data, max_pages=settings.docling_max_pages)`.
- `guardrails.assess(...)` → `chunking.logical_chunks`/`chunk_summary` → `facts.extract_facts`/`facts_to_records`.
- Whole convert→facts body wrapped in `try/except Exception`; on failure returns
  `{"name": name, "error": str(e)}` and logs a `logging.warning`. One bad document
  NEVER raises to the caller (verified — see below).
- All heavy imports (`from .converter import get_converter`,
  `from .logic.services import chunking, facts, guardrails`,
  `from .logic.services.docling_converter import convert_bytes`, `from pipeline.config import settings`)
  are LOCAL inside `extract()`, so importing the package stays cheap and does not pull
  in docling_core/pandas/torch just to import.

## Return dict shape — DATA CONTRACT for D1 (be precise)

On SUCCESS, exactly these 9 keys (all JSON-ready, no Pydantic objects):

| key             | type            | notes |
|-----------------|-----------------|-------|
| `name`          | str             | echoes the input `name`. |
| `markdown`      | str             | full document markdown. **Can be large** (xlsx hit ~40 KB) — D1 must apply `settings.docling_markdown_inline_cap` (default 100_000). |
| `grade`         | str             | `EXCELLENT` / `GOOD` / `OK` / `POOR` (PDFs); `UNSPECIFIED` for xlsx/spreadsheets. |
| `pages`         | int \| None     | page count; xlsx reports a synthetic page count (sheets). |
| `facts`         | list[dict]      | from `facts_to_records()` — plain dicts (see fields below). |
| `fact_count`    | int             | `len(facts)`. |
| `guardrails`    | dict            | `GuardrailReport`-shaped: `grade`, `quality_ok`, `furniture_dropped`, `body_elements`, `tables_audited`, `table_issues` (list), `passed`, `needs_review`. |
| `needs_review`  | bool            | convenience copy of `guardrails["needs_review"]`. |
| `chunk_summary` | dict            | `ChunkSummary`-shaped: `total`, `table`, `narrative`, `pages` (list[int]). |

On EMPTY/FAILURE, ONLY `{"name": str, "error": str}` — none of the success keys
are present. D1 MUST branch on `"error" in result` (do NOT assume `markdown`/`facts`
exist).

Each fact dict (`facts[i]`) has fields:
`metric` (str), `section` (str|None), `dimensions` (str, " / "-joined), `value` (float),
`raw` (str), `unit` (str: billions|millions|thousands|units|percent), `scale_multiplier`
(float), `currency` (str|None), `table_index` (int), `page` (int|None), `bbox`
(list[float] [l,t,r,b] | None), `reconciled` (bool|None). Apply
`settings.docling_facts_inline_cap` (default 200) downstream — a cap-table xlsx produced
899 facts.

## Two FinancialFact representations (don't conflate)
- **Dataclass** `FinancialFact` in `logic/services/facts.py` — the working/in-memory
  representation (tuple dimensions/bbox). `extract_facts()` returns these.
- **Pydantic** `FinancialFact` in `logic/models/models.py` — the serialization boundary.
- `facts_to_records(fact_objs)` bridges them: it yields **plain `dict`s** that map
  field-for-field onto the Pydantic model. `extract()` returns those plain dicts in
  `facts` — it does NOT instantiate either FinancialFact type. D1 gets dicts, ready
  for JSON.

## Data-structure / coherency
TRANSIENT ONLY. `extract()` returns in-memory data; nothing is persisted, written to
disk, or sent to a DB. No migrations, no schema impact. The caller owns the result.

## Verification

### Static
- `./.venv/bin/python -m py_compile pipeline/adapters/docling_extract/__init__.py` → `PY_COMPILE_OK`.
- `./.venv/bin/ruff check pipeline/adapters/docling_extract/__init__.py` → `All checks passed!`.

### REAL extraction (SharePoint Portfolio — Theker Robotics, Fondo IV)
Drive resolved via `client._get_site_id` + `client._resolve_drive`; traversed 345 items
/ 239 files; downloaded bytes via `client._download_file(drive_id, item_id)`; ran
`await extract(name, bytes)`. Converter WARMED once (untimed) first, so the numbers
below are warm-path.

| Document | type | grade | pages | md_len | fact_count | warm time | s/page |
|----------|------|-------|-------|--------|-----------|-----------|--------|
| `[THEKER ROBOTICS - 2026Q1] Cuenta de pérdidas y ganancias.pdf` | PDF (P&L) | EXCELLENT | 1 | 3905 | **40** | 1.68 s | 1.68 |
| `3.2- Exhibit 1.10.a - ISHA Theker (PyG).pdf` | PDF (P&L) | GOOD | 1 | 1678 | 0 | 1.91 s | 1.91 |
| `3.1- Exhibit 1.10.a - ISHA Theker (Balance).pdf` | PDF (Balance) | GOOD | 1 | 2913 | 0 | 0.28 s | 0.28 |
| `Theker Cap Table_v6.xlsx` | xlsx | UNSPECIFIED | 4 | 40167 | **899** | 0.26 s | — |
| `BP_ISHA_v0.xlsx` | xlsx | UNSPECIFIED | 1 | 2387 | 35 | 0.26 s | — |

- **Facts WERE extracted from a financial PDF**: the 2026Q1 P&L PDF yielded 40 facts,
  grade EXCELLENT, currency `EUR` correctly detected (e.g. `metric="1. Importe neto de
  la cifra de negocios."`, `value=175.43151`, `raw="175.431,51"`, `currency="EUR"`).
  (The two Exhibit PDFs graded GOOD but yielded 0 facts — docling did not emit those as
  structured table cells; expected for those particular scanned-layout exhibits.)
- **xlsx path works**: markdown non-empty, large fact yields (cap table = 899 facts).
- **Cold (first, untimed-against-contract) call** earlier measured ~42 s for a 2-page
  PDF because model loading happened in that call; warm path is ~0.3–1.9 s/page. The
  MCP startup warmup (B1) pays the cold cost at boot, so production `fetch_document`
  calls hit the warm path.
- **Failure isolation CONFIRMED**: several large public-deed PDFs (e.g. `Theker - Share
  capital & bylaws public deed 3843.2025.pdf`) raise `single positional indexer is
  out-of-bounds` inside the vendored facts/normalize code on certain table shapes.
  `extract()` caught each one and returned `{"name", "error": "single positional indexer
  is out-of-bounds"}` — no exception propagated. This is exactly the per-document
  isolation the contract promises; D1 can rely on it.
- **Empty input**: `await extract("x.pdf", b"")` → `{'error': 'empty file (0 bytes)', 'name': 'x.pdf'}`.

Throwaway test scripts were written under `/tmp` and deleted after the run.

## Open items for D1 (how to call extract)
1. Call: `result = await extract(name, data, minimum_grade=None)` where `name` is the
   original filename (drives docling format detection by extension) and `data` is raw
   bytes. `minimum_grade` is optional — leave `None` to use `settings.docling_min_grade`.
2. **Branch on errors first**: `if "error" in result: ...` (no success keys present).
   Otherwise read the 9 success keys above.
3. **Apply the inline caps** D1 owns (extract() does NOT apply them):
   - `settings.docling_markdown_inline_cap` (default 100_000) — truncate/handle
     `result["markdown"]` before inlining into an MCP/HTTP response.
   - `settings.docling_facts_inline_cap` (default 200) — cap `result["facts"]`
     (cap-table xlsx legitimately produces ~900 facts).
4. `extract()` is `async` and already offloads conversion via `asyncio.to_thread`; call
   it with `await` from D1's async handler — do not wrap it in another thread.
5. Importing `extract` is cheap, but the FIRST call builds the converter (~3.5 s model
   load, or model download on a fresh machine) unless the MCP startup warmup (B1) has
   already run. In the MCP server it has.

---

## Fix: markdown preserved on best-effort failure (DD-04 required fix, 2026-06-30)

The DD found that conversion + guardrails + chunking + facts were wrapped in ONE
try/except, so a facts hiccup (e.g. `single positional indexer is out-of-bounds` in the
vendored facts/normalize code on odd table shapes) discarded the already-converted
markdown and returned `{name, error}`. Fixed by splitting `extract()` into two tiers.

### New structure (only file touched: `pipeline/pipeline/adapters/docling_extract/__init__.py`)
- **Tier 1 — ESSENTIAL (conversion):** `get_converter()` (warm singleton, NOT
  `build_converter()`) + `await asyncio.to_thread(convert_bytes, ..., max_pages=settings.docling_max_pages)`
  in their own try/except. If conversion raises (or returns no document), return
  `{"name": name, "error": str(e)}` — nothing usable to return. Empty input still
  short-circuits to `{"error": "empty file (0 bytes)", "name": name}` before any import.
- **Tier 2 — BEST-EFFORT (guardrails / chunking / facts):** runs only AFTER a successful
  conversion, inside a SEPARATE try/except. On success → all keys populated, `warning=None`.
  On ANY exception here → markdown is preserved; degraded fields take empty forms and a
  `warning` string is set + a stdlib `logging.warning` is emitted.

Signature, lazy heavy imports, warm singleton, `asyncio.to_thread`, `min_grade`
resolution, and the "no inline caps here (D1 owns caps)" rule are all UNCHANGED.

### FINAL RETURN CONTRACT for D1 (3 cases) — keys are STABLE

**(a) FULL SUCCESS** — 10 keys, all JSON-ready:

| key | type | value |
|-----|------|-------|
| `name` | str | echoes input `name` |
| `markdown` | str | full document markdown (non-empty; D1 applies `docling_markdown_inline_cap`) |
| `grade` | str | `EXCELLENT`/`GOOD`/`OK`/`POOR`; `UNSPECIFIED` for xlsx |
| `pages` | int \| None | page count |
| `facts` | list[dict] | plain dicts from `facts_to_records()` (see field list above); D1 applies `docling_facts_inline_cap` |
| `fact_count` | int | `len(facts)` |
| `guardrails` | dict | `GuardrailReport`-shaped 8-key dict |
| `needs_review` | bool | `bool(guardrails["needs_review"])` |
| `chunk_summary` | dict | `ChunkSummary`-shaped 4-key dict |
| `warning` | str \| None | **`None`** on full success |

**(b) PARTIAL SUCCESS (best-effort steps failed; markdown survives)** — SAME 10 keys:

| key | type | value |
|-----|------|-------|
| `name` | str | echoes input `name` |
| `markdown` | str | full document markdown (non-empty — the whole point of the fix) |
| `grade` | str | from conversion (`converted.grade`) |
| `pages` | int \| None | from conversion |
| `facts` | list[dict] | **`[]`** |
| `fact_count` | int | **`0`** |
| `guardrails` | dict | **`{}`** |
| `needs_review` | bool | **`False`** |
| `chunk_summary` | dict | **`{}`** |
| `warning` | str | **`"facts/guardrails extraction failed: <err>; returning markdown only"`** (non-None) |

D1 rule: a non-None `warning` means markdown is usable but facts/guardrails/chunk_summary
are degraded to their empty forms. There is NO `error` key in this case.

**(c) CONVERSION FAILURE (or empty input)** — exactly 2 keys, no success keys present:

| key | type | value |
|-----|------|-------|
| `name` | str | echoes input `name` |
| `error` | str | `str(e)` from conversion, or `"empty file (0 bytes)"`, or `"conversion produced no document"` |

D1 MUST still branch on `"error" in result` FIRST. The presence of `error` and the
presence of `markdown`/`warning` are mutually exclusive: `error` ⟺ no markdown.

### Verification (2026-06-30, pipeline/.venv, docling 2.107.0)
- `py_compile` → `PY_COMPILE_OK`; `ruff check` → `All checks passed!`.
- **(a) Happy path** — real `downloads/Theker_SeriesA_v7.xlsx`: `error` absent,
  `markdown` len 191896, `fact_count` 4841, `warning` is `None`, all 10 keys present. PASS.
- **(b) Partial path** — monkeypatched `facts.extract_facts` to raise `ValueError("boom")`,
  re-ran on same xlsx bytes: `error` absent, `markdown` len 191896 (preserved),
  `facts == []`, `fact_count == 0`, `guardrails == {}`, `needs_review == False`,
  `chunk_summary == {}`, `warning` contains `"boom"`. PASS.
- **(c) Conversion failure** — `extract("garbage.pdf", b"not a real file")` →
  `{'name': 'garbage.pdf', 'error': 'Conversion failed ... PDFium: Data format error...'}`,
  no `markdown` key. PASS.

Throwaway verification script written under `/tmp` and deleted after the run.
