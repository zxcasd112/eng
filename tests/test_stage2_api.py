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


class _Stage2FakeCompletions:
    async def create(self, **kwargs):
        messages = kwargs.get("messages", [])
        prompt = messages[-1]["content"] if messages else ""

        if "Explain this English word" in prompt:
            data = {
                "lemma": "versatile",
                "cefr_level": "B2",
                "translation_ru": "универсальный",
                "grammar_rules": ["Can be used attributively or predicatively"],
                "prepositions_and_patterns": ["versatile in doing something"],
                "collocations": ["versatile tool", "versatile performer"],
                "synonyms_with_nuances": ["adaptable (flexible in situations)", "all-round"],
                "common_mistakes": ["Do not confuse with versatilely"],
                "examples": ["She is a versatile musician."],
            }
        elif "distractors" in prompt or "multiple-choice" in prompt:
            data = {"distractors": ["сложный", "простой", "неизвестный"]}
        else:
            data = {
                "lemma": "versatile",
                "transcription": "/ˈvɜːsətaɪl/",
                "part_of_speech": "adjective",
                "cefr_level": "B2",
                "translation_ru": "универсальный",
                "definition_en": "able to adapt or be adapted to many different functions",
                "collocations": ["versatile tool", "versatile actor"],
                "synonyms": ["adaptable", "flexible"],
                "antonyms": ["inflexible"],
                "grammar_note": "Can be followed by in/with",
                "example_en": "Python is a versatile language for engineering.",
                "example_ru": "Python — универсальный язык для разработки.",
            }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))]
        )


@pytest.fixture
async def stage2_client(monkeypatch):
    bot_token = "123456:STAGE2_TEST_TOKEN"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_Stage2FakeCompletions()))

    def override_llm():
        return LLMService(client=fake_client)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_service] = override_llm

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, bot_token

    get_settings.cache_clear()
    await engine.dispose()


async def test_stage2_card_types_and_explain(stage2_client):
    client, bot_token = stage2_client

    # Auth
    tg_payload = _sign_telegram_payload(
        {"id": 888222, "first_name": "Elena", "auth_date": int(time.time())},
        bot_token=bot_token,
    )
    auth_resp = await client.post("/api/v1/auth/telegram", json=tg_payload)
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Card types GET and PUT
    types_resp = await client.get("/api/v1/cards/types", headers=headers)
    assert types_resp.status_code == 200
    assert "en_ru" in types_resp.json()["active_card_types"]

    put_types_resp = await client.put(
        "/api/v1/cards/types",
        json={"card_types": ["en_ru", "cloze"]},
        headers=headers,
    )
    assert put_types_resp.status_code == 200
    assert put_types_resp.json()["active_card_types"] == ["en_ru", "cloze"]

    # Add word
    word_resp = await client.post(
        "/api/v1/words",
        json={"text": "versatile"},
        headers=headers,
    )
    assert word_resp.status_code == 200
    assert word_resp.json()["card"]["word"]["collocations"] is not None

    # Explain word
    exp_resp = await client.get("/api/v1/explain/versatile", headers=headers)
    assert exp_resp.status_code == 200
    exp_data = exp_resp.json()
    assert exp_data["lemma"] == "versatile"
    assert len(exp_data["collocations"]) > 0

    # Multiple Choice Quiz
    mc_resp = await client.get("/api/v1/quiz/multiple-choice", headers=headers)
    assert mc_resp.status_code == 200
    mc_data = mc_resp.json()
    quiz_id = mc_data["quiz_id"]
    correct_opt = next(o for o in mc_data["options"] if o == "универсальный")

    ans_resp = await client.post(
        "/api/v1/quiz/multiple-choice/answer",
        json={"quiz_id": quiz_id, "chosen_option": correct_opt},
        headers=headers,
    )
    assert ans_resp.status_code == 200
    assert ans_resp.json()["is_correct"] is True
