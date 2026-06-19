# Gmail Connector for the Memory Layer

## Context

The KnowledgeForest memory layer ingests heterogeneous sources through a Python
FastAPI pipeline (`/pipeline`) whose adapters normalize input into
`NormalizedItem`s and route them to Supabase edge functions
(`insert-pointer` / `ingest-document` / `ingest-batch`). Today there are
adapters for structured data, documents/files, conversations, and web pages —
but **no connectors to live data sources**.

This is the first source connector: **Gmail**, so emails become first-class
documents in the global graph (searchable, embedded, deduplicated, and
eventually surfaced in the tenant forest).

**Decisions locked with the user:**
- **Auth:** Google **service account with domain-wide delegation (DWD)** — the
  pipeline impersonates a Workspace mailbox (e.g. `niklas@kiboventures.com`)
  with `gmail.readonly`. No per-user OAuth consent, no token storage.
- **Sync mode:** **one-time manual pull** — an endpoint called with a Gmail
  search query + max results. Scheduling/push are explicit follow-ups.
- **Granularity:** **per thread** — each Gmail thread becomes one document.

## Approach

Add a `GmailAdapter` that mirrors the existing `WebAdapter`: async, takes the
shared `httpx.AsyncClient` from `app.state.http`, and emits
`NormalizedItem(kind="document")` — one per thread. It routes through the
**existing** `route()` → `ingest-document` path with **no changes** to the
router or edge functions.

Token minting uses `google-auth`'s service-account credentials with
`.with_subject(subject)` for DWD; the (synchronous) `.refresh()` is wrapped in
`asyncio.to_thread` so the event loop isn't blocked. All Gmail data fetches use
the shared async httpx client against the Gmail REST API directly (no heavy
`google-api-python-client` dependency).

**Dedup behavior (important, by design):** `ingest-document` sets
`canonical_key = "doc:" + sha256(content)` and ignores any caller-supplied key
(`supabase/functions/ingest-document/index.ts:135`). So re-running a pull over
an unchanged thread → `merged` (no-op). A thread that gained a new reply has
different content → a new document version. The Gmail thread ID lives in
`metadata` for traceability, not as the identity key. This is acceptable for the
PoC and noted as a known limitation.

## Files to change

**`pipeline/pyproject.toml`** — add dependency `google-auth[requests]>=2.0`. The
Gmail REST calls go over the existing `httpx` (so no `google-api-python-client`),
but service-account token minting uses `google.auth.transport.requests`, which
requires the `requests` extra — without it `_mint_token` raises ImportError.

**`pipeline/pipeline/config.py`** — add settings:
- `gmail_sa_key_json: str | None = None` — service-account JSON (raw JSON
  string or a path to the key file; the adapter accepts either).
- `gmail_delegated_subject: str | None = None` — default mailbox to impersonate
  when the request omits `subject`.
- `gmail_max_results: int = 25` — default cap.
- `gmail_scopes: str = "https://www.googleapis.com/auth/gmail.readonly"`.

**`pipeline/pipeline/models.py`** — add:
```python
class GmailRequest(BaseModel):
    subject: str | None = None      # mailbox to impersonate; falls back to settings
    query: str | None = None        # Gmail search syntax, e.g. "from:x after:2026/01/01"
    max_results: int | None = None  # falls back to settings.gmail_max_results
    access_class: str | None = None
    link: LinkSpec | None = None
```

**`pipeline/pipeline/adapters/gmail.py`** (new) — `GmailAdapter`:
- `async def process(self, request: GmailRequest, http: httpx.AsyncClient) -> list[NormalizedItem]`
- Resolve `subject` (request → settings); raise `ValidationError` if neither set
  or if `gmail_sa_key_json` is unconfigured.
- `_mint_token(subject)`: build
  `google.oauth2.service_account.Credentials.from_service_account_info(...)`
  (or `_file` if a path), `.with_subject(subject)`, `.with_scopes([...])`,
  then `await asyncio.to_thread(creds.refresh, Request())` and return
  `creds.token`.
- `GET https://gmail.googleapis.com/gmail/v1/users/me/threads?q={query}&maxResults={n}`
  (Bearer token) → list of thread IDs (single page for the PoC; `nextPageToken`
  noted as a follow-up).
- For each thread: `GET .../threads/{id}?format=minimal` to enumerate message
  IDs, then `GET .../messages/{id}?format=raw` per message (raw is only valid on
  messages.get, not threads.get). Decode `message.raw` (base64url → bytes) and
  **reuse `_extract_email` from `pipeline/pipeline/adapters/document.py`** to get
  `(subject, body, date)`.
- Build one combined document: messages in order, each prefixed with a small
  `From / Date / Subject` header block, joined by separators.
- `label` = first message's subject (strip a leading `Re:`/`Fwd:`); fall back to
  thread snippet. `occurred_at` = latest message date. `metadata` =
  `{gmail_thread_id, mailbox, message_count, participants}`. `source = "gmail"`.
- Validate combined content via the existing `_validate_content` helper.

**`pipeline/pipeline/api/ingest.py`** — add endpoint mirroring `/web`:
```python
@router.post("/gmail", response_model=IngestResponse)
async def ingest_gmail(body: GmailRequest, request: Request) -> IngestResponse:
    adapter = GmailAdapter()
    items = await adapter.process(body, http=request.app.state.http)
    results, errors = await route(items, request.app.state.client)
    # ... same envelope, source_type="gmail"
```

**`pipeline/.env.example`** — document `GMAIL_SA_KEY_JSON`,
`GMAIL_DELEGATED_SUBJECT`, `GMAIL_MAX_RESULTS`.

**`pipeline/tests/test_adapters/test_gmail.py`** (new) — mock token minting
(monkeypatch `_mint_token`) and Gmail REST responses (httpx mock / monkeypatch,
following `conftest.py` patterns). Fixtures: raw RFC822 messages for a
two-message thread. Assert: one document produced, title strips `Re:`,
participants collected, combined body contains both messages, `occurred_at` is
the latest. Add an error-path test (no subject configured → `ValidationError`).

## One-time external setup (operator, outside the codebase)

1. Google Cloud: create/choose a project, **enable the Gmail API**, create a
   **service account**, generate a **JSON key**.
2. Note the service account's numeric **client ID**.
3. Google **Workspace Admin** (`admin.google.com` → Security → API Controls →
   Domain-wide Delegation): authorize that client ID for scope
   `https://www.googleapis.com/auth/gmail.readonly`. *(Requires super-admin.)*
4. Put the key JSON into `GMAIL_SA_KEY_JSON` (or a file path) and set
   `GMAIL_DELEGATED_SUBJECT` in `pipeline/.env`. Keep the key out of git.

## Verification

1. **Unit tests:** `make test` (or `pytest pipeline/tests/test_adapters/test_gmail.py`)
   — all green, no network calls (mocked).
2. **Lint:** `make lint` (ruff).
3. **End-to-end (after external setup + real `.env`):**
   - `make dev`, then
     `curl -X POST localhost:8000/api/v1/ingest/gmail -H 'content-type: application/json' -d '{"query":"newer_than:7d","max_results":3}'`
   - Expect `IngestResponse` with `source_type:"gmail"`, `items_produced` = #
     threads, and `results[].status` of `created`.
   - Re-run the same call → statuses become `merged` (dedup confirmed).
   - Confirm rows: query Supabase `pointers` (type `document`, `metadata`
     contains `gmail_thread_id`) and that `document_chunks` exist; optionally
     search via the frontend `SearchPanel`.

## Known limitations / explicit follow-ups (out of scope)

- Single page of threads (no `nextPageToken` pagination yet).
- No incremental sync cursor and no scheduling/push (Pub/Sub) — manual pull only.
- Attachments are not extracted (could later route email attachments through
  `DocumentAdapter`/PyMuPDF).
- New reply to a thread creates a new document version rather than updating the
  existing one (content-hash identity).
