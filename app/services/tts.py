import hashlib
from pathlib import Path

from openai import AsyncOpenAI

from app.config import get_settings


class TTSService:
    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._settings = get_settings()
        self._client = client

    def is_enabled(self) -> bool:
        key = self._settings.openai_api_key.strip()
        return self._settings.enable_tts and bool(key) and not key.startswith("your_")

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key.strip(),
                base_url=self._settings.openai_base_url,
            )
        return self._client

    def _audio_path_for(self, text: str) -> Path:
        self._settings.ensure_dirs()
        key = f"{self._settings.openai_tts_model}:{self._settings.openai_tts_voice}:{text.strip().lower()}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return self._settings.audio_dir / f"{digest}.mp3"

    async def get_or_create_audio(self, text: str) -> Path | None:
        if not self.is_enabled():
            return None

        target = self._audio_path_for(text)
        if target.exists() and target.stat().st_size > 0:
            return target

        client = self._get_client()
        response = await client.audio.speech.create(
            model=self._settings.openai_tts_model,
            voice=self._settings.openai_tts_voice,
            input=text.strip(),
        )
        audio_bytes = response.read()
        target.write_bytes(audio_bytes)
        return target
