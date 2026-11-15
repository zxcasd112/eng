import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.services.llm import LLMService


@pytest.fixture
async def test_env(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-32-chars-long-minimum!")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999999:TEST_BOT_TOKEN")
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    def override_llm():
        return LLMService(client=None)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_service] = override_llm

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_review_advances_queue_and_409_on_duplicate(test_env):
    """Test:
    1. Answer to card pushes it away so next due is not the same card.
    2. Rapid duplicate submission for same card returns 409 Conflict.
    3. Due cards count without limit returns accurate count.
    4. Reviewed today increases in /stats and /profile/analytics.
    """
    client = test_env

    # 1. Login user
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "reviewer@test.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "reviewer@test.com", "code": code})

    # 2. Add two words to deck
    r1 = await client.post("/api/v1/words", json={"lemma": "apple", "translation_ru": "яблоко"})
    assert r1.status_code in (200, 201)
    card1_id = r1.json()["card"]["id"]

    r2 = await client.post("/api/v1/words", json={"lemma": "banana", "translation_ru": "банан"})
    assert r2.status_code in (200, 201)
    card2_id = r2.json()["card"]["id"]

    # 3. Check due count
    count_resp = await client.get("/api/v1/cards/due/count")
    assert count_resp.status_code == 200
    assert count_resp.json()["count"] >= 2

    # Initial stats
    stats_before = await client.get("/api/v1/stats")
    assert stats_before.status_code == 200
    reviewed_before = stats_before.json()["reviewed_today"]

    # 4. Fetch due cards
    due_resp = await client.get("/api/v1/cards/due?limit=10")
    assert due_resp.status_code == 200
    due_cards = due_resp.json()
    assert len(due_cards) >= 2
    first_card = due_cards[0]
    assert first_card["id"] == card1_id

    # 5. Submit review for first card
    rev_resp = await client.post(
        f"/api/v1/cards/{first_card['id']}/review",
        json={"rating": 3, "response_time_ms": 1200},
    )
    assert rev_resp.status_code == 200

    # 6. Duplicate review for the SAME card immediately must return 409 Conflict
    dup_resp = await client.post(
        f"/api/v1/cards/{first_card['id']}/review",
        json={"rating": 3, "response_time_ms": 1100},
    )
    assert dup_resp.status_code == 409
    assert "already submitted" in dup_resp.json()["detail"]

    # 7. Check next due cards: first_card should not be the first due card anymore
    next_due_resp = await client.get("/api/v1/cards/due?limit=10")
    assert next_due_resp.status_code == 200
    next_due_cards = next_due_resp.json()
    assert len(next_due_cards) > 0
    assert next_due_cards[0]["id"] != first_card["id"]
    assert next_due_cards[0]["id"] == card2_id

    # 8. Check reviewed_today in /stats and /profile/analytics
    stats_after = await client.get("/api/v1/stats")
    assert stats_after.status_code == 200
    assert stats_after.json()["reviewed_today"] == reviewed_before + 1

    analytics = await client.get("/api/v1/profile/analytics")
    assert analytics.status_code == 200
    assert analytics.json()["reviewed_today"] == reviewed_before + 1
