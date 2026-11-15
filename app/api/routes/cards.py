from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_llm_service
from app.api.schemas import (
    CardOut,
    CardTypesResponse,
    ExampleOut,
    ExtractedWordOut,
    ReviewSubmitRequest,
    ReviewSubmitResponse,
    SentenceAnalyzeRequest,
    SentenceAnalyzeResponse,
    UpdateCardTypesRequest,
    UserStatsResponse,
    WordOut,
)
from app.db.models import Card, User
from app.db.session import get_db
from app.services.llm import LLMNotConfiguredError, LLMService
from app.services.review_engine import ALL_CARD_TYPES
from app.services.vocabulary import (
    extract_new_words_from_sentence,
    get_due_cards,
    get_user_stats,
    submit_review,
)

router = APIRouter(prefix="/api/v1", tags=["vocabulary"])


def _card_to_out(card: Card) -> CardOut:
    return CardOut(
        id=card.id,
        card_type=card.card_type,
        due_at=card.due_at,
        state=card.state,
        reps=card.reps,
        lapses=card.lapses,
        word=WordOut(
            id=card.word.id,
            lemma=card.word.lemma,
            transcription=card.word.transcription,
            part_of_speech=card.word.part_of_speech,
            cefr_level=card.word.cefr_level,
            translation_ru=card.word.translation_ru,
            definition_en=card.word.definition_en,
            collocations=card.word.collocations,
            synonyms=card.word.synonyms,
            antonyms=card.word.antonyms,
            grammar_note=card.word.grammar_note,
        ),
        example=(
            ExampleOut(
                id=card.example.id,
                sentence_en=card.example.sentence_en,
                sentence_ru=card.example.sentence_ru,
            )
            if card.example
            else None
        ),
    )


@router.post("/sentences", response_model=SentenceAnalyzeResponse)
async def analyze_sentence(
    payload: SentenceAnalyzeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> SentenceAnalyzeResponse:
    try:
        words = await extract_new_words_from_sentence(
            session=session,
            user=user,
            sentence=payload.sentence,
            llm_service=llm_service,
        )
        await session.commit()
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return SentenceAnalyzeResponse(words=[ExtractedWordOut(**w.model_dump()) for w in words])


@router.get("/cards/due", response_model=list[CardOut])
async def list_due_cards(
    limit: int = Query(default=10, ge=1, le=50),
    card_type: str | None = Query(default=None),
    interleave: bool = Query(default=True),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[CardOut]:
    cards = await get_due_cards(
        session=session,
        user_id=user.id,
        limit=limit,
        card_type=card_type,
        interleave=interleave,
    )
    return [_card_to_out(c) for c in cards]


@router.get("/cards/types", response_model=CardTypesResponse)
async def get_card_types(
    user: User = Depends(get_current_user),
) -> CardTypesResponse:
    active = getattr(user, "active_card_types", None) or ALL_CARD_TYPES
    return CardTypesResponse(
        active_card_types=active,
        available_types=ALL_CARD_TYPES,
    )


@router.put("/cards/types", response_model=CardTypesResponse)
async def update_card_types(
    payload: UpdateCardTypesRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CardTypesResponse:
    valid_types = [t for t in payload.card_types if t in ALL_CARD_TYPES]
    if not valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid card type must be selected",
        )
    user.active_card_types = valid_types
    await session.commit()
    return CardTypesResponse(
        active_card_types=valid_types,
        available_types=ALL_CARD_TYPES,
    )


@router.post("/cards/{card_id}/review", response_model=ReviewSubmitResponse)
async def review_card(
    card_id: int,
    payload: ReviewSubmitRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReviewSubmitResponse:
    try:
        card, _review = await submit_review(
            session=session,
            user_id=user.id,
            card_id=card_id,
            rating=payload.rating,
            response_time_ms=payload.response_time_ms,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return ReviewSubmitResponse(
        card_id=card.id,
        next_due_at=card.due_at,
        state=card.state,
        reps=card.reps,
        lapses=card.lapses,
    )


@router.get("/stats", response_model=UserStatsResponse)
async def get_stats(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserStatsResponse:
    stats = await get_user_stats(session=session, user_id=user.id)
    return UserStatsResponse(**stats)
