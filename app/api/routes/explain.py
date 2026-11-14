from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_llm_service
from app.api.schemas import WordExplainResponse
from app.db.models import User
from app.db.session import get_db
from app.services.llm import LLMNotConfiguredError, LLMService
from app.services.vocabulary import get_word_explanation

router = APIRouter(prefix="/api/v1", tags=["explain"])


@router.get("/explain/{word}", response_model=WordExplainResponse)
async def explain_word_endpoint(
    word: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> WordExplainResponse:
    if not word.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Word cannot be empty",
        )
    try:
        explanation = await get_word_explanation(
            session=session,
            user=user,
            word_or_lemma=word,
            llm_service=llm_service,
        )
        await session.commit()
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return WordExplainResponse(**explanation.model_dump())
