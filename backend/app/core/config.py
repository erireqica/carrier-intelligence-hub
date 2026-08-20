from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Carrier Intelligence API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    frontend_origin: AnyHttpUrl = "http://localhost:5173"
    database_url: PostgresDsn = "postgresql+psycopg://localhost:5433/carrier_intelligence_hub"
    test_database_url: PostgresDsn | None = None
    demo_seed_password: SecretStr | None = None
    session_cookie_name: str = "carrier_hub_session"
    session_lifetime_hours: int = 12
    session_cookie_secure: bool = False
    google_oauth_client_id: SecretStr | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_token_encryption_key: SecretStr | None = None
    google_oauth_redirect_uri: AnyHttpUrl = "http://localhost:8000/api/v1/gmail/oauth/callback"
    gmail_poll_interval_seconds: int = Field(default=60, ge=5)
    gmail_initial_lookback_days: int = Field(default=7, ge=1, le=365)
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-terra"
    ai_auto_apply_confidence_threshold: float = Field(default=0.80, ge=0, le=1)
    ai_max_source_chars: int = Field(default=120_000, ge=1_000, le=1_000_000)
    message_process_poll_interval_seconds: int = Field(default=10, ge=5)
    message_process_max_auto_attempts: int = Field(default=3, ge=1, le=10)
    message_process_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    message_process_retry_max_seconds: int = Field(default=600, ge=1, le=86_400)
    message_process_stale_after_seconds: int = Field(default=600, ge=30, le=86_400)
    gmail_label_max_attempts: int = Field(default=4, ge=1, le=10)
    gmail_label_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    gmail_label_retry_max_seconds: int = Field(default=600, ge=1, le=86_400)
    gmail_label_stale_after_seconds: int = Field(default=300, ge=30, le=86_400)
    gmail_label_poll_interval_seconds: int = Field(default=10, ge=5, le=3600)
    pdf_max_attachment_bytes: int = Field(default=10_485_760, ge=1_024)
    pdf_max_pages: int = Field(default=50, ge=1, le=1_000)

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def gmail_oauth_configured(self) -> bool:
        secrets = (
            self.google_oauth_client_id,
            self.google_oauth_client_secret,
            self.google_token_encryption_key,
        )
        return all(
            value is not None and bool(value.get_secret_value().strip()) for value in secrets
        )

    @property
    def openai_configured(self) -> bool:
        return self.openai_api_key is not None and bool(
            self.openai_api_key.get_secret_value().strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
