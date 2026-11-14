import logging
import random
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Card, Example, Word
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

_QUIZ_CACHE: dict[str, dict[str, Any]] = {}


@dataclass
class MultipleChoiceQuestion:
    quiz_id: str
    word_id: int
    lemma: str
    context_sentence: str | None
    correct_translation: str
    options: list[str]
    cefr_level: str | None


@dataclass
class SentenceScrambleQuestion:
    quiz_id: str
    word_id: int
    original_sentence: str
    translation_ru: str | None
    shuffled_tokens: list[str]
    correct_token_order: list[str]


@dataclass
class MatchingPairsQuestion:
    quiz_id: str
    pairs: list[tuple[str, str]]  # list of (en_lemma, ru_translation)
    shuffled_en: list[str]
    shuffled_ru: list[str]


async def create_multiple_choice_quiz(
    session: AsyncSession,
    user_id: int,
    llm_service: LLMService | None = None,
) -> MultipleChoiceQuestion | None:
    # Pick a random user card with word and example
    stmt = (
        select(Card)
        .options(selectinload(Card.word), selectinload(Card.example))
        .where(Card.user_id == user_id)
        .order_by(func.random())
        .limit(1)
    )
    res = await session.execute(stmt)
    card = res.scalar_one_or_none()
    if card is None:
        return None

    target_word = card.word
    correct = target_word.translation_ru

    # Select candidate distractors from other words in the DB
    other_stmt = (
        select(Word.translation_ru)
        .where(
            Word.id != target_word.id,
            Word.translation_ru != correct,
        )
        .order_by(func.random())
        .limit(6)
    )
    other_res = await session.execute(other_stmt)
    distractors = list(set(other_res.scalars().all()))[:3]

    # If database doesn't have enough other words, use LLM or fallback defaults
    if len(distractors) < 3 and llm_service is not None:
        try:
            llm_distractors = await llm_service.generate_distractors(
                session=session,
                lemma=target_word.lemma,
                correct_translation=correct,
                user_level=target_word.cefr_level or "B1",
                count=3 - len(distractors),
            )
            distractors.extend(llm_distractors)
        except Exception:
            logger.debug("Failed to generate LLM distractors, using fallbacks", exc_info=True)

    fallback_distractors = ["развитие", "исследование", "влияние", "понимание", "возможность"]
    for fb in fallback_distractors:
        if len(distractors) >= 3:
            break
        if fb != correct and fb not in distractors:
            distractors.append(fb)

    options = [correct] + distractors[:3]
    random.shuffle(options)

    quiz_id = uuid.uuid4().hex[:12]
    _QUIZ_CACHE[quiz_id] = {
        "type": "multiple_choice",
        "word_id": target_word.id,
        "correct": correct,
        "lemma": target_word.lemma,
    }

    context = card.example.sentence_en if card.example else None

    return MultipleChoiceQuestion(
        quiz_id=quiz_id,
        word_id=target_word.id,
        lemma=target_word.lemma,
        context_sentence=context,
        correct_translation=correct,
        options=options,
        cefr_level=target_word.cefr_level,
    )


def verify_multiple_choice_answer(quiz_id: str, chosen_option: str) -> dict[str, Any]:
    cached = _QUIZ_CACHE.get(quiz_id)
    if not cached:
        return {"valid": False, "error": "Quiz expired"}
    is_correct = chosen_option.strip().lower() == cached["correct"].strip().lower()
    return {
        "valid": True,
        "is_correct": is_correct,
        "correct_answer": cached["correct"],
        "lemma": cached["lemma"],
    }


async def create_sentence_scramble_quiz(
    session: AsyncSession,
    user_id: int,
) -> SentenceScrambleQuestion | None:
    # Find examples associated with user's cards
    stmt = (
        select(Example, Word)
        .join(Word, Example.word_id == Word.id)
        .join(Card, Card.word_id == Word.id)
        .where(Card.user_id == user_id, Example.sentence_en.isnot(None))
        .order_by(func.random())
        .limit(1)
    )
    res = await session.execute(stmt)
    row = res.first()
    if not row:
        return None

    example, word = row
    tokens = [t.strip() for t in example.sentence_en.split() if t.strip()]
    if len(tokens) < 4:
        return None

    shuffled = list(tokens)
    # Ensure shuffled is different from original
    for _ in range(10):
        random.shuffle(shuffled)
        if shuffled != tokens:
            break

    quiz_id = uuid.uuid4().hex[:12]
    _QUIZ_CACHE[quiz_id] = {
        "type": "scramble",
        "tokens": tokens,
        "original": example.sentence_en,
        "translation_ru": example.sentence_ru,
    }

    return SentenceScrambleQuestion(
        quiz_id=quiz_id,
        word_id=word.id,
        original_sentence=example.sentence_en,
        translation_ru=example.sentence_ru,
        shuffled_tokens=shuffled,
        correct_token_order=tokens,
    )


def verify_sentence_scramble_answer(quiz_id: str, submitted_sentence: str) -> dict[str, Any]:
    cached = _QUIZ_CACHE.get(quiz_id)
    if not cached:
        return {"valid": False, "error": "Quiz expired"}

    # Compare cleaned string
    norm_sub = " ".join(submitted_sentence.strip().split()).rstrip(".")
    norm_orig = " ".join(cached["original"].strip().split()).rstrip(".")
    is_correct = norm_sub.lower() == norm_orig.lower()

    return {
        "valid": True,
        "is_correct": is_correct,
        "original_sentence": cached["original"],
        "translation_ru": cached.get("translation_ru"),
    }


async def create_matching_quiz(
    session: AsyncSession,
    user_id: int,
    pair_count: int = 5,
) -> MatchingPairsQuestion | None:
    stmt = (
        select(Word)
        .join(Card, Card.word_id == Word.id)
        .where(Card.user_id == user_id)
        .distinct()
        .order_by(func.random())
        .limit(pair_count)
    )
    res = await session.execute(stmt)
    words = list(res.scalars().all())
    if len(words) < 3:
        return None

    pairs = [(w.lemma, w.translation_ru) for w in words]
    shuffled_en = [p[0] for p in pairs]
    shuffled_ru = [p[1] for p in pairs]
    random.shuffle(shuffled_en)
    random.shuffle(shuffled_ru)

    quiz_id = uuid.uuid4().hex[:12]
    _QUIZ_CACHE[quiz_id] = {
        "type": "matching",
        "pair_dict": {p[0].lower(): p[1].lower() for p in pairs},
    }

    return MatchingPairsQuestion(
        quiz_id=quiz_id,
        pairs=pairs,
        shuffled_en=shuffled_en,
        shuffled_ru=shuffled_ru,
    )


def verify_matching_pair(quiz_id: str, en_word: str, ru_translation: str) -> dict[str, Any]:
    cached = _QUIZ_CACHE.get(quiz_id)
    if not cached:
        return {"valid": False, "error": "Quiz expired"}

    expected_ru = cached["pair_dict"].get(en_word.strip().lower())
    is_match = expected_ru == ru_translation.strip().lower()

    return {
        "valid": True,
        "is_match": is_match,
        "en_word": en_word,
        "ru_translation": ru_translation,
    }
