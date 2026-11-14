from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Card, Example, Review, Source, User, Word
from app.services.fsrs_service import new_card_state, preview_intervals, review_fsrs_card
from app.services.llm import LLMService, WordEnrichment, WordExplanation, normalize_text
from app.services.review_engine import (
    ALL_CARD_TYPES,
    CARD_TYPE_EN_RU,
    interleave_cards,
)


@dataclass
class AddedWordResult:
    word: Word
    example: Example | None
    card: Card
    created_new_card: bool


async def get_or_create_user_by_telegram(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    res = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            active_card_types=list(ALL_CARD_TYPES),
        )
        session.add(user)
        await session.flush()
    else:
        changed = False
        if username is not None and user.username != username:
            user.username = username
            changed = True
        if first_name is not None and user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if not user.active_card_types:
            user.active_card_types = list(ALL_CARD_TYPES)
            changed = True
        if changed:
            await session.flush()
    return user


async def _get_or_create_source(
    session: AsyncSession,
    user_id: int,
    title: str,
    source_type: str = "bot",
) -> Source:
    res = await session.execute(
        select(Source).where(
            Source.user_id == user_id,
            Source.title == title,
            Source.source_type == source_type,
        )
    )
    source = res.scalar_one_or_none()
    if source is None:
        source = Source(user_id=user_id, title=title, source_type=source_type)
        session.add(source)
        await session.flush()
    return source


async def add_word_from_enrichment(
    session: AsyncSession,
    user: User,
    enrichment: WordEnrichment,
    source_title: str | None = None,
    source_type: str = "bot",
    card_type: str = CARD_TYPE_EN_RU,
    is_ai_generated: bool = True,
) -> AddedWordResult:
    norm = normalize_text(enrichment.lemma)
    res = await session.execute(
        select(Word).options(selectinload(Word.examples)).where(Word.normalized == norm)
    )
    word = res.scalar_one_or_none()
    if word is None:
        word = Word(
            lemma=enrichment.lemma.strip(),
            normalized=norm,
            language="en",
            transcription=enrichment.transcription.strip() or None,
            part_of_speech=enrichment.part_of_speech.strip() or None,
            cefr_level=enrichment.cefr_level.strip().upper()[:8] or None,
            translation_ru=enrichment.translation_ru.strip(),
            definition_en=enrichment.definition_en.strip() or None,
            collocations=enrichment.collocations or None,
            synonyms=enrichment.synonyms or None,
            antonyms=enrichment.antonyms or None,
            grammar_note=enrichment.grammar_note.strip() or None,
        )
        session.add(word)
        await session.flush()
    else:
        # Update missing enrichment metadata
        if not word.collocations and enrichment.collocations:
            word.collocations = enrichment.collocations
        if not word.synonyms and enrichment.synonyms:
            word.synonyms = enrichment.synonyms
        if not word.grammar_note and enrichment.grammar_note:
            word.grammar_note = enrichment.grammar_note

    source: Source | None = None
    if source_title:
        source = await _get_or_create_source(session, user.id, source_title, source_type)

    example: Example | None = None
    if enrichment.example_en.strip():
        ex_stmt = select(Example).where(
            Example.word_id == word.id,
            Example.sentence_en == enrichment.example_en.strip(),
        )
        ex_res = await session.execute(ex_stmt)
        example = ex_res.scalar_one_or_none()
        if example is None:
            example = Example(
                word_id=word.id,
                source_id=source.id if source else None,
                sentence_en=enrichment.example_en.strip(),
                sentence_ru=enrichment.example_ru.strip() or None,
                cefr_level=enrichment.cefr_level.strip().upper()[:8] or None,
                is_ai_generated=is_ai_generated,
            )
            session.add(example)
            await session.flush()

    active_types = getattr(user, "active_card_types", None) or ALL_CARD_TYPES
    if card_type not in active_types:
        active_types = [card_type] + [t for t in active_types if t != card_type]

    primary_card: Card | None = None
    created_any_new = False

    for c_type in active_types:
        card_res = await session.execute(
            select(Card).where(
                Card.user_id == user.id,
                Card.word_id == word.id,
                Card.card_type == c_type,
            )
        )
        card = card_res.scalar_one_or_none()
        if card is None:
            state_data = new_card_state()
            card = Card(
                user_id=user.id,
                word_id=word.id,
                example_id=example.id if example else None,
                card_type=c_type,
                fsrs_state=state_data["fsrs_state"],
                due_at=state_data["due_at"],
                stability=state_data["stability"],
                difficulty=state_data["difficulty"],
                step=state_data["step"],
                state=state_data["state"],
                reps=0,
                lapses=0,
                last_review_at=state_data["last_review_at"],
            )
            session.add(card)
            await session.flush()
            created_any_new = True

        if c_type == card_type or primary_card is None:
            primary_card = card

    assert primary_card is not None
    return AddedWordResult(
        word=word,
        example=example,
        card=primary_card,
        created_new_card=created_any_new,
    )


async def add_word_or_phrase(
    session: AsyncSession,
    user: User,
    text: str,
    llm_service: LLMService,
    source_title: str | None = None,
    source_type: str = "bot",
) -> AddedWordResult:
    norm = normalize_text(text)
    existing_word_res = await session.execute(
        select(Word).options(selectinload(Word.examples)).where(Word.normalized == norm)
    )
    existing_word = existing_word_res.scalar_one_or_none()

    if existing_word is not None:
        example = existing_word.examples[0] if existing_word.examples else None
        active_types = getattr(user, "active_card_types", None) or ALL_CARD_TYPES
        primary_card: Card | None = None
        created_any_new = False

        for c_type in active_types:
            card_res = await session.execute(
                select(Card).where(
                    Card.user_id == user.id,
                    Card.word_id == existing_word.id,
                    Card.card_type == c_type,
                )
            )
            card = card_res.scalar_one_or_none()
            if card is None:
                state_data = new_card_state()
                card = Card(
                    user_id=user.id,
                    word_id=existing_word.id,
                    example_id=example.id if example else None,
                    card_type=c_type,
                    fsrs_state=state_data["fsrs_state"],
                    due_at=state_data["due_at"],
                    stability=state_data["stability"],
                    difficulty=state_data["difficulty"],
                    step=state_data["step"],
                    state=state_data["state"],
                    reps=0,
                    lapses=0,
                    last_review_at=state_data["last_review_at"],
                )
                session.add(card)
                await session.flush()
                created_any_new = True

            if primary_card is None:
                primary_card = card

        assert primary_card is not None
        return AddedWordResult(
            word=existing_word,
            example=example,
            card=primary_card,
            created_new_card=created_any_new,
        )

    enrichment = await llm_service.enrich_word(session, text, user_level=user.cefr_level)
    return await add_word_from_enrichment(
        session=session,
        user=user,
        enrichment=enrichment,
        source_title=source_title,
        source_type=source_type,
    )


async def extract_new_words_from_sentence(
    session: AsyncSession,
    user: User,
    sentence: str,
    llm_service: LLMService,
) -> list[WordEnrichment]:
    result = await llm_service.extract_words_from_sentence(
        session,
        sentence=sentence,
        user_level=user.cefr_level,
    )
    known_res = await session.execute(
        select(Word.normalized)
        .join(Card, Card.word_id == Word.id)
        .where(Card.user_id == user.id)
    )
    known = set(known_res.scalars().all())
    return [w for w in result.words if normalize_text(w.lemma) not in known]


async def get_due_cards(
    session: AsyncSession,
    user_id: int,
    limit: int = 10,
    card_type: str | None = None,
    interleave: bool = True,
    now: datetime | None = None,
) -> list[Card]:
    now_utc = now or datetime.now(UTC)
    stmt = (
        select(Card)
        .options(selectinload(Card.word), selectinload(Card.example))
        .where(Card.user_id == user_id, Card.due_at <= now_utc)
    )
    if card_type:
        stmt = stmt.where(Card.card_type == card_type)

    stmt = stmt.order_by(Card.due_at.asc()).limit(limit * 3 if interleave else limit)
    res = await session.execute(stmt)
    cards = list(res.scalars().all())

    if interleave and len(cards) > 1:
        return interleave_cards(cards)[:limit]
    return cards[:limit]


async def get_card_with_details(
    session: AsyncSession,
    user_id: int,
    card_id: int,
) -> Card | None:
    stmt = (
        select(Card)
        .options(selectinload(Card.word), selectinload(Card.example))
        .where(Card.id == card_id, Card.user_id == user_id)
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def submit_review(
    session: AsyncSession,
    user_id: int,
    card_id: int,
    rating: int,
    response_time_ms: int | None = None,
    review_time: datetime | None = None,
) -> tuple[Card, Review]:
    card = await get_card_with_details(session, user_id, card_id)
    if card is None:
        raise ValueError(f"Card {card_id} not found for user {user_id}")

    now_utc = review_time or datetime.now(UTC)
    outcome = review_fsrs_card(card.fsrs_state, rating, review_time=now_utc)

    card.fsrs_state = outcome["fsrs_state"]
    card.due_at = outcome["due_at"]
    card.stability = outcome["stability"]
    card.difficulty = outcome["difficulty"]
    card.step = outcome["step"]
    card.state = outcome["state"]
    card.last_review_at = outcome["last_review_at"]
    card.reps += 1
    if outcome["is_lapse"]:
        card.lapses += 1

    review = Review(
        card_id=card.id,
        user_id=user_id,
        rating=rating,
        reviewed_at=now_utc,
        elapsed_days=outcome["elapsed_days"],
        scheduled_days=outcome["scheduled_days"],
        response_time_ms=response_time_ms,
    )
    session.add(review)
    await session.flush()
    return card, review


def get_card_rating_previews(card: Card) -> dict[int, str]:
    return preview_intervals(card.fsrs_state)


async def get_word_explanation(
    session: AsyncSession,
    user: User,
    word_or_lemma: str,
    llm_service: LLMService,
) -> WordExplanation:
    return await llm_service.explain_word(
        session=session,
        text=word_or_lemma,
        user_level=user.cefr_level,
    )


async def get_user_stats(session: AsyncSession, user_id: int) -> dict:
    now_utc = datetime.now(UTC)
    start_of_today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    total_cards = (
        await session.scalar(select(func.count(Card.id)).where(Card.user_id == user_id))
    ) or 0
    due_cards = (
        await session.scalar(
            select(func.count(Card.id)).where(
                Card.user_id == user_id,
                Card.due_at <= now_utc,
            )
        )
    ) or 0
    reviewed_today = (
        await session.scalar(
            select(func.count(Review.id)).where(
                Review.user_id == user_id,
                Review.reviewed_at >= start_of_today,
            )
        )
    ) or 0
    total_reviews = (
        await session.scalar(select(func.count(Review.id)).where(Review.user_id == user_id))
    ) or 0
    passed_reviews = (
        await session.scalar(
            select(func.count(Review.id)).where(
                Review.user_id == user_id,
                Review.rating >= 3,
            )
        )
    ) or 0

    retention = round((passed_reviews / total_reviews) * 100, 1) if total_reviews else 0.0

    dates_res = await session.execute(
        select(Review.reviewed_at)
        .where(Review.user_id == user_id)
        .order_by(Review.reviewed_at.desc())
        .limit(500)
    )
    review_days = {
        (dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)).date()
        for dt in dates_res.scalars().all()
    }
    streak = 0
    cursor = now_utc.date()
    if cursor not in review_days:
        cursor = cursor - timedelta(days=1)
    while cursor in review_days:
        streak += 1
        cursor = cursor - timedelta(days=1)

    # Card breakdown by type
    by_type_res = await session.execute(
        select(Card.card_type, func.count(Card.id))
        .where(Card.user_id == user_id)
        .group_by(Card.card_type)
    )
    card_types_breakdown = dict(by_type_res.all())

    return {
        "total_cards": total_cards,
        "due_cards": due_cards,
        "reviewed_today": reviewed_today,
        "total_reviews": total_reviews,
        "retention_percent": retention,
        "streak_days": streak,
        "card_types_breakdown": card_types_breakdown,
    }
