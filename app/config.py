from functools import lru_cache
from pathlib import Path

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
