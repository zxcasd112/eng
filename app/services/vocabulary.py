import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Card, Example, Review, Source, User, Word
from app.services.fsrs_service import new_card_state, preview_intervals, review_fsrs_card
from app.services.llm import (
    LLMNotConfiguredError,
    LLMService,
    WordEnrichment,
    WordExplanation,
    normalize_text,
)
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


async def get_or_create_user_by_email(
    session: AsyncSession,
    email: str,
    first_name: str | None = None,
) -> User:
    norm_email = email.strip().lower()
    res = await session.execute(select(User).where(User.email == norm_email))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(
            email=norm_email,
            first_name=first_name,
            telegram_id=None,
            active_card_types=list(ALL_CARD_TYPES),
        )
        session.add(user)
        await session.flush()
    else:
        changed = False
        if first_name is not None and not user.first_name:
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
                source=source_type,
                status="learning",
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
    try:
        result = await llm_service.extract_words_from_sentence(
            session,
            sentence=sentence,
            user_level=user.cefr_level,
        )
        words = result.words
    except (LLMNotConfiguredError, RuntimeError, OSError, ValueError):
        import re

        tokens = set(re.findall(r"\b[a-zA-Z]{3,}\b", sentence.lower()))
        stopwords = {
            "the", "and", "for", "with", "that", "this", "from", "are", "were", "been",
            "have", "has", "had", "they", "them", "their", "what", "which", "will", "would",
            "can", "could", "should", "about", "into", "over", "after", "then", "also",
            "some", "very", "just", "like", "other", "than", "now", "only", "well"
        }
        candidate_tokens = [t for t in tokens if t not in stopwords]
        words = []
        if candidate_tokens:
            stmt = select(Word).where(Word.normalized.in_(candidate_tokens)).limit(6)
            db_words = (await session.execute(stmt)).scalars().all()
            for dbw in db_words:
                words.append(
                    WordEnrichment(
                        lemma=dbw.lemma,
                        transcription=dbw.transcription or "",
                        part_of_speech=dbw.part_of_speech or "word",
                        cefr_level=dbw.cefr_level or "B1",
                        translation_ru=dbw.translation_ru,
                        definition_en=dbw.definition_en or "",
                        example_en=sentence,
                        example_ru="Пример из вашего предложения.",
                    )
                )

    known_res = await session.execute(
        select(Word.normalized).join(Card, Card.word_id == Word.id).where(Card.user_id == user.id)
    )
    known = set(known_res.scalars().all())
    return [w for w in words if normalize_text(w.lemma) not in known]


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


async def get_user_stats(session: AsyncSession, user_id: int, user_tz: str | None = None) -> dict:
    now_utc = datetime.now(UTC)
    if user_tz:
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(user_tz)
        except Exception:  # noqa: BLE001
            tz = UTC
    else:
        tz = UTC

    now_user = datetime.now(tz)
    start_of_today_user = now_user.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_today = start_of_today_user.astimezone(UTC)

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


async def get_user_words(
    session: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    cefr_level: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> tuple[list[dict], int]:
    """Retrieve user's distinct deck words with filters and pagination."""
    base_query = (
        select(
            Word,
            func.min(Card.created_at).label("card_created_at"),
            func.min(Card.status).label("card_status"),
            func.min(Card.source).label("card_source"),
            func.max(Card.notes).label("card_notes"),
            func.count(Card.id).label("cards_count"),
            func.min(Card.due_at).label("next_due_at"),
            func.sum(Card.reps).label("total_reps"),
            func.sum(Card.lapses).label("total_lapses"),
        )
        .join(Card, Card.word_id == Word.id)
        .where(Card.user_id == user_id)
        .group_by(Word.id)
    )

    count_subquery = (
        select(Word.id).join(Card, Card.word_id == Word.id).where(Card.user_id == user_id)
    )

    if cefr_level:
        lvl = cefr_level.strip().upper()
        base_query = base_query.where(Word.cefr_level == lvl)
        count_subquery = count_subquery.where(Word.cefr_level == lvl)
    if status:
        st = status.strip().lower()
        base_query = base_query.where(Card.status == st)
        count_subquery = count_subquery.where(Card.status == st)
    if search:
        s = f"%{search.strip().lower()}%"
        cond = or_(func.lower(Word.lemma).like(s), func.lower(Word.translation_ru).like(s))
        base_query = base_query.where(cond)
        count_subquery = count_subquery.where(cond)

    sub = count_subquery.distinct().subquery()
    total = await session.scalar(select(func.count()).select_from(sub)) or 0

    offset_val = max(0, (page - 1) * page_size)
    paginated_query = (
        base_query.order_by(func.min(Card.created_at).desc()).offset(offset_val).limit(page_size)
    )
    rows = (await session.execute(paginated_query)).all()

    items = []
    for r in rows:
        w = r[0]
        items.append(
            {
                "id": w.id,
                "lemma": w.lemma,
                "translation_ru": w.translation_ru,
                "transcription": w.transcription,
                "part_of_speech": w.part_of_speech,
                "cefr_level": w.cefr_level,
                "status": r.card_status or "learning",
                "source": r.card_source or "bot",
                "notes": r.card_notes,
                "created_at": r.card_created_at,
                "cards_count": r.cards_count or 0,
                "next_due_at": r.next_due_at,
                "total_reps": int(r.total_reps or 0),
                "total_lapses": int(r.total_lapses or 0),
                "collocations": w.collocations,
                "grammar_note": w.grammar_note,
            }
        )

    return items, total


async def get_user_word_detail(
    session: AsyncSession,
    user_id: int,
    word_id: int,
) -> dict | None:
    """Get full details of a word in user's deck including examples, cards, and reviews."""
    word_res = await session.execute(
        select(Word).options(selectinload(Word.examples)).where(Word.id == word_id)
    )
    word = word_res.scalar_one_or_none()
    if word is None:
        return None

    cards_res = await session.execute(
        select(Card)
        .options(selectinload(Card.reviews), selectinload(Card.example))
        .where(Card.user_id == user_id, Card.word_id == word_id)
    )
    cards = cards_res.scalars().all()
    if not cards:
        return None

    all_reviews = []
    for c in cards:
        for rev in c.reviews:
            all_reviews.append(
                {
                    "id": rev.id,
                    "card_id": rev.card_id,
                    "rating": rev.rating,
                    "reviewed_at": rev.reviewed_at,
                    "scheduled_days": rev.scheduled_days,
                    "elapsed_days": rev.elapsed_days,
                    "response_time_ms": rev.response_time_ms,
                }
            )
    all_reviews.sort(key=lambda x: x["reviewed_at"], reverse=True)

    primary_card = cards[0]
    cards_out = []
    for c in cards:
        cards_out.append(
            {
                "id": c.id,
                "card_type": c.card_type,
                "due_at": c.due_at,
                "state": c.state,
                "reps": c.reps,
                "lapses": c.lapses,
                "word": {
                    "id": word.id,
                    "lemma": word.lemma,
                    "transcription": word.transcription,
                    "part_of_speech": word.part_of_speech,
                    "cefr_level": word.cefr_level,
                    "translation_ru": word.translation_ru,
                    "definition_en": word.definition_en,
                    "collocations": word.collocations,
                    "synonyms": word.synonyms,
                    "antonyms": word.antonyms,
                    "grammar_note": word.grammar_note,
                },
                "example": {
                    "id": c.example.id,
                    "sentence_en": c.example.sentence_en,
                    "sentence_ru": c.example.sentence_ru,
                }
                if c.example
                else None,
            }
        )

    examples_out = [
        {"id": ex.id, "sentence_en": ex.sentence_en, "sentence_ru": ex.sentence_ru}
        for ex in word.examples
    ]

    return {
        "id": word.id,
        "lemma": word.lemma,
        "normalized": word.normalized,
        "translation_ru": word.translation_ru,
        "transcription": word.transcription,
        "part_of_speech": word.part_of_speech,
        "cefr_level": word.cefr_level,
        "definition_en": word.definition_en,
        "collocations": word.collocations,
        "synonyms": word.synonyms,
        "antonyms": word.antonyms,
        "grammar_note": word.grammar_note,
        "status": primary_card.status or "learning",
        "source": primary_card.source or "bot",
        "notes": primary_card.notes,
        "created_at": primary_card.created_at,
        "examples": examples_out,
        "cards": cards_out,
        "reviews": all_reviews,
    }


async def update_user_word(
    session: AsyncSession,
    user_id: int,
    word_id: int,
    status: str | None = None,
    notes: str | None = None,
    cefr_level: str | None = None,
) -> dict | None:
    """Update user card status/notes or word CEFR level."""
    cards_res = await session.execute(
        select(Card).where(Card.user_id == user_id, Card.word_id == word_id)
    )
    cards = cards_res.scalars().all()
    if not cards:
        return None

    for c in cards:
        if status is not None:
            c.status = status.strip().lower()
        if notes is not None:
            c.notes = notes.strip()

    if cefr_level is not None:
        word = await session.get(Word, word_id)
        if word:
            word.cefr_level = cefr_level.strip().upper()[:8]

    await session.flush()
    return await get_user_word_detail(session, user_id, word_id)


async def delete_user_word(
    session: AsyncSession,
    user_id: int,
    word_id: int,
) -> bool:
    """Remove a word from user's deck (deletes user's cards, keeps Word entity)."""
    cards_res = await session.execute(
        select(Card).where(Card.user_id == user_id, Card.word_id == word_id)
    )
    cards = cards_res.scalars().all()
    if not cards:
        return False

    for c in cards:
        await session.delete(c)
    await session.flush()
    return True


async def import_words_csv(
    session: AsyncSession,
    user: User,
    csv_text: str,
    source_type: str = "import",
) -> dict:
    """Import words from CSV text with report: added, duplicates, errors."""
    added = 0
    duplicates = 0
    errors: list[str] = []

    if not csv_text.strip():
        return {"added": 0, "duplicates": 0, "errors": ["Empty CSV content"]}

    # Detect delimiter: comma, semicolon, tab
    sample = csv_text[:1024]
    delimiter = ","
    if ";" in sample and sample.count(";") > sample.count(","):
        delimiter = ";"
    elif "\t" in sample and sample.count("\t") > sample.count(","):
        delimiter = "\t"

    reader = csv.reader(io.StringIO(csv_text), delimiter=delimiter)
    active_types = getattr(user, "active_card_types", None) or ALL_CARD_TYPES

    for line_idx, row in enumerate(reader, start=1):
        if not row or not any(field.strip() for field in row):
            continue

        raw_lemma = row[0].strip()
        raw_translation = row[1].strip() if len(row) > 1 else ""

        # Skip header row if detected
        if line_idx == 1 and raw_lemma.lower() in {"word", "lemma", "слово", "term", "english"}:
            continue

        if not raw_lemma:
            errors.append(f"Line {line_idx}: empty word")
            continue

        norm = normalize_text(raw_lemma)
        if not norm:
            errors.append(f"Line {line_idx}: invalid word format '{raw_lemma}'")
            continue

        # Check if user already has this word in cards
        existing_card = await session.scalar(
            select(Card.id)
            .join(Word, Card.word_id == Word.id)
            .where(Card.user_id == user.id, Word.normalized == norm)
        )
        if existing_card is not None:
            duplicates += 1
            continue

        # Find or create Word
        w_res = await session.execute(select(Word).where(Word.normalized == norm))
        word = w_res.scalar_one_or_none()
        if word is None:
            word = Word(
                lemma=raw_lemma,
                normalized=norm,
                language="en",
                translation_ru=raw_translation or raw_lemma,
                cefr_level="B1",
            )
            session.add(word)
            await session.flush()
        elif raw_translation and (not word.translation_ru or word.translation_ru == word.lemma):
            word.translation_ru = raw_translation
            await session.flush()

        # Create cards for active card types
        for c_type in active_types:
            st = new_card_state()
            c = Card(
                user_id=user.id,
                word_id=word.id,
                card_type=c_type,
                source=source_type,
                status="new",
                fsrs_state=st["fsrs_state"],
                due_at=st["due_at"],
                stability=st["stability"],
                difficulty=st["difficulty"],
                step=st["step"],
                state=st["state"],
                reps=0,
                lapses=0,
            )
            session.add(c)

        await session.flush()
        added += 1

    return {"added": added, "duplicates": duplicates, "errors": errors}
