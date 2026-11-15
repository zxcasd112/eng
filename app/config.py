from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "ENG Tutor"
    app_env: str = "development"
    app_secret_key: str = "dev-secret-key-change-me-in-production-32chars"
    data_dir: Path = Path("data")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.is_production:
            insecure_defaults = {
                "dev-secret-key-change-me-in-production-32chars",
                "change-this-secret-in-production-min-32-chars",
            }
            if (
                not self.app_secret_key
                or self.app_secret_key in insecure_defaults
                or len(self.app_secret_key) < 32
            ):
                raise ValueError(
                    "In production (APP_ENV=production), APP_SECRET_KEY must be explicitly set, "
                    "cannot use the default dev secret, and must be at least 32 characters long."
                )
        return self

    # CORS
    cors_origins: str = (
        "http://localhost:8000,http://127.0.0.1:8000,"
        "http://localhost:3000,http://127.0.0.1:3000,"
        "https://eng-tutor.onrender.com,https://eng-tutor-omuc.onrender.com"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Database (PostgreSQL asyncpg or SQLite aiosqlite)
    database_url: str = "sqlite+aiosqlite:///./data/eng.db"

    # Telegram Bot & Login Widget
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""

    # OpenAI-compatible LLM & TTS
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    enable_tts: bool = True

    # Reminders / Scheduler
    review_reminder_enabled: bool = True
    default_reminder_hour: int = 19

    # Recommendations Weights
    rec_weight_source: float = 3.0
    rec_weight_cefr: float = 2.5
    rec_weight_frequency: float = 2.0
    rec_weight_unreviewed: float = 1.5

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
