# Handover 05 — Route fetch_document through Docling extract() (agent D1)

Status: COMPLETE. The `fetch_document` MCP tool now returns clean markdown +
financial facts (MCP-capped) instead of raw text, via the new `extract()`. All
security guards unchanged. Verified with a REAL Portfolio PDF + xlsx, a txt
fallback, and both docling-error fallback paths. No blockers for DD-D1.

## File touched (1)
`pipeline/pipeline/mcp_server/tools/fetch_document.py` — step 6 only (parsing +
return shape) + imports + docstring. Steps 1–5 are byte-for-byte unchanged.

## Diff intent

### Imports added
- `from pathlib import Path`
- `from pipeline.adapters.docling_extract import extract`
- kept `from pipeline.adapters.document import DocumentAdapter`
- module constant: `_DOCLING_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".html", ".htm"}`
  (placed AFTER all imports so ruff E402 stays clean).

### Docstring
Rewritten to describe the new return (markdown + facts via Docling; PDF / Word /
PowerPoint / Excel / HTML parsed server-side; emails + text/markdown via the
lightweight fallback extractor; full key list incl. the deprecated `text` alias).
The security/scope paragraph (Portfolio-only, Kibo-only) is preserved.

### Step 6 (the only logic change)
Replaced the old `DocumentAdapter().process_file(...)[0]` → `{text, truncated}`
block with extension-branched parsing:

- `ext = Path(item["name"]).suffix.lower()`.
- **Docling formats** (`_DOCLING_EXTS`):
  - `result = await extract(item["name"], data, minimum_grade=settings.docling_min_grade)`
  - `if "error" in result:` (branched FIRST per the contract) → fall back to
    `DocumentAdapter().process_file(item["name"], data)[0]`, use its `.content`
    as markdown, `grade=None, pages=None, facts=[], fact_count=0,
    needs_review=False`, and set
    `warning = f"docling failed ({result['error']}); used fallback extractor"`.
    If the fallback ALSO raises, the exception propagates (clean error) — not
    swallowed.
  - else → read `markdown, facts, fact_count, grade, pages, needs_review,
    warning` from the success dict.
- **Text/email + any other ext** → `DocumentAdapter().process_file(...)[0]`;
  `.content` → markdown; `grade=None, pages=None, facts=[], fact_count=0,
  needs_review=False, warning=None`.

### Caps (owned here, not by extract())
- `md = markdown or ""`; `markdown_truncated = len(md) > settings.docling_markdown_inline_cap` (100_000); truncate if so.
- `facts_full = facts or []`; `facts_truncated = len(facts_full) > settings.docling_facts_inline_cap` (200); `facts = facts_full[:cap]`.
- `fact_count` is the FULL pre-cap count from `extract()` (not `len(facts)` after capping).

## FINAL response contract (STABLE) — every key + type

| key | type | notes |
|-----|------|-------|
| `name` | str | `item["name"]` |
| `title` | str | `Path(item["name"]).stem` (no docling title) |
| `sp_path` | str | from `_portfolio_path(item)` (unchanged) |
| `web_url` | str | `item.get("webUrl", "")` |
| `size` | int | byte size (unchanged) |
| `grade` | str \| None | docling grade (`EXCELLENT/GOOD/OK/POOR`, `UNSPECIFIED` for xlsx); None for text/email + fallback |
| `pages` | int \| None | page count; None for text/email + fallback |
| `markdown` | str | capped to `docling_markdown_inline_cap` |
| `markdown_truncated` | bool | true if markdown exceeded the cap |
| `facts` | list[dict] | capped to `docling_facts_inline_cap`; each dict shaped per handover-04 |
| `fact_count` | int | **FULL pre-cap count** |
| `facts_truncated` | bool | true if more facts existed than the cap |
| `needs_review` | bool | from docling guardrails; False otherwise |
| `warning` | str \| None | non-None on docling partial-success OR fallback-used |
| `text` | str | **DEPRECATED alias of `markdown`** (see note) |

### `text` alias note
`text` is kept as an exact alias of `markdown` (`"text": md`) with an inline
comment marking it deprecated. Rationale: existing consumers may read
`result["text"]`. **This is a contract CHANGE**: previously `text` was raw
extracted text (truncated at `max_content_length` = 500_000); now it is the
Docling markdown (truncated at `docling_markdown_inline_cap` = 100_000). The
**old `truncated` key is removed**, replaced by `markdown_truncated` /
`facts_truncated`. DD-D1 must confirm no consumer reads `["truncated"]`.

## Guards UNCHANGED (steps 1–5) — quoted verbatim from current file

1. Caller + Kibo-tenant gate:
   ```python
   ctx = caller()
   if KIBO_TENANT not in resolve_tenants(ctx.email):
       raise NotAuthenticated("fetch_document is restricted to Kibo tenant members.")
   ```
2. Drive allowlist:
   ```python
   if drive_id != settings.sharepoint_portfolio_drive_id:
       raise PermissionError("drive_id is not the Portfolio drive.")
   ```
3. Folder reject + portfolio-path assert:
   ```python
   item = await asyncio.to_thread(client._get_item_by_id, drive_id, item_id)
   if item.get("folder") is not None:
       raise ValueError("item is a folder, not a document.")
   sp_path = _portfolio_path(item)
   ```
   (`_portfolio_path()` itself — the `root:` parse + Portfolio-root assertion +
   PermissionError — is untouched.)
4. Size check:
   ```python
   size = int(item.get("size", 0) or 0)
   if size > settings.max_upload_bytes:
       raise ValueError(
           f"document is {size:,} bytes, over the {settings.max_upload_bytes:,}-byte limit."
       )
   ```
5. Download (unchanged): `data = await asyncio.to_thread(client._download_file, drive_id, item_id)`.

The two `asyncio.to_thread` SharePoint calls are unchanged. `extract()` is
`await`ed directly (it offloads conversion internally) — NOT wrapped in another
thread.

## Verification (REAL, bypassing caller(); pipeline/.venv, docling 2.107.0)

Throwaway `/tmp/verify_d1.py` replicated the tool's post-download step 6 +
caps + return, then asserted the full key set / types. Cleaned up after.

### Static
- `python -m py_compile pipeline/mcp_server/tools/fetch_document.py` → PY_COMPILE_OK.
- `ruff check ...fetch_document.py` → All checks passed!
- `python -c "import pipeline.mcp_server.tools.fetch_document as m; print(hasattr(m,'fetch_document'))"` → True.
- `asyncio.run(mcp.list_tools())` → `fetch_document registered: True`.

### Real Portfolio PDF (drive `b!cva5DQ…012eb`, `02_Portfolio/2.4 Portfolio Fondo IV/001. Theker Robotics`)
- Picked `Coatue_ThePathToGeneralPurposeRobots.pdf`.
- grade=**EXCELLENT**, pages=**45**, fact_count=**0** (int), markdown len=**19832**,
  facts_truncated=False, warning=None. (A pitch-deck PDF — no structured financial
  tables, so 0 facts is expected; the int/markdown contract holds.)

### Real Portfolio xlsx
- Picked `Theker business model.xlsx`.
- grade=**UNSPECIFIED**, pages=**2**, fact_count=**2548** (FULL count),
  markdown len=**62678**, markdown_truncated=False, facts_truncated=**True**,
  `len(facts)==200` (capped). Cap behavior confirmed: fact_count is pre-cap,
  facts list is capped.

### Text fallback (non-docling ext)
- `note.txt` (`b"# Hello\n\nThis is a plain text note.\n"`) → DocumentAdapter
  branch: grade=None, pages=None, facts=[], fact_count=0, warning=None,
  markdown = the text. PASS.

### Docling-error → fallback SUCCEEDS
- Monkeypatched `extract` to return `{"error": "..."}` for a `.html` doc;
  DocumentAdapter parsed it → warning=`"docling failed (simulated docling
  failure); used fallback extractor"`, markdown non-empty (contains "Theker"),
  facts=[], grade=None, pages=None. PASS.

### Docling-error → fallback ALSO fails → clean raise
- Monkeypatched `extract` to error AND fed garbage `garbage.pdf` bytes;
  DocumentAdapter raised `AdapterError`, which propagated cleanly (not
  swallowed). PASS — matches the spec ("If the fallback ALSO raises, return/raise
  a clean error").

## Data-structure / coherency
READ-ONLY. No persistence, no disk writes, no DB / schema / migration changes.
`fetch_document` returns transient in-memory data; the caller owns it. The ONLY
behavioral change is the RESPONSE CONTRACT (see table above).

## Open items for DD-D1
1. **Grep for consumers of `fetch_document`'s output** and confirm the contract
   change is safe:
   - readers of `result["text"]` — now = Docling markdown (was raw text;
     cap changed 500_000 → 100_000). Check `scripts/kf_ingest.py`, the
     `kf-ingest` skill, the frontend, and any MCP-result handlers.
   - readers of the REMOVED `result["truncated"]` key — replaced by
     `markdown_truncated` / `facts_truncated`. Any reader of `["truncated"]`
     will now KeyError / get None.
   - readers of `result["title"]` — now the file stem (was the adapter's
     extracted label); usually equivalent for files but not identical.
2. Decide whether to drop the `text` alias once consumers read `markdown`
   directly; kept for now for safety.
3. New keys consumers may want to surface: `grade`, `pages`, `facts`,
   `fact_count`, `needs_review`, `warning`.
