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
from app.services.vocabulary import add_word_or_phrase, get_or_create_user_by_telegram


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
            "lemma": "resilience",
            "transcription": "/rɪˈzɪl.jəns/",
            "part_of_speech": "noun",
            "cefr_level": "B2",
            "translation_ru": "устойчивость",
            "definition_en": "the capacity to recover quickly from difficulties",
            "example_en": "Technological resilience is essential in engineering.",
            "example_ru": "Технологическая устойчивость необходима в инженерии.",
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))]
        )


@pytest.mark.asyncio
async def test_bot_add_word_visible_in_web(monkeypatch):
    bot_token = "123456:E2E_BOT_TEST_TOKEN"
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

    # 1. User adds a word in Telegram bot
    telegram_id = 998877
    username = "alex_engineer"

    async with session_factory() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=telegram_id,
            first_name="Alex",
            username=username,
        )
        llm = override_llm()
        result = await add_word_or_phrase(
            session=session,
            user=user,
            text="resilience",
            llm_service=llm,
            source_title="telegram",
        )
        await session.commit()
        assert result.word.lemma == "resilience"
        assert result.created_new_card is True

    # 2. User opens web cabinet and logs in via Telegram Widget
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        auth_data = _sign_telegram_payload(
            {
                "id": telegram_id,
                "first_name": "Alex",
                "username": username,
                "auth_date": int(time.time()),
            },
            bot_token=bot_token,
        )
        login_res = await client.post("/api/v1/auth/telegram", json=auth_data)
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Verify word is visible in Web Deck: GET /api/v1/words
        words_res = await client.get("/api/v1/words", headers=headers)
        assert words_res.status_code == 200
        words_data = words_res.json()
        assert words_data["total"] >= 1
        found = [w for w in words_data["items"] if w["lemma"] == "resilience"]
        assert len(found) == 1
        assert found[0]["translation_ru"] == "устойчивость"
        assert found[0]["cefr_level"] == "B2"
        assert found[0]["source"] == "bot"
        assert found[0]["status"] == "learning"

        # 4. Verify cards are visible in Web Study: GET /api/v1/cards/due
        due_res = await client.get("/api/v1/cards/due?limit=10", headers=headers)
        assert due_res.status_code == 200
        due_cards = due_res.json()
        assert len(due_cards) >= 1
        resilience_cards = [c for c in due_cards if c["word"]["lemma"] == "resilience"]
        assert len(resilience_cards) >= 1

        # 5. Review card in web and verify retention updates
        card_to_review = resilience_cards[0]
        review_res = await client.post(
            f"/api/v1/cards/{card_to_review['id']}/review",
            json={"rating": 3, "response_time_ms": 1200},
            headers=headers,
        )
        assert review_res.status_code == 200
        assert review_res.json()["reps"] == 1

        # 6. Check analytics reflects the review
        an_res = await client.get("/api/v1/profile/analytics", headers=headers)
        assert an_res.status_code == 200
        assert an_res.json()["retention_30d"] == 100.0

    get_settings.cache_clear()
    await engine.dispose()
