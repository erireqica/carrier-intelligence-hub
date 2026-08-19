from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, PostgresDsn, SecretStr
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

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
