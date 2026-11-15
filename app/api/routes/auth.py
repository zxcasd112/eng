from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import AuthTokenResponse, TelegramAuthPayload, UserProfileResponse
from app.db.models import User
from app.db.session import get_db
from app.services.auth import create_access_token, verify_telegram_login
from app.services.review_engine import ALL_CARD_TYPES
from app.services.vocabulary import get_or_create_user_by_telegram

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthTokenResponse)
async def telegram_login(
    payload: TelegramAuthPayload,
    response: Response,
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

    token = create_access_token(user_id=user.id, telegram_id=user.telegram_id, expires_days=30)

    # Set httpOnly cookie for web browser session (30 days)
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True behind HTTPS reverse proxy automatically
        path="/",
    )

    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        telegram_id=user.telegram_id,
        cefr_level=user.cefr_level,
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(key="access_token", path="/")
    return {"status": "ok", "message": "Successfully logged out"}


@router.get("/me", response_model=UserProfileResponse)
async def get_me(user: User = Depends(get_current_user)) -> UserProfileResponse:
    return UserProfileResponse(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        email=getattr(user, "email", None),
        cefr_level=user.cefr_level,
        daily_goal=user.daily_goal,
        timezone=user.timezone,
        reminder_hour=user.reminder_hour,
        active_card_types=getattr(user, "active_card_types", None) or ALL_CARD_TYPES,
    )

