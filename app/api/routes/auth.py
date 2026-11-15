from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    AuthTokenResponse,
    EmailAuthPayload,
    GoogleAuthPayload,
    TelegramAuthPayload,
    UserProfileResponse,
)
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.services.auth import (
    create_access_token,
    verify_google_id_token,
    verify_telegram_login,
)
from app.services.review_engine import ALL_CARD_TYPES
from app.services.vocabulary import (
    get_or_create_user_by_email,
    get_or_create_user_by_telegram,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )


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

    token = create_access_token(
        user_id=user.id,
        telegram_id=user.telegram_id,
        email=user.email,
        expires_days=30,
    )
    _set_auth_cookie(response, token)

    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        telegram_id=user.telegram_id,
        email=user.email,
        cefr_level=user.cefr_level,
    )


@router.post("/google", response_model=AuthTokenResponse)
async def google_login(
    payload: GoogleAuthPayload,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    token_data = await verify_google_id_token(payload.credential)
    if not token_data or not token_data.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google credentials or unverified email",
        )

    email = token_data["email"].strip().lower()
    first_name = token_data.get("name") or token_data.get("given_name")

    user = await get_or_create_user_by_email(
        session=session,
        email=email,
        first_name=first_name,
    )
    await session.commit()

    token = create_access_token(
        user_id=user.id,
        telegram_id=user.telegram_id,
        email=user.email,
        expires_days=30,
    )
    _set_auth_cookie(response, token)

    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        telegram_id=user.telegram_id,
        email=user.email,
        cefr_level=user.cefr_level,
    )


@router.post("/email", response_model=AuthTokenResponse)
async def email_login(
    payload: EmailAuthPayload,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Некорректный формат email адреса",
        )

    user = await get_or_create_user_by_email(
        session=session,
        email=email,
    )
    await session.commit()

    token = create_access_token(
        user_id=user.id,
        telegram_id=user.telegram_id,
        email=user.email,
        expires_days=30,
    )
    _set_auth_cookie(response, token)

    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        telegram_id=user.telegram_id,
        email=user.email,
        cefr_level=user.cefr_level,
    )


@router.get("/widget-config")
async def get_widget_config() -> dict[str, str]:
    settings = get_settings()
    return {
        "bot_username": settings.telegram_bot_username or "nigerbbbit_bot",
        "google_client_id": settings.google_client_id,
    }


@router.post("/logout")
async def logout(response: Response) -> dict:
    settings = get_settings()
    response.delete_cookie(
        key="access_token",
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
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

