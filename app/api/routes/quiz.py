from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_llm_service
from app.api.schemas import (
    MatchingAnswerRequest,
    MatchingAnswerResponse,
    MatchingQuizOut,
    MultipleChoiceAnswerRequest,
    MultipleChoiceAnswerResponse,
    MultipleChoiceQuizOut,
    SentenceScrambleAnswerRequest,
    SentenceScrambleAnswerResponse,
    SentenceScrambleQuizOut,
)
from app.db.models import User
from app.db.session import get_db
from app.services.llm import LLMService
from app.services.quiz_service import (
    create_matching_quiz,
    create_multiple_choice_quiz,
    create_sentence_scramble_quiz,
    verify_matching_pair,
    verify_multiple_choice_answer,
    verify_sentence_scramble_answer,
)

router = APIRouter(prefix="/api/v1/quiz", tags=["quiz"])


@router.get("/multiple-choice", response_model=MultipleChoiceQuizOut | None)
async def get_multiple_choice_quiz(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> MultipleChoiceQuizOut | None:
    q = await create_multiple_choice_quiz(session=session, user_id=user.id, llm_service=llm_service)
    if q is None:
        return None
    return MultipleChoiceQuizOut(
        quiz_id=q.quiz_id,
        word_id=q.word_id,
        lemma=q.lemma,
        context_sentence=q.context_sentence,
        options=q.options,
        cefr_level=q.cefr_level,
    )


@router.post("/multiple-choice/answer", response_model=MultipleChoiceAnswerResponse)
async def answer_multiple_choice(
    payload: MultipleChoiceAnswerRequest,
    _user: User = Depends(get_current_user),
) -> MultipleChoiceAnswerResponse:
    res = verify_multiple_choice_answer(payload.quiz_id, payload.chosen_option)
    if not res.get("valid"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error", "Invalid or expired quiz"),
        )
    return MultipleChoiceAnswerResponse(
        is_correct=res["is_correct"],
        correct_answer=res["correct_answer"],
        lemma=res["lemma"],
    )


@router.get("/scramble", response_model=SentenceScrambleQuizOut)
async def get_sentence_scramble_quiz(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SentenceScrambleQuizOut:
    q = await create_sentence_scramble_quiz(session=session, user_id=user.id)
    if q is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No example sentences found for scramble quiz.",
        )
    return SentenceScrambleQuizOut(
        quiz_id=q.quiz_id,
        word_id=q.word_id,
        original_sentence=q.original_sentence,
        translation_ru=q.translation_ru,
        shuffled_tokens=q.shuffled_tokens,
    )


@router.post("/scramble/answer", response_model=SentenceScrambleAnswerResponse)
async def answer_sentence_scramble(
    payload: SentenceScrambleAnswerRequest,
    _user: User = Depends(get_current_user),
) -> SentenceScrambleAnswerResponse:
    res = verify_sentence_scramble_answer(payload.quiz_id, payload.submitted_sentence)
    if not res.get("valid"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error", "Invalid or expired quiz"),
        )
    return SentenceScrambleAnswerResponse(
        is_correct=res["is_correct"],
        original_sentence=res["original_sentence"],
        translation_ru=res.get("translation_ru"),
    )


@router.get("/matching", response_model=MatchingQuizOut)
async def get_matching_quiz(
    pair_count: int = Query(default=5, ge=3, le=8),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> MatchingQuizOut:
    q = await create_matching_quiz(session=session, user_id=user.id, pair_count=pair_count)
    if q is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Need at least 3 words in your deck for matching quiz.",
        )
    return MatchingQuizOut(
        quiz_id=q.quiz_id,
        shuffled_en=q.shuffled_en,
        shuffled_ru=q.shuffled_ru,
    )


@router.post("/matching/answer", response_model=MatchingAnswerResponse)
async def answer_matching_pair(
    payload: MatchingAnswerRequest,
    _user: User = Depends(get_current_user),
) -> MatchingAnswerResponse:
    res = verify_matching_pair(payload.quiz_id, payload.en_word, payload.ru_translation)
    if not res.get("valid"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error", "Invalid or expired quiz"),
        )
    return MatchingAnswerResponse(
        is_match=res["is_match"],
        en_word=res["en_word"],
        ru_translation=res["ru_translation"],
    )
