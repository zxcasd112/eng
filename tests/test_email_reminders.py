from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.bot.scheduler import send_due_reminders
from app.config import get_settings
from app.db.base import Base
from app.db.models import Card, User, Word
from app.db.session import get_db
from app.services.email_service import (
    generate_unsubscribe_token,
    verify_unsubscribe_token,
)
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
async def test_reminder_channel_and_unsubscribe_flow(test_env):
    client, session_factory = test_env

    # 1. Login user
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "notify_me@test.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "notify_me@test.com", "code": code})

    # 2. Update profile with reminder_channel = 'both'
    patch_resp = await client.patch("/api/v1/profile", json={"reminder_channel": "both"})
    assert patch_resp.status_code == 200
    p_data = patch_resp.json()
    assert p_data["reminder_channel"] == "both"

    # 3. Test unsubscribe token generation & verification
    token = generate_unsubscribe_token(p_data["id"], "notify_me@test.com")
    verified = verify_unsubscribe_token(token)
    assert verified is not None
    assert verified[0] == p_data["id"]
    assert verified[1] == "notify_me@test.com"

    # Tampered token
    assert verify_unsubscribe_token(token + "tampered") is None

    # 4. Hit unsubscribe endpoint (public, unauthenticated)
    unsub_resp = await client.get(f"/api/v1/profile/unsubscribe?token={token}")
    assert unsub_resp.status_code == 200
    assert "успешно отписались" in unsub_resp.text

    # Verify in DB that reminder_channel changed to telegram
    async with session_factory() as session:
        u_res = await session.execute(select(User).where(User.id == p_data["id"]))
        user = u_res.scalar_one()
        assert user.reminder_channel == "telegram"


@pytest.mark.asyncio
async def test_scheduler_due_reminders_dispatch(test_env, monkeypatch):
    _, session_factory = test_env
    now_utc = datetime.now(UTC)

    # Monkeypatch AsyncSessionLocal in scheduler
    monkeypatch.setattr("app.bot.scheduler.AsyncSessionLocal", session_factory)

    # Seed user with due cards and email reminders
    async with session_factory() as session:
        user = User(
            email="learner@school.com",
            telegram_id=12345678,
            reminder_hour=now_utc.hour,
            reminder_channel="both",
            cefr_level="B1",
        )
        session.add(user)
        await session.flush()

        word = Word(lemma="persistence", normalized="persistence", translation_ru="упорство")
        session.add(word)
        await session.flush()

        card = Card(
            user_id=user.id,
            word_id=word.id,
            card_type="en_ru",
            fsrs_state=1,
            due_at=now_utc - timedelta(hours=2),
            stability=2.0,
            difficulty=5.0,
            status="learning",
        )
        session.add(card)
        await session.commit()

    # Mock bot
    from unittest.mock import AsyncMock, MagicMock
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    # Trigger scheduler job
    await send_due_reminders(mock_bot)

    # Bot message was sent
    assert mock_bot.send_message.called
    assert mock_bot.send_message.call_args[1]["chat_id"] == 12345678
