from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str

    default_access_class: str = "public"
    max_content_length: int = 500_000
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MB
    web_scrape_timeout: int = 30
    web_scrape_user_agent: str = "KnowledgeForest-Pipeline/0.1"
    # Block scraping URLs that resolve to private/loopback/link-local/reserved
    # IPs (SSRF guard). Set false only for trusted local/dev scraping.
    block_private_urls: bool = True

    max_retries: int = 3
    retry_backoff_base: float = 1.0

    # Browser origins allowed to call the pipeline (CORS). Comma-separated in
    # the env var; defaults to the Vite dev server. Use "*" to allow any.
    cors_origins: str = "http://localhost:5173"

    # Gmail connector (service account with domain-wide delegation).
    # gmail_sa_key_json accepts either the raw service-account JSON string or a
    # path to the key file. gmail_delegated_subject is the Workspace mailbox to
    # impersonate when a request omits an explicit subject.
    gmail_sa_key_json: str | None = None
    # Alternative to gmail_sa_key_json: the same service-account JSON, base64-
    # encoded (handy for single-line .env / secret stores). Takes precedence.
    gmail_sa_key_b64: str | None = None
    gmail_delegated_subject: str | None = None
    # Comma-separated enumeration of mailboxes to sweep in one pull, e.g.
    # "a@nzyme.com,b@nzyme.com". Takes precedence over gmail_delegated_subject
    # when a request omits an explicit subject.
    gmail_delegated_subjects: str | None = None
    gmail_max_results: int = 25
    gmail_scopes: str = "https://www.googleapis.com/auth/gmail.readonly"
    # Optional mailbox auto-discovery: when a firm entry declares a `domain`
    # instead of an explicit `mailboxes` list, the connector enumerates that
    # Workspace's users via the Admin Directory API. The directory scope must be
    # DWD-authorized on the same client ID, and the call impersonates an admin
    # (`admin_subject` on the firm, else this global default).
    gmail_directory_scope: str = (
        "https://www.googleapis.com/auth/admin.directory.user.readonly"
    )
    gmail_admin_subject: str | None = None
    gmail_directory_query: str | None = None
    # Multi-tenant connector config. JSON array of per-firm objects, each:
    #   {"tenant_id": "<uuid>",
    #    "mailboxes": ["a@firm.com", ...]   # explicit list, OR
    #    "domain": "firm.com",              # auto-discover via Directory API
    #    "admin_subject": "admin@firm.com"? # admin to impersonate for discovery
    #    "sa_key_b64": "<base64 SA JSON>"?  # else falls back to the global SA
    #    "scopes": "<space-separated>"?}
    # Each entry needs either mailboxes or a domain. One shared SA typically
    # serves every tenant (DWD-authorized per Workspace). SA keys stay in
    # env/secret, never the DB.
    gmail_firms: str | None = None
    # First-run backfill window (days) for recurrent per-mailbox sync.
    gmail_backfill_days: int = 7
    # Drop threads whose only sender is a no-reply/alert address (keeps automated
    # newsletters out of the graph and off the embedding bill). Set False to
    # ingest everything regardless of sender.
    gmail_skip_noise_senders: bool = True

    # Notes connector (multi-tenant; reads meeting notes from a *source* Supabase
    # project over a direct Postgres connection using a least-privilege read-only
    # role). JSON array, one object per firm, each:
    #   {"tenant_id": "<uuid>", "source_dsn": "postgresql://forest_notes_reader…",
    #    "table": "meeting_transcripts"?, "content_fields": ["notion_summary"]?,
    #    "confidential_field": "confidential"?,
    #    "owner_map_tables": [{"table": "...", "name_col": "...", "email_col": "..."}]?}
    # The DSN (with the role password) is the only source credential; it lives in
    # env/secret, never the DB. Mirrors the GMAIL_FIRMS posture.
    notes_firms: str | None = None
    # Single-firm convenience: a bare DSN used when notes_firms is unset. Must be
    # paired with a tenant_id on the request (or notes_default_tenant_id).
    notes_source_dsn: str | None = None
    notes_default_tenant_id: str | None = None
    # Per-pull cap on meeting rows fetched from one firm.
    notes_max_results: int = 200

    # Affinidad connector (Kibo's single-tenant in-house CRM). Reads the CRM's
    # Supabase Postgres directly over a least-privilege read-only role, same
    # posture as the Notes connector. Affinidad has no tenant_id of its own, so a
    # firm here is just {tenant_id (assigned on the memory side), source_dsn}.
    # JSON array form for future multi-firm use:
    #   [{"tenant_id": "<uuid>", "source_dsn": "postgresql://forest_crm_reader…"}]
    affinidad_firms: str | None = None
    # Single-firm convenience (the normal case): a bare DSN + the tenant to attach.
    affinidad_source_dsn: str | None = None
    affinidad_default_tenant_id: str | None = None
    # Per-pull cap on rows fetched from the large `events` table during backfill.
    affinidad_max_results: int = 50_000
    # Max in-flight edge-function calls per object stage (backfill throughput).
    # Safe because canonical-key dedup is a transactional upsert.
    affinidad_concurrency: int = 8

    # Notion connector (internal integration token; Bearer auth).
    # notion_api_key is the internal integration secret. Scope is controlled by
    # what's shared with the integration in Notion, not by code.
    notion_api_key: str | None = None
    notion_version: str = "2022-06-28"
    notion_max_results: int = 100
    # Cap on Markdown pages pulled from a single workspace-export ZIP import.
    notion_export_max_files: int = 5000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # The pipeline shares .env with the frontend (VITE_* vars etc.); ignore
        # any keys this Settings model doesn't define instead of erroring.
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
