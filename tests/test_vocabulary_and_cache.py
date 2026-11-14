import json
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.services.llm import LLMService
from app.services.vocabulary import (
    add_word_or_phrase,
    extract_new_words_from_sentence,
    get_due_cards,
    get_or_create_user_by_telegram,
    get_user_stats,
    submit_review,
)


class FakeCompletions:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = responses
        self.calls = 0

    async def create(self, **_kwargs):
        payload = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )


def make_fake_openai(responses: list[dict]):
    completions = FakeCompletions(responses)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


async def test_llm_cache_prevents_duplicate_api_calls(db_session: AsyncSession):
    payload = {
        "lemma": "resilient",
        "transcription": "/rɪˈzɪl.jənt/",
        "part_of_speech": "adjective",
        "cefr_level": "B2",
        "translation_ru": "устойчивый, жизнестойкий",
        "definition_en": "able to recover quickly from difficulties",
        "example_en": "She remained resilient despite the setbacks.",
        "example_ru": "Она оставалась стойкой, несмотря на неудачи.",
    }
    client, completions = make_fake_openai([payload])
    llm = LLMService(client=client)

    first = await llm.enrich_word(db_session, "Resilient", user_level="B1")
    second = await llm.enrich_word(db_session, "  resilient ", user_level="B1")

    assert first.lemma == "resilient"
    assert second.translation_ru == "устойчивый, жизнестойкий"
    assert completions.calls == 1


async def test_add_word_sentence_extraction_and_review_stats(db_session: AsyncSession):
    word_payload = {
        "lemma": "ephemeral",
        "transcription": "/ɪˈfem.ər.əl/",
        "part_of_speech": "adjective",
        "cefr_level": "C1",
        "translation_ru": "мимолётный, недолговечный",
        "definition_en": "lasting for a very short time",
        "example_en": "Fame can be ephemeral.",
        "example_ru": "Слава бывает мимолётной.",
    }
    sentence_payload = {
        "words": [
            word_payload,
            {
                "lemma": "serendipity",
                "transcription": "/ˌser.ənˈdɪp.ə.ti/",
                "part_of_speech": "noun",
                "cefr_level": "C1",
                "translation_ru": "счастливая случайность",
                "definition_en": "finding good things by chance",
                "example_en": "Their meeting was pure serendipity.",
                "example_ru": "Их встреча была чистой счастливой случайностью.",
            },
        ]
    }
    client, _ = make_fake_openai([word_payload, sentence_payload])
    llm = LLMService(client=client)

    user = await get_or_create_user_by_telegram(
        db_session, telegram_id=10001, username="tester", first_name="Test"
    )

    added1 = await add_word_or_phrase(db_session, user, "ephemeral", llm_service=llm)
    assert added1.created_new_card is True

    # Adding same word again for same user does not create duplicate card
    added2 = await add_word_or_phrase(db_session, user, "ephemeral", llm_service=llm)
    assert added2.created_new_card is False
    assert added2.card.id == added1.card.id

    # Sentence extraction filters out 'ephemeral' since user already has it
    extracted = await extract_new_words_from_sentence(
        db_session,
        user,
        "Their ephemeral encounter felt like pure serendipity.",
        llm_service=llm,
    )
    assert [w.lemma for w in extracted] == ["serendipity"]

    # Due cards & review (4 card types generated per word)
    due = await get_due_cards(db_session, user.id)
    assert len(due) == 4

    card, review = await submit_review(db_session, user.id, due[0].id, rating=3)
    assert card.reps == 1
    assert review.rating == 3

    stats = await get_user_stats(db_session, user.id)
    assert stats["total_cards"] == 4
    assert stats["reviewed_today"] == 1
    assert stats["retention_percent"] == 100.0
    assert stats["streak_days"] == 1
