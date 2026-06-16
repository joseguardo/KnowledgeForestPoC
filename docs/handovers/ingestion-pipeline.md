# Ingestion Pipeline Handover

## What was built

A **Python FastAPI service** (`pipeline/`) that acts as a universal intake for heterogeneous data sources. It normalizes input into the schema expected by the existing Supabase Edge Functions and routes to the correct function. It does **not** bypass edge functions — all writes flow through the existing dedup + embedding + RLS path.

**Phase scope**: Structured routing layer only. No LLM extraction (future stage).

```
  Source → Adapter → NormalizedItem → Router → Edge Function
                                                ├── insert-pointer   (single entity)
                                                ├── ingest-document  (text/document)
                                                └── ingest-batch     (2-50 entities)
```

### Why this exists

The existing write path is three edge functions (`insert-pointer`, `ingest-document`, `ingest-batch`) that each expect a specific JSON shape. There was no unified way to ingest from conversations, file uploads, web pages, or bulk API data without the caller knowing the exact edge function contract. This service absorbs that complexity: callers describe *what* they have (a PDF, a URL, a CRM export, a chat transcript), and the pipeline figures out *how* to get it into the knowledge graph.

---

## Architecture

```
                        ┌──────────────────────────────┐
                        │   FastAPI Service (Python)    │
                        │        localhost:8000         │
                        └──────────┬───────────────────┘
                                   │
         ┌────────────┬────────────┼────────────┬──────────────┐
         ▼            ▼            ▼            ▼              │
   POST /ingest/  POST /ingest/ POST /ingest/ POST /ingest/   │
   conversation   document      structured    web              │
         │            │            │            │              │
         ▼            ▼            ▼            ▼              │
   ┌──────────────────────────────────────────────┐           │
   │              Source Adapters                   │           │
   │  conversation.py | document.py | structured.py│           │
   │  web.py                                       │           │
   └──────────────────┬───────────────────────────┘           │
                      │                                        │
                      ▼ list[NormalizedItem]                   │
   ┌──────────────────────────────────────────────┐           │
   │                  Router                       │           │
   │  kind="document" → ingest-document            │           │
   │  kind="pointer" (1) → insert-pointer          │           │
   │  kind="pointer" (2-50) → ingest-batch         │           │
   │  kind="pointer" (>50) → chunked ingest-batch  │           │
   └──────────────────┬───────────────────────────┘           │
                      │ HTTP POST                              │
                      ▼                                        │
   ┌──────────────────────────────────────────────┐           │
   │       Supabase Edge Functions (unchanged)     │           │
   │  insert-pointer | ingest-document | ingest-batch          │
   └──────────────────────────────────────────────┘
```

---

## What was added

### New directory: `pipeline/` (27 files, ~2,400 lines)

No existing files were modified. The entire pipeline is additive.

#### Core modules

| File | Lines | Purpose |
|------|-------|---------|
| `pipeline/config.py` | 22 | `pydantic-settings` config — reads `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, retry params from `.env` |
| `pipeline/models.py` | 124 | All Pydantic models: `NormalizedItem` (intermediate format), request models per endpoint, `IngestResponse` envelope, `EdgeFunctionResult`, `IngestError` |
| `pipeline/errors.py` | 26 | Exception hierarchy: `ValidationError`, `AdapterError`, `EdgeFunctionError`, `EdgeFunctionTimeout` |
| `pipeline/client.py` | 134 | Async HTTP client for edge functions. Three methods (`insert_pointer`, `ingest_document`, `ingest_batch`) matching exact edge function contracts. Exponential backoff retry on 5xx (1s, 2s, 4s). No retry on 4xx. Auth via `Authorization: Bearer {service_role_key}` |
| `pipeline/router.py` | 122 | Takes `list[NormalizedItem]`, separates by `kind`, dispatches: documents → individual `ingest-document` calls, single pointer → `insert-pointer`, 2+ pointers → `ingest-batch` (auto-chunked at 50). Sequential execution preserves cross-item dedup ordering |
| `pipeline/main.py` | 73 | FastAPI app factory. Lifespan creates shared `httpx.AsyncClient` + `EdgeFunctionClient`. Registers exception handlers that map pipeline errors to HTTP 422/502/504. Mounts `/api/v1/ingest/` router and `/api/v1/health` |

#### Adapters

| File | Lines | What it does |
|------|-------|-------------|
| `pipeline/adapters/base.py` | 12 | Abstract base class with `process() → list[NormalizedItem]` contract |
| `pipeline/adapters/structured.py` | 33 | Maps JSON entity arrays to pointer-type `NormalizedItem`s. Validates `type` against all 16 `pointer_type` enum values. Applies access class fallback (item-level overrides request-level) |
| `pipeline/adapters/document.py` | 141 | Two entry points: `process_text()` for JSON body, `process_file()` for uploads. PDF extraction via PyMuPDF (`fitz`). Email parsing via stdlib `email.parser` (subject→title, body→content, date→occurred_at, HTML fallback via BeautifulSoup). Markdown title from first `#` heading. Validates content non-empty and ≤500K chars (matches `ingest-document` limit) |
| `pipeline/adapters/conversation.py` | 34 | Wraps entire transcript as a single document-type `NormalizedItem`. Derives title from first non-empty line. Adds `participants` and `source` to metadata |
| `pipeline/adapters/web.py` | 90 | Fetches URL via `httpx` (30s timeout). BeautifulSoup extracts title from `<title>`/`<h1>`, content from `<article>`/`<main>`/`<body>`. Strips `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<aside>`. Stores `source_url` in metadata. Truncates to 500K chars |

#### API routes

| File | Lines | Endpoints |
|------|-------|-----------|
| `pipeline/api/ingest.py` | 141 | `POST /structured` — JSON body, `POST /document` — multipart file upload or form fields, `POST /document/json` — JSON body (no file), `POST /conversation` — JSON body, `POST /web` — JSON body with URL |

All endpoints return a consistent `IngestResponse` envelope:
```json
{
  "source_type": "structured",
  "items_produced": 3,
  "results": [{"index": 0, "status": "created", "pointer_id": "..."}],
  "errors": [],
  "duration_ms": 42
}
```

#### Configuration

| File | Lines | Purpose |
|------|-------|---------|
| `pyproject.toml` | 37 | PEP 621 project metadata. Dependencies: fastapi, uvicorn, pydantic, pydantic-settings, httpx, pymupdf, beautifulsoup4, python-multipart. Dev: pytest, pytest-asyncio, ruff |
| `.env.example` | 3 | Template: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DEFAULT_ACCESS_CLASS` |

#### Tests (84 total, all passing)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_adapters/test_structured.py` | 7 | Single item, multiple items, attributes passthrough, invalid type rejection, access class fallback/override |
| `tests/test_adapters/test_document.py` | 7 | Text content, title derivation, empty/missing content rejection, markdown title extraction, txt file, empty file |
| `tests/test_adapters/test_conversation.py` | 4 | Basic transcript, explicit title, participants in metadata, empty line skipping |
| `tests/test_adapters/test_web.py` | 6 | HTML extraction (article, body fallback, h1 title, script stripping), full adapter with mock transport, non-HTML rejection |
| `tests/test_client.py` | 6 | Success paths, 4xx not retried, 5xx retried then succeeds, retries exhausted, auth header verification |
| `tests/test_router.py` | 7 | Single pointer → insert-pointer, multiple → ingest-batch, document → ingest-document, mixed items, attributes passthrough, link passthrough, >50 items chunked |
| `tests/test_stress.py` | 48 | **14 structured** (all pointer types, unicode, nested metadata, 50-item batch, validation failures), **11 document/json** (100K doc, markdown memo, link, chunk_size, unicode, special chars), **7 conversation** (IC meeting, agent chat, Slack thread, 100-turn long), **7 web** (article, nav/footer stripping, JS-heavy, large page, minimal HTML), **5 file upload** (txt, md, form fields, 50K upload), **4 response structure** (envelope shape, duration, pointer_id, health) |

All tests use mocked edge function responses (no live Supabase calls). Mock is configured in `tests/conftest.py` via `AsyncMock(spec=EdgeFunctionClient)`.

### New file at repo root: `Makefile`

| Command | Action |
|---------|--------|
| `make dev` | Starts both frontend (`:5173`) and backend (`:8000`) in parallel; Ctrl+C kills both |
| `make frontend` | Vite dev server only |
| `make backend` | FastAPI pipeline only |
| `make install` | Install all deps (npm + python venv) |
| `make test` | Run pipeline pytest suite |
| `make lint` | Ruff lint |
| `make clean` | Remove build artifacts |
| `make help` | Show all commands |

---

## Key design decisions

1. **Route through edge functions, not direct DB writes.** The pipeline calls edge functions via HTTP. This preserves all existing dedup logic (`insert_pointer_with_dedup`), embedding generation (OpenAI), and RLS enforcement. The pipeline never touches the database directly.

2. **NormalizedItem as lingua franca.** Every adapter produces `NormalizedItem(kind="pointer"|"document")`. The router consumes these without knowing which adapter produced them. Adding a new source type means writing one adapter — router and client are untouched.

3. **Automatic batching.** The router uses `insert-pointer` for single entities and `ingest-batch` for 2+, auto-chunking at 50 (the edge function limit). Callers don't need to know about batch limits.

4. **Sequential processing.** Both document and batch dispatch are sequential, not parallel. For documents, each gets a unique SHA256 hash; for batches, sequential execution preserves cross-item dedup (item N deduplicates against items 0..N-1).

5. **Retry on 5xx only.** The client retries edge function 5xx errors with exponential backoff (max 3 attempts). 4xx errors are not retried — they indicate bad input that won't fix itself.

6. **Partial failure reporting.** If item 3 of 5 fails, items 1-2 are already committed. The response includes both `results` (successful) and `errors` (failed) arrays with original indices for traceability.

7. **No LLM in this phase.** The pipeline is a structural routing layer. Conversation transcripts become documents (not extracted entities). LLM-driven entity/relationship extraction is a planned future stage that would add a processing step between adapter and router.

---

## Existing code: zero modifications

No existing files were changed. The pipeline is entirely additive:
- No changes to edge functions (`insert-pointer`, `ingest-document`, `ingest-batch`)
- No changes to database schema or migrations
- No changes to frontend code
- No changes to `package.json` or any existing config

The `Makefile` at repo root is new (the project had no Makefile before).

---

## How to verify

### 1. Tests pass
```bash
cd pipeline
source .venv/bin/activate
python -m pytest tests/ -v
# Expected: 84 passed in ~1.3s
```

### 2. Service starts
```bash
# Requires .env with valid SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
cd pipeline
source .venv/bin/activate
uvicorn pipeline.main:app --reload --port 8000
# Or from repo root:
make backend
```

### 3. Health check
```bash
curl http://localhost:8000/api/v1/health
# Expected: {"status":"ok","supabase_url":"https://rkuyvzcxaoulhjiflrmp.supabase.co"}
```

### 4. Structured ingestion (requires live Supabase)
```bash
curl -X POST http://localhost:8000/api/v1/ingest/structured \
  -H "Content-Type: application/json" \
  -d '{"items": [{"label": "Test Company", "type": "company", "canonical_key": "test-co"}]}'
# Expected: {"source_type":"structured","items_produced":1,"results":[{"index":0,"status":"created","pointer_id":"..."}],"errors":[],"duration_ms":...}
```

### 5. Document ingestion (requires live Supabase)
```bash
curl -X POST http://localhost:8000/api/v1/ingest/document/json \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Document", "content": "This is a test document with enough content to verify ingestion works correctly."}'
# Expected: status "created", pointer_id present
```

### 6. Conversation ingestion (requires live Supabase)
```bash
curl -X POST http://localhost:8000/api/v1/ingest/conversation \
  -H "Content-Type: application/json" \
  -d '{"content": "User: What is the status?\nAgent: Everything is on track.", "source": "test"}'
# Expected: status "created" (ingested as document type)
```

### 7. Web ingestion (requires live Supabase + internet)
```bash
curl -X POST http://localhost:8000/api/v1/ingest/web \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
# Expected: status "created", scraped content from example.com
```

### 8. File upload (requires live Supabase)
```bash
echo "# Test Markdown\n\nThis is a test file." > /tmp/test.md
curl -X POST http://localhost:8000/api/v1/ingest/document \
  -F "file=@/tmp/test.md"
# Expected: status "created", title "Test Markdown"
```

### 9. Makefile works
```bash
make help
# Expected: 10 commands listed with descriptions
```

### 10. Verify in Supabase after live tests
```sql
-- Check that test entities appeared
SELECT id, label, type, created_at
FROM pointers
WHERE label IN ('Test Company', 'Test Document')
ORDER BY created_at DESC;
```

---

## Files to review

| File | What to check |
|------|---------------|
| `pipeline/models.py` | `NormalizedItem` shape matches edge function contracts; response models cover all fields |
| `pipeline/client.py` | Auth header uses service role key; retry logic only on 5xx; timeout handling |
| `pipeline/router.py` | Routing logic: kind="document" → ingest-document, kind="pointer" single → insert-pointer, multiple → ingest-batch; batch chunking at 50; index mapping for batch results |
| `pipeline/adapters/document.py` | PDF extraction via PyMuPDF; email parsing via stdlib; content length validation matches 500K limit; empty content rejection |
| `pipeline/adapters/web.py` | Script/style/nav stripping; content extraction hierarchy (article → main → body); content-type validation |
| `pipeline/adapters/structured.py` | Pointer type validation against all 16 enum values; access class fallback chain |
| `pipeline/api/ingest.py` | File upload handling (multipart vs JSON); form field → LinkSpec construction; web endpoint passes `app.state.http` |
| `pipeline/main.py` | Lifespan manages httpx client lifecycle; exception handlers map to correct HTTP status codes |
| `pipeline/config.py` | `settings` instantiation at module level — will fail fast if env vars missing |
| `tests/test_stress.py` | 48 scenarios covering all endpoints with diverse data (unicode, large payloads, edge cases, validation failures) |
| `tests/conftest.py` | Mock client returns realistic edge function responses; `app.state.http` set for web tests |
| `Makefile` | `make dev` trap kills both processes on Ctrl+C; backend activates venv correctly |

---

## Known issues and limitations

1. **No auth on the pipeline API itself.** The service authenticates *to* Supabase with the service role key, but does not authenticate incoming requests. For local/dev use only. Production would need API key or JWT middleware.

2. **Scanned PDFs extract no text.** PyMuPDF extracts text layers only. Image-only PDFs return an `AdapterError`. OCR (e.g., Tesseract) is a future extension.

3. **Web scraping is HTTP-only.** JavaScript-rendered content (SPAs) returns empty or partial content. Playwright/Selenium is a future extension.

4. **No rate limiting.** Bulk ingestion of hundreds of items could hit Supabase Edge Function rate limits. The sequential processing model and retry backoff help, but there's no explicit throttling.

5. **Conversations are ingested as documents, not decomposed.** Without LLM extraction, a meeting transcript becomes a single searchable document. Entity extraction (people, companies, decisions mentioned) is planned for the next phase.

6. **Email attachment handling is skipped.** `.eml` files extract subject + body only. Attachments (PDFs inside emails, etc.) are ignored in this phase.

7. **The `.venv/` directory is inside `pipeline/`.** It should be in `.gitignore`. Currently untracked by git, but could accidentally be committed.
