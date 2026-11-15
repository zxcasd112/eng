import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.models import Card, Word
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
            "lemma": "meticulous",
            "transcription": "/məˈtɪk.jə.ləs/",
            "part_of_speech": "adjective",
            "cefr_level": "C1",
            "translation_ru": "доскональный, тщательный",
            "definition_en": "showing great attention to detail",
            "example_en": "She was meticulous about keeping records.",
            "example_ru": "Она тщательно вела записи.",
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))]
        )


@pytest.fixture
async def vocab_client(monkeypatch):
    bot_token = "888888:TEST_VOCAB_TOKEN"
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
        yield client, bot_token, session_factory

    get_settings.cache_clear()
    await engine.dispose()


async def test_vocabulary_crud_and_filters(vocab_client):
    client, bot_token, _sf = vocab_client

    # 1. Authenticate user
    tg_payload = _sign_telegram_payload(
        {"id": 123456, "first_name": "TestUser", "auth_date": int(time.time())},
        bot_token=bot_token,
    )
    auth_resp = await client.post("/api/v1/auth/telegram", json=tg_payload)
    assert auth_resp.status_code == 200
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Add word via API
    add_resp = await client.post(
        "/api/v1/words",
        json={"text": "meticulous", "source": "web"},
        headers=headers,
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["created_new_card"] is True
    word_id = add_resp.json()["card"]["word"]["id"]

    # 3. List words (GET /api/v1/words)
    list_resp = await client.get("/api/v1/words", headers=headers)
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["lemma"] == "meticulous"
    assert data["items"][0]["source"] == "web"
    assert data["items"][0]["status"] == "learning"

    # 4. Filter by CEFR matching and non-matching
    c1_resp = await client.get("/api/v1/words?cefr_level=C1", headers=headers)
    assert c1_resp.status_code == 200
    assert c1_resp.json()["total"] == 1

    a1_resp = await client.get("/api/v1/words?cefr_level=A1", headers=headers)
    assert a1_resp.status_code == 200
    assert a1_resp.json()["total"] == 0

    # 5. Search by query
    search_resp = await client.get("/api/v1/words?search=metic", headers=headers)
    assert search_resp.status_code == 200
    assert search_resp.json()["total"] == 1

    search_ru_resp = await client.get("/api/v1/words?search=тщательн", headers=headers)
    assert search_ru_resp.status_code == 200
    assert search_ru_resp.json()["total"] == 1

    no_match_resp = await client.get("/api/v1/words?search=nonexistentword", headers=headers)
    assert no_match_resp.status_code == 200
    assert no_match_resp.json()["total"] == 0

    # 6. Word Detail (GET /api/v1/words/{id})
    detail_resp = await client.get(f"/api/v1/words/{word_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == word_id
    assert detail["lemma"] == "meticulous"
    assert len(detail["cards"]) == 4

    # 7. Update Word (PATCH /api/v1/words/{id})
    patch_resp = await client.patch(
        f"/api/v1/words/{word_id}",
        json={"status": "mastered", "notes": "Learned in project review", "cefr_level": "C2"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["status"] == "mastered"
    assert patched["notes"] == "Learned in project review"
    assert patched["cefr_level"] == "C2"

    # 8. Delete Word from deck (DELETE /api/v1/words/{id})
    del_resp = await client.delete(f"/api/v1/words/{word_id}", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"

    # Verify deleted from user's deck
    list_after_del = await client.get("/api/v1/words", headers=headers)
    assert list_after_del.json()["total"] == 0


async def test_import_words_csv_and_deduplication(vocab_client):
    client, bot_token, session_factory = vocab_client

    tg_payload = _sign_telegram_payload(
        {"id": 999111, "first_name": "CSVUser", "auth_date": int(time.time())},
        bot_token=bot_token,
    )
    auth_resp = await client.post("/api/v1/auth/telegram", json=tg_payload)
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Prepare CSV content with valid rows, duplicate rows, and broken row
    csv_content = (
        "word,translation\n"
        "ubiquitous,вездесущий\n"
        "versatile,универсальный\n"
        "ubiquitous,вездесущий повтор\n"  # duplicate in CSV
        " , \n"  # broken line
        "resilient,устойчивый\n"
    )

    import_resp = await client.post(
        "/api/v1/words/import",
        files={"file": ("words.csv", csv_content.encode("utf-8"), "text/csv")},
        headers=headers,
    )
    assert import_resp.status_code == 200
    report = import_resp.json()
    assert report["added"] == 3  # ubiquitous, versatile, resilient
    assert report["duplicates"] == 1  # 2nd ubiquitous
    assert len(report["errors"]) == 0  # empty line skipped cleanly

    # Test deduplication when adding same word again via API
    re_add = await client.post(
        "/api/v1/words/import",
        files={"file": ("words2.csv", "resilient,устойчивый\n".encode(), "text/csv")},
        headers=headers,
    )
    assert re_add.status_code == 200
    assert re_add.json()["added"] == 0
    assert re_add.json()["duplicates"] == 1

    # Verify Word count in DB vs Cards for user
    async with session_factory() as session:
        words_count = await session.scalar(select(Word.id).where(Word.normalized == "resilient"))
        assert words_count is not None
        cards_count = (
            await session.scalars(
                select(Card.id)
                .join(Word, Card.word_id == Word.id)
                .where(Card.user_id == 1, Word.normalized == "resilient")
            )
        ).all()
        # Exactly 4 cards (one per active card type), no duplicates
        assert len(cards_count) == 4
