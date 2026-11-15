import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Card, Example, Mistake, User, Word
from app.db.session import get_db
from app.services.fsrs_service import new_card_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/mistakes", tags=["mistakes"])


class MistakeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    original: str
    correction: str
    explanation: str | None = None
    word_id: int | None = None
    created_at: datetime
    has_card: bool = False


class ConvertMistakeResponse(BaseModel):
    card_id: int
    message: str


@router.get("", response_model=list[MistakeOut])
async def list_mistakes(
    source: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[MistakeOut]:
    stmt = select(Mistake).where(Mistake.user_id == user.id)
    if source:
        stmt = stmt.where(Mistake.source == source)
    stmt = stmt.order_by(Mistake.created_at.desc()).offset(offset).limit(limit)

    result = await session.execute(stmt)
    mistakes = result.scalars().all()

    # Check which mistakes already have associated cloze cards
    existing_cards_res = await session.execute(
        select(Card.word_id).where(
            Card.user_id == user.id,
            Card.card_type == "cloze",
            Card.source == "mistake",
        )
    )
    cloze_word_ids = set(existing_cards_res.scalars().all())

    items = []
    for m in mistakes:
        has_card = m.word_id in cloze_word_ids if m.word_id else False
        items.append(
            MistakeOut(
                id=m.id,
                source=m.source,
                original=m.original,
                correction=m.correction,
                explanation=m.explanation,
                word_id=m.word_id,
                created_at=m.created_at,
                has_card=has_card,
            )
        )
    return items


@router.post("/{mistake_id}/to-cards", response_model=ConvertMistakeResponse)
async def convert_mistake_to_card(
    mistake_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ConvertMistakeResponse:
    res = await session.execute(
        select(Mistake).where(Mistake.id == mistake_id, Mistake.user_id == user.id)
    )
    mistake = res.scalar_one_or_none()
    if not mistake:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ошибка с id {mistake_id} не найдена",
        )

    # Resolve or create target Word
    word = None
    if mistake.word_id:
        w_res = await session.execute(select(Word).where(Word.id == mistake.word_id))
        word = w_res.scalar_one_or_none()

    if not word:
        # Extract primary English lemma from correction
        clean_words = re.findall(r"\b[A-Za-z'-]+\b", mistake.correction)
        lemma = clean_words[0].lower() if clean_words else "mistake"
        norm = lemma.strip().lower()

        # Check existing word
        w_res = await session.execute(select(Word).where(Word.normalized == norm))
        word = w_res.scalar_one_or_none()
        if not word:
            word = Word(
                lemma=lemma,
                normalized=norm,
                translation_ru=mistake.original[:120],
                cefr_level=user.cefr_level,
                definition_en=mistake.explanation or mistake.correction,
            )
            session.add(word)
            await session.flush()

        # Link word to mistake
        mistake.word_id = word.id

    # Create Example sentence for the cloze card
    sentence_en = mistake.correction if len(mistake.correction) > 10 else f"Always remember: {mistake.correction}"
    example = Example(
        word_id=word.id,
        sentence_en=sentence_en,
        sentence_ru=mistake.explanation or mistake.original,
        cefr_level=user.cefr_level,
        is_ai_generated=False,
    )
    session.add(example)
    await session.flush()

    # Check if cloze card already exists for this word
    c_res = await session.execute(
        select(Card).where(
            Card.user_id == user.id,
            Card.word_id == word.id,
            Card.card_type == "cloze",
        )
    )
    existing_card = c_res.scalar_one_or_none()

    now_utc = datetime.now(UTC)
    state_data = new_card_state(now_utc)

    if existing_card:
        existing_card.example_id = example.id
        existing_card.due_at = now_utc
        existing_card.source = "mistake"
        existing_card.notes = f"Updated from mistake #{mistake.id}: {mistake.original} -> {mistake.correction}"
        await session.commit()
        return ConvertMistakeResponse(
            card_id=existing_card.id,
            message="Существующая карточка с пропуском обновлена и добавлена в очередь повторения",
        )

    card = Card(
        user_id=user.id,
        word_id=word.id,
        example_id=example.id,
        card_type="cloze",
        source="mistake",
        status="learning",
        fsrs_state=state_data["fsrs_state"],
        due_at=now_utc,
        stability=state_data["stability"],
        difficulty=state_data["difficulty"],
        step=state_data["step"],
        state=state_data["state"],
        notes=f"Created from mistake #{mistake.id}: {mistake.original} -> {mistake.correction}",
    )
    session.add(card)
    await session.commit()

    return ConvertMistakeResponse(
        card_id=card.id,
        message="Карточка с пропуском (Cloze) успешно создана и добавлена в очередь повторения",
    )
