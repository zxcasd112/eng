import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_requires_explicit_secret_key():
    # Production with default key must fail
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="production",
            app_secret_key="dev-secret-key-change-me-in-production-32chars",
        )
    assert "APP_SECRET_KEY must be explicitly set" in str(exc_info.value)


def test_production_requires_non_empty_secret_key():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="production",
            app_secret_key="",
        )
    assert "APP_SECRET_KEY must be explicitly set" in str(exc_info.value)


def test_production_requires_min_32_chars():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="production",
            app_secret_key="too-short-secret",
        )
    assert "APP_SECRET_KEY must be explicitly set" in str(exc_info.value)


def test_production_succeeds_with_strong_secret():
    settings = Settings(
        app_env="production",
        app_secret_key="this-is-a-strong-custom-production-secret-key-12345",
    )
    assert settings.is_production is True
    assert settings.app_secret_key == "this-is-a-strong-custom-production-secret-key-12345"


def test_development_allows_default_secret():
    settings = Settings(
        app_env="development",
    )
    assert settings.is_production is False
    assert settings.app_secret_key == "dev-secret-key-change-me-in-production-32chars"
