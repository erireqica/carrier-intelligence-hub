from app.core.config import Settings


def test_settings_can_be_overridden_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "Test Carrier API")
    monkeypatch.setenv("API_V1_PREFIX", "/test/v1")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Test Carrier API"
    assert settings.api_v1_prefix == "/test/v1"
    assert settings.database_url.scheme == "postgresql+psycopg"
