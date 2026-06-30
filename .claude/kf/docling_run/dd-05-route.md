# Due-Diligence Verification 05 — fetch_document routing (agent DD-D1)

Status: **PASS**

This report verifies agent D1's implementation of `fetch_document` routing through Docling `extract()` with capped return shapes. All security guards remain intact. No persistence changes. Consumer grep confirms the `text` alias is safe to keep.

---

## Check 1: Syntax / Lint / Registration

- **py_compile**: `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/mcp_server/tools/fetch_document.py` → `PY_COMPILE_OK`
- **ruff check**: All checks passed!
- **Tool registration**: `fetch_document in mcp.list_tools()` → `True`

**VERDICT: PASS**

---

## Check 2: Guards UNCHANGED (Critical)

All four guards are present and unchanged:

### Guard (a) — Caller + Kibo-tenant gate
```python
ctx = caller()
if KIBO_TENANT not in resolve_tenants(ctx.email):
    raise NotAuthenticated("fetch_document is restricted to Kibo tenant members.")
```
(lines 90-92, unchanged)

### Guard (b) — Drive allowlist
```python
if drive_id != settings.sharepoint_portfolio_drive_id:
    raise PermissionError("drive_id is not the Portfolio drive.")
```
(lines 95-96, unchanged)

### Guard (c) — Folder reject + portfolio-path assertion
```python
if item.get("folder") is not None:
    raise ValueError("item is a folder, not a document.")
sp_path = _portfolio_path(item)
```
(lines 101-103, `_portfolio_path()` untouched, unchanged)

### Guard (d) — Size check
```python
if size > settings.max_upload_bytes:
    raise ValueError(
        f"document is {size:,} bytes, over the {settings.max_upload_bytes:,}-byte limit."
    )
```
(lines 106-109, unchanged)

**Note**: Both SharePoint calls remain via `asyncio.to_thread`:
- Line 100: `await asyncio.to_thread(client._get_item_by_id, drive_id, item_id)`
- Line 111: `await asyncio.to_thread(client._download_file, drive_id, item_id)`

**VERDICT: PASS — All guards intact, no weakening.**

---

## Check 3: Branching Correctness

Extension-based routing (lines 116-146):

**Docling formats** (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.xlsm`, `.html`, `.htm`):
- Line 126: `result = await extract(item["name"], data, minimum_grade=settings.docling_min_grade)`
- Line 127: `if "error" in result:` (error branched **FIRST**, correct)
- Lines 127-133: On error → fall back to `DocumentAdapter`, set `warning`, read `markdown` only
- Lines 134-141: On success → read all keys: `markdown`, `facts`, `fact_count`, `grade`, `pages`, `needs_review`, `warning`

**Non-Docling formats** (text/email/other, lines 142-146):
- `DocumentAdapter().process_file(...)` → markdown only, `facts=[]`, `fact_count=0`, `grade=None`, `pages=None`, `needs_review=False`, `warning=None`

**Extract await**: Line 126 uses `await extract(...)` directly — **NOT** wrapped in `asyncio.to_thread` (correct; extract already offloads internally per handover-04).

**VERDICT: PASS — Branching correct, error check first, extract awaited directly.**

---

## Check 4: Caps Applied Correctly

Lines 148-156:

```python
# MPC inline caps (owned here, not by extract()).
md = markdown or ""
markdown_truncated = len(md) > settings.docling_markdown_inline_cap
if markdown_truncated:
    md = md[: settings.docling_markdown_inline_cap]

facts_full = facts or []
facts_truncated = len(facts_full) > settings.docling_facts_inline_cap
facts = facts_full[: settings.docling_facts_inline_cap]
```

**Critical**: `fact_count` is the FULL pre-cap count from `extract()`:
- Line 137: `fact_count = result["fact_count"]` (full count, before capping)
- Line 169: returns `fact_count` unchanged (NOT `len(facts)` after capping)

This is **correct**. The fact_count preserved full pre-cap count, while `facts` list is capped.

**VERDICT: PASS — Caps applied, full fact_count preserved, markdown_truncated and facts_truncated flags set correctly.**

---

## Check 5: Response Contract (15 Keys, Exact)

Lines 158-176 return a dict with exactly these keys (verified in smoke test):

| key | type | present |
|-----|------|---------|
| `name` | str | ✓ |
| `title` | str | ✓ |
| `sp_path` | str | ✓ |
| `web_url` | str | ✓ |
| `size` | int | ✓ |
| `grade` | str \| None | ✓ |
| `pages` | int \| None | ✓ |
| `markdown` | str | ✓ |
| `markdown_truncated` | bool | ✓ |
| `facts` | list[dict] | ✓ |
| `fact_count` | int | ✓ |
| `facts_truncated` | bool | ✓ |
| `needs_review` | bool | ✓ |
| `warning` | str \| None | ✓ |
| `text` | str | ✓ (deprecated alias) |

**VERDICT: PASS — All 15 keys present, types correct, `text == markdown` alias in place.**

---

## Check 6: Consumer Grep (Data-Coherency Task)

### Grep Results

Searched the entire repo (excluding `.venv`, `node_modules`, `.git`) for:
- `fetch_document` calls
- readers of `result["text"]` / `result["markdown"]` / `result["facts"]` / `result["fact_count"]` / `result["truncated"]`

**Findings**:

1. **No external consumers of fetch_document results found**. All grep hits are:
   - Config comments about the tool (e.g., `pipeline/config.py` lines 186–200)
   - The tool definition itself (`fetch_document.py` lines 135–141 where it reads from `extract()`)
   - MCP server setup code
   - Test infrastructure

2. **No readers of the old `truncated` key**: Zero matches for `\.truncated` or `"truncated"` anywhere in the codebase (except version control).

3. **No direct consumers of `result["text"]`** outside the tool. The tool constructs the response; external callers (Claude Desktop, MCP clients) will receive JSON and can read any key.

### Conclusion

The `text` alias is **SAFE TO KEEP** because:
- No internal Python/TypeScript code reads `result["text"]` (verified grep above)
- The tool is consumed externally via MCP (Claude Desktop, external clients) where the response shape is free-form JSON; the `text` key does not break any internal contract
- **Recommendation**: Keep the `text` alias. It is zero-cost (one extra key in the dict), and it is a safe migration path for any external clients. The deprecation comment is clear.

**VERDICT: PASS — No consumer breakage, text alias is safe and recommended to keep.**

---

## Check 7: Real Smoke Test

Tested with `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/downloads/Theker_SeriesA_v7.xlsx` (463,579 bytes):

```
✓ Extract OK: markdown=191896 chars, fact_count=4841, facts=4841, grade=UNSPECIFIED, warning=None
✓ Caps applied correctly:
  - markdown_truncated: True (len=100000, cap=100000)
  - facts_truncated: True (len=200, cap=200, full_count=4841)
✓ Xlsx facts capping verified: 4841 total, 200 returned
✓ PASS: All checks passed
```

**Assertions verified**:
- `extract()` returns success dict with no error
- Markdown is non-empty (191896 chars) and correctly capped to 100000
- `fact_count` is full pre-cap value (4841), not len(facts) (200)
- `facts_truncated=True` because 4841 > 200 cap
- Response dict has exactly 15 keys, all correct types
- `text == markdown` (capped)

**VERDICT: PASS — Real extraction, capping, and response contract verified.**

---

## Check 8: Data-Structure / Coherency

**Persistence**: None. The function is read-only from the database (SharePoint access only) and returns transient in-memory data. No writes to pointers, edges, agent_tasks, or any table.

**Schema / Migration**: No changes. The response is pure in-memory JSON.

**Contract change noted**: 
- **Old**: `text` was raw extracted text (cap 500_000), `truncated` was a single bool
- **New**: `text` is Docling markdown (cap 100_000), split into `markdown_truncated` and `facts_truncated`

No internal code reads the removed `truncated` key (verified grep above), so this is safe.

**VERDICT: PASS — Read-only, no persistence, no schema changes.**

---

## Summary

| Check | Result | Notes |
|-------|--------|-------|
| 1. Syntax/Lint/Registration | PASS | py_compile OK, ruff OK, fetch_document registered |
| 2. Guards UNCHANGED | PASS | All 4 guards present, verbatim unchanged, SharePoint calls still via to_thread |
| 3. Branching Correctness | PASS | Error check first, extract awaited directly (not to_thread), fallback logic correct |
| 4. Caps Applied | PASS | fact_count full pre-cap, facts capped, markdown_truncated and facts_truncated set |
| 5. Response Contract | PASS | 15 keys exactly, all types correct, text alias in place |
| 6. Consumer Grep | PASS | No external consumers, no readers of old truncated key, text alias safe |
| 7. Smoke Test | PASS | Real xlsx extraction, capping, and 15-key contract verified |
| 8. Data-Structure | PASS | Read-only, no persistence, no schema changes |

---

## FINAL VERDICT: **PASS**

Agent D1 has successfully routed `fetch_document` through Docling `extract()` with capped return shapes. All security guards remain intact and unchanged. No persistence or schema changes. The `text` alias is safe and recommended for backward compatibility.

No blockers for E1 (final DD).

---

**Generated**: 2026-06-30 | DD-D1 verification via automated smoke test + comprehensive grep
