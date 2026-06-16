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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()  # type: ignore[call-arg]
