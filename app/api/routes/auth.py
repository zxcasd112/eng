from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AuthTokenResponse, TelegramAuthPayload
from app.db.session import get_db
from app.services.auth import create_access_token, verify_telegram_login
from app.services.vocabulary import get_or_create_user_by_telegram

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthTokenResponse)
async def telegram_login(
    payload: TelegramAuthPayload,
    session: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    raw = payload.model_dump(exclude_none=True)
    if not verify_telegram_login(raw):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram authentication signature",
        )

    user = await get_or_create_user_by_telegram(
        session=session,
        telegram_id=payload.id,
        username=payload.username,
        first_name=payload.first_name,
    )
    await session.commit()

    token = create_access_token(user_id=user.id, telegram_id=user.telegram_id)
    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        telegram_id=user.telegram_id,
        cefr_level=user.cefr_level,
    )
