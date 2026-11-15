from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_llm_service
from app.api.schemas import (
    AddWordRequest,
    AddWordResponse,
    CardOut,
    ExampleOut,
    ImportWordsResponse,
    PaginatedWordsResponse,
    UpdateWordRequest,
    UserWordDetailOut,
    UserWordItemOut,
    WordOut,
)
from app.db.models import Card, User
from app.db.session import get_db
from app.services.llm import LLMNotConfiguredError, LLMService
from app.services.vocabulary import (
    add_word_or_phrase,
    delete_user_word,
    get_user_word_detail,
    get_user_words,
    import_words_csv,
    update_user_word,
)

router = APIRouter(prefix="/api/v1/words", tags=["words"])


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


@router.get("", response_model=PaginatedWordsResponse)
async def list_words(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    cefr_level: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> PaginatedWordsResponse:
    items, total = await get_user_words(
        session=session,
        user_id=user.id,
        page=page,
        page_size=page_size,
        cefr_level=cefr_level,
        status=status,
        search=search,
    )
    total_pages = (total + page_size - 1) // page_size if total else 0
    return PaginatedWordsResponse(
        items=[UserWordItemOut(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=AddWordResponse)
async def add_word(
    payload: AddWordRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> AddWordResponse:
    try:
        result = await add_word_or_phrase(
            session=session,
            user=user,
            text=payload.text,
            llm_service=llm_service,
            source_title=payload.source_title,
            source_type=payload.source or "web",
        )
        await session.commit()
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    result.card.word = result.word
    result.card.example = result.example
    return AddWordResponse(
        created_new_card=result.created_new_card,
        card=_card_to_out(result.card),
    )


@router.post("/import", response_model=ImportWordsResponse)
async def import_words(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ImportWordsResponse:
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("cp1251", errors="replace")

    report = await import_words_csv(
        session=session,
        user=user,
        csv_text=text,
        source_type="import",
    )
    await session.commit()
    return ImportWordsResponse(**report)


@router.get("/{word_id}", response_model=UserWordDetailOut)
async def get_word_detail(
    word_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserWordDetailOut:
    detail = await get_user_word_detail(session=session, user_id=user.id, word_id=word_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word #{word_id} not found in user deck",
        )
    return UserWordDetailOut(**detail)


@router.patch("/{word_id}", response_model=UserWordDetailOut)
async def update_word(
    word_id: int,
    payload: UpdateWordRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserWordDetailOut:
    updated = await update_user_word(
        session=session,
        user_id=user.id,
        word_id=word_id,
        status=payload.status,
        notes=payload.notes,
        cefr_level=payload.cefr_level,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word #{word_id} not found in user deck",
        )
    await session.commit()
    return UserWordDetailOut(**updated)


@router.delete("/{word_id}")
async def delete_word(
    word_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict:
    deleted = await delete_user_word(session=session, user_id=user.id, word_id=word_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word #{word_id} not found in user deck",
        )
    await session.commit()
    return {"status": "ok", "deleted_word_id": word_id}
