import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Card, Example, User, Word
from app.services.fsrs_service import new_card_state
from app.services.quiz_service import (
    create_matching_quiz,
    create_multiple_choice_quiz,
    create_sentence_scramble_quiz,
    verify_matching_pair,
    verify_multiple_choice_answer,
    verify_sentence_scramble_answer,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


async def _seed_data(session: AsyncSession) -> User:
    user = User(telegram_id=12345, username="tester", cefr_level="B1")
    session.add(user)
    await session.flush()

    words_info = [
        ("breakthrough", "прорыв", "A major breakthrough was achieved in science."),
        ("crucial", "решающий", "Active recall is crucial for long-term memory."),
        ("versatile", "универсальный", "Python is a versatile programming language."),
        ("inevitable", "неизбежный", "Change is inevitable in tech."),
    ]

    for lemma, tr, sent in words_info:
        w = Word(lemma=lemma, normalized=lemma, translation_ru=tr, language="en")
        session.add(w)
        await session.flush()

        ex = Example(word_id=w.id, sentence_en=sent, sentence_ru="перевод")
        session.add(ex)
        await session.flush()

        st = new_card_state()
        card = Card(
            user_id=user.id,
            word_id=w.id,
            example_id=ex.id,
            card_type="en_ru",
            fsrs_state=st["fsrs_state"],
            due_at=st["due_at"],
            state=1,
            reps=0,
            lapses=0,
        )
        session.add(card)
        await session.flush()

    await session.commit()
    return user


async def test_multiple_choice_quiz_flow(db_session: AsyncSession):
    user = await _seed_data(db_session)
    q = await create_multiple_choice_quiz(db_session, user.id)
    assert q is not None
    assert len(q.options) == 4
    assert q.correct_translation in q.options

    # Verify correct answer
    v_correct = verify_multiple_choice_answer(q.quiz_id, q.correct_translation)
    assert v_correct["valid"] is True
    assert v_correct["is_correct"] is True

    # Verify incorrect answer
    v_wrong = verify_multiple_choice_answer(q.quiz_id, "неправильный перевод")
    assert v_wrong["valid"] is True
    assert v_wrong["is_correct"] is False


async def test_sentence_scramble_quiz_flow(db_session: AsyncSession):
    user = await _seed_data(db_session)
    q = await create_sentence_scramble_quiz(db_session, user.id)
    assert q is not None
    assert len(q.shuffled_tokens) >= 4

    # Verify correct
    v_correct = verify_sentence_scramble_answer(q.quiz_id, q.original_sentence)
    assert v_correct["valid"] is True
    assert v_correct["is_correct"] is True


async def test_matching_quiz_flow(db_session: AsyncSession):
    user = await _seed_data(db_session)
    q = await create_matching_quiz(db_session, user.id, pair_count=4)
    assert q is not None
    assert len(q.pairs) >= 3

    # Check a correct pair
    en, ru = q.pairs[0]
    v_pair = verify_matching_pair(q.quiz_id, en, ru)
    assert v_pair["valid"] is True
    assert v_pair["is_match"] is True
