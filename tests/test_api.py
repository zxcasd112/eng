import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.services.llm import LLMService


def _sign_telegram_payload(payload: dict, bot_token: str) -> dict:
    signed = dict(payload)
    items = [f"{k}={v}" for k, v in sorted(signed.items()) if v is not None]
    check_str = "\n".join(items)
    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    signed["hash"] = hmac.new(secret, check_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return signed


class _FakeCompletions:
    async def create(self, **_kwargs):
        data = {
            "lemma": "ubiquitous",
            "transcription": "/juːˈbɪk.wɪ.təs/",
            "part_of_speech": "adjective",
            "cefr_level": "C1",
            "translation_ru": "вездесущий",
            "definition_en": "seeming to be everywhere",
            "example_en": "Smartphones have become ubiquitous.",
            "example_ru": "Смартфоны стали вездесущими.",
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))]
        )


@pytest.fixture
async def api_client(monkeypatch):
    bot_token = "999999:TEST_BOT_TOKEN"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))

    def override_llm():
        return LLMService(client=fake_client)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_service] = override_llm

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, bot_token

    get_settings.cache_clear()
    await engine.dispose()


async def test_full_api_flow(api_client):
    client, bot_token = api_client

    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    # Auth via Telegram Login Widget payload
    tg_payload = _sign_telegram_payload(
        {
            "id": 777111,
            "first_name": "Ivan",
            "username": "ivan_dev",
            "auth_date": int(time.time()),
        },
        bot_token=bot_token,
    )
    auth_resp = await client.post("/api/v1/auth/telegram", json=tg_payload)
    assert auth_resp.status_code == 200
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Add word
    word_resp = await client.post(
        "/api/v1/words",
        json={"text": "ubiquitous"},
        headers=headers,
    )
    assert word_resp.status_code == 200
    word_data = word_resp.json()
    assert word_data["created_new_card"] is True
    card_id = word_data["card"]["id"]
    assert word_data["card"]["word"]["lemma"] == "ubiquitous"

    # Fetch due cards (all active types: en_ru, ru_en, cloze, audio)
    due_resp = await client.get("/api/v1/cards/due", headers=headers)
    assert due_resp.status_code == 200
    assert len(due_resp.json()) == 4

    # Or filter by specific card_type
    due_en_ru = await client.get("/api/v1/cards/due?card_type=en_ru", headers=headers)
    assert due_en_ru.status_code == 200
    assert len(due_en_ru.json()) == 1

    # Submit review
    rev_resp = await client.post(
        f"/api/v1/cards/{card_id}/review",
        json={"rating": 3, "response_time_ms": 1400},
        headers=headers,
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["reps"] == 1

    # Check stats
    stats_resp = await client.get("/api/v1/stats", headers=headers)
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["total_cards"] == 4
    assert stats["reviewed_today"] == 1
    assert stats["retention_percent"] == 100.0
