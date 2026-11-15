from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.handlers.start import (
    cmd_analytics,
    cmd_learn,
    cmd_list,
    cmd_mywords_export,
    cmd_profile,
)
from app.bot.handlers.words import cmd_add
from app.db.base import Base
from app.db.models import Card, User, Word
from app.services.fsrs_service import new_card_state


@pytest.fixture
async def bot_db_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.bot.handlers.start.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.bot.handlers.words.AsyncSessionLocal", session_factory)

    # Pre-seed user
    async with session_factory() as session:
        user = User(
            telegram_id=987654321,
            username="bot_user",
            first_name="BotTester",
            cefr_level="B1",
            daily_goal=15,
        )
        session.add(user)
        await session.flush()

        # Seed sample word and card
        w = Word(
            lemma="tenacious", normalized="tenacious", translation_ru="упорный", cefr_level="B2"
        )
        session.add(w)
        await session.flush()

        st = new_card_state()
        card = Card(
            user_id=user.id,
            word_id=w.id,
            card_type="en_ru",
            fsrs_state=st["fsrs_state"],
            due_at=st["due_at"],
            reps=1,
            lapses=0,
            status="learning",
            source="bot",
        )
        session.add(card)
        await session.commit()

    yield session_factory
    await engine.dispose()


def _make_mock_message(text: str, user_id: int = 987654321) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock(id=user_id, username="bot_user", first_name="BotTester")
    msg.answer = AsyncMock()
    msg.answer_document = AsyncMock()
    return msg


async def test_cmd_profile(bot_db_session):
    msg = _make_mock_message("/profile")
    await cmd_profile(msg)
    assert msg.answer.called
    text = msg.answer.call_args[0][0]
    assert "Твой профиль" in text
    assert "B1" in text
    assert "15 карточек" in text


async def test_cmd_analytics(bot_db_session):
    msg = _make_mock_message("/analytics")
    wait_msg = MagicMock(edit_text=AsyncMock())
    msg.answer.return_value = wait_msg

    await cmd_analytics(msg)
    assert msg.answer.called
    assert wait_msg.edit_text.called
    report = wait_msg.edit_text.call_args[0][0]
    assert "Аналитика обучения" in report
    assert "Retention за 30 дней" in report


async def test_cmd_learn(bot_db_session):
    msg = _make_mock_message("/learn")
    wait_msg = MagicMock(edit_text=AsyncMock(), delete=AsyncMock())
    msg.answer.return_value = wait_msg

    await cmd_learn(msg)
    assert msg.answer.called


async def test_cmd_list(bot_db_session):
    msg = _make_mock_message("/list")
    await cmd_list(msg)
    assert msg.answer.called
    text = msg.answer.call_args[0][0]
    assert "Твоя колода слов" in text
    assert "tenacious" in text


async def test_cmd_mywords_export(bot_db_session):
    msg = _make_mock_message("/mywords_export")
    wait_msg = MagicMock(delete=AsyncMock())
    msg.answer.return_value = wait_msg

    await cmd_mywords_export(msg)
    assert msg.answer_document.called
    kwargs = msg.answer_document.call_args[1]
    assert "Экспорт завершён" in kwargs["caption"]


async def test_cmd_add(bot_db_session):
    # Without argument
    msg_empty = _make_mock_message("/add")
    await cmd_add(msg_empty)
    assert msg_empty.answer.called
    assert "Напиши слово или фразу" in msg_empty.answer.call_args[0][0]
