from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.models import Card, Review, User, Word
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
        yield client, session_factory

    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_anki_advanced_analytics_and_heatmap(test_env):
    client, session_factory = test_env

    # 1. Login user
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "anki_fan@test.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "anki_fan@test.com", "code": code})

    now_utc = datetime.now(UTC)

    # 2. Seed synthetic cards and reviews
    async with session_factory() as session:
        user_res = await session.execute(
            select(User).where(User.email == "anki_fan@test.com")
        )
        user = user_res.scalar_one()

        # Word 1: Mature card (stability=35, scheduled_days=30)
        w1 = Word(lemma="serendipity", normalized="serendipity", translation_ru="счастливая случайность", cefr_level="C1")
        # Word 2: Young learning card (stability=4.5, scheduled_days=4)
        w2 = Word(lemma="meticulous", normalized="meticulous", translation_ru="дотошный", cefr_level="B2")
        session.add_all([w1, w2])
        await session.flush()

        # Mature card
        c1 = Card(
            user_id=user.id,
            word_id=w1.id,
            card_type="en_ru",
            fsrs_state=2,
            due_at=now_utc + timedelta(days=10),
            stability=35.0,
            difficulty=4.0,
            last_review_at=now_utc - timedelta(days=5),
            step=3,
            state=2,
            reps=5,
            lapses=0,
            status="review",
        )
        # Young card
        c2 = Card(
            user_id=user.id,
            word_id=w2.id,
            card_type="ru_en",
            fsrs_state=1,
            due_at=now_utc + timedelta(days=1),
            stability=4.5,
            difficulty=7.0,
            last_review_at=now_utc - timedelta(days=1),
            step=1,
            state=1,
            reps=2,
            lapses=1,
            status="learning",
        )
        session.add_all([c1, c2])
        await session.flush()

        # Reviews:
        # r1: mature review (scheduled_days=30, rating=3 Good) -> pass
        r1 = Review(card_id=c1.id, user_id=user.id, rating=3, scheduled_days=30, elapsed_days=25, reviewed_at=now_utc - timedelta(days=5))
        # r2: mature review (scheduled_days=24, rating=4 Easy) -> pass
        r2 = Review(card_id=c1.id, user_id=user.id, rating=4, scheduled_days=24, elapsed_days=24, reviewed_at=now_utc - timedelta(days=35))
        # r3: mature review (scheduled_days=22, rating=1 Again) -> fail
        r3 = Review(card_id=c1.id, user_id=user.id, rating=1, scheduled_days=22, elapsed_days=21, reviewed_at=now_utc - timedelta(days=60))
        # r4: young review (scheduled_days=3, rating=3 Good)
        r4 = Review(card_id=c2.id, user_id=user.id, rating=3, scheduled_days=3, elapsed_days=3, reviewed_at=now_utc - timedelta(days=1))

        session.add_all([r1, r2, r3, r4])
        await session.commit()

    # 3. Query analytics endpoint
    res = await client.get("/api/v1/profile/analytics")
    assert res.status_code == 200
    data = res.json()

    # Verify Activity Heatmap 365 Days
    heatmap = data.get("activity_heatmap_365d", [])
    assert len(heatmap) == 366  # 365 days range
    total_reviews_in_heatmap = sum(h["count"] for h in heatmap)
    assert total_reviews_in_heatmap == 4

    # Verify 30-day forecast
    forecast30 = data.get("workload_forecast_30d", [])
    assert len(forecast30) == 30
    assert len(data.get("workload_forecast_7d", [])) == 7

    # Verify Anki-style Metrics
    anki = data.get("anki_metrics")
    assert anki is not None
    # 3 mature reviews: ratings 3, 4, 1 -> 2 out of 3 passed = 66.7%
    assert anki["true_retention_mature_pct"] == 66.7
    assert anki["mature_cards_count"] == 1  # c1 has stability 35.0 >= 21.0
    assert anki["total_mature_reviews"] == 3
    # Average stability: (35.0 + 4.5) / 2 = 19.75
    assert anki["avg_stability"] == 19.75
    # Average difficulty: (4.0 + 7.0) / 2 = 5.5
    assert anki["avg_difficulty"] == 5.5
    # Active vocabulary count should be 2
    assert anki["active_vocabulary_estimate"] >= 1
