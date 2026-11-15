import hashlib
import hmac
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.models import Card, Example, Review, Source, User, Word
from app.db.session import get_db
from app.services.fsrs_service import new_card_state


def _sign_telegram_payload(payload: dict, bot_token: str) -> dict:
    signed = dict(payload)
    items = [f"{k}={v}" for k, v in sorted(signed.items()) if v is not None]
    check_str = "\n".join(items)
    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    signed["hash"] = hmac.new(secret, check_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return signed


@pytest.fixture
async def analytics_client(monkeypatch):
    bot_token = "777777:TEST_ANALYTICS_TOKEN"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, bot_token, session_factory

    get_settings.cache_clear()
    await engine.dispose()


async def test_profile_crud_and_patch(analytics_client):
    client, bot_token, _sf = analytics_client

    tg_payload = _sign_telegram_payload(
        {"id": 555111, "first_name": "ProfileUser", "auth_date": int(time.time())},
        bot_token=bot_token,
    )
    auth_resp = await client.post("/api/v1/auth/telegram", json=tg_payload)
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Get profile
    prof_resp = await client.get("/api/v1/profile", headers=headers)
    assert prof_resp.status_code == 200
    p = prof_resp.json()
    assert p["cefr_level"] == "B1"
    assert p["daily_goal"] == 15
    assert p["telegram_id"] == 555111

    # 2. Patch profile
    patch_resp = await client.patch(
        "/api/v1/profile",
        json={
            "cefr_level": "B2",
            "daily_goal": 25,
            "timezone": "Europe/London",
            "reminder_hour": 20,
            "email": "learner@example.com",
            "active_card_types": ["en_ru", "cloze"],
        },
        headers=headers,
    )
    assert patch_resp.status_code == 200
    p2 = patch_resp.json()
    assert p2["cefr_level"] == "B2"
    assert p2["daily_goal"] == 25
    assert p2["timezone"] == "Europe/London"
    assert p2["reminder_hour"] == 20
    assert p2["email"] == "learner@example.com"
    assert p2["active_card_types"] == ["en_ru", "cloze"]


async def test_analytics_and_recommendations(analytics_client):
    client, bot_token, session_factory = analytics_client

    tg_payload = _sign_telegram_payload(
        {"id": 444111, "first_name": "AnalyticsUser", "auth_date": int(time.time())},
        bot_token=bot_token,
    )
    auth_resp = await client.post("/api/v1/auth/telegram", json=tg_payload)
    token = auth_resp.json()["access_token"]
    user_id = auth_resp.json()["user_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Seed words and cards in DB
    async with session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None

        # Word 1: B2 word (i+1 if user is B1)
        w1 = Word(
            lemma="lucid",
            normalized="lucid",
            language="en",
            translation_ru="ясный, понятный",
            cefr_level="B2",
        )
        # Word 2: C1 word (advanced)
        w2 = Word(
            lemma="quintessential",
            normalized="quintessential",
            language="en",
            translation_ru="наиболее типичный",
            cefr_level="C1",
        )
        # Word 3: B1 word in user's deck with lapses
        w3 = Word(
            lemma="struggle",
            normalized="struggle",
            language="en",
            translation_ru="бороться",
            cefr_level="B1",
        )
        session.add_all([w1, w2, w3])
        await session.flush()

        # Add Source for user referencing w1
        src = Source(user_id=user.id, title="Scientific Article", source_type="reading")
        session.add(src)
        await session.flush()

        ex1 = Example(
            word_id=w1.id,
            source_id=src.id,
            sentence_en="The explanation was lucid and comprehensive.",
            sentence_ru="Объяснение было ясным и всеобъемлющим.",
        )
        session.add(ex1)

        # Create cards for w3 with lapses and reviews
        st = new_card_state()
        card_w3 = Card(
            user_id=user.id,
            word_id=w3.id,
            card_type="en_ru",
            fsrs_state=st["fsrs_state"],
            due_at=st["due_at"],
            stability=2.5,
            difficulty=6.0,
            step=1,
            state=1,
            reps=3,
            lapses=2,
            source="bot",
            status="learning",
        )
        session.add(card_w3)
        await session.flush()

        # Add reviews for card_w3
        r1 = Review(card_id=card_w3.id, user_id=user.id, rating=1, scheduled_days=1, elapsed_days=0)
        r2 = Review(card_id=card_w3.id, user_id=user.id, rating=3, scheduled_days=3, elapsed_days=1)
        session.add_all([r1, r2])
        await session.commit()

    # 1. Test Analytics
    an_resp = await client.get("/api/v1/profile/analytics", headers=headers)
    assert an_resp.status_code == 200
    an = an_resp.json()
    assert an["retention_30d"] == 50.0  # 1 out of 2 passed (rating 3)
    assert len(an["retention_daily"]) == 31
    assert len(an["workload_forecast_7d"]) == 7
    assert len(an["problem_words"]) == 1
    assert an["problem_words"][0]["lemma"] == "struggle"
    assert an["problem_words"][0]["lapses"] == 2
    assert an["stability_stats"]["mean"] == 2.5
    assert an["difficulty_stats"]["mean"] == 6.0

    # 2. Test Recommendations
    rec_resp = await client.get("/api/v1/profile/recommendations?limit=5", headers=headers)
    assert rec_resp.status_code == 200
    recs = rec_resp.json()
    assert len(recs) >= 2
    top_rec = recs[0]
    assert "word" in top_rec
    assert "score" in top_rec
    assert len(top_rec["reasons"]) > 0
    # w1 should be top or near top due to user source + i+1 B2 level
    lemmas = [r["word"]["lemma"] for r in recs]
    assert "lucid" in lemmas
