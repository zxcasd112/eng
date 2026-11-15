from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    RecommendationItem,
    UpdateProfileRequest,
    UserAnalyticsResponse,
    UserProfileResponse,
    WordOut,
)
from app.db.models import User
from app.db.session import get_db
from app.services.analytics import get_user_analytics, get_user_recommendations
from app.services.cefr import normalize_cefr
from app.services.email_service import verify_unsubscribe_token
from app.services.review_engine import ALL_CARD_TYPES

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("", response_model=UserProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
) -> UserProfileResponse:
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
        reminder_channel=getattr(user, "reminder_channel", "telegram") or "telegram",
        active_card_types=getattr(user, "active_card_types", None) or ALL_CARD_TYPES,
    )


@router.patch("", response_model=UserProfileResponse)
async def update_profile(
    payload: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserProfileResponse:
    if payload.cefr_level is not None:
        user.cefr_level = normalize_cefr(payload.cefr_level)
    if payload.daily_goal is not None:
        user.daily_goal = max(1, payload.daily_goal)
    if payload.timezone is not None:
        user.timezone = payload.timezone.strip()
    if payload.reminder_hour is not None:
        user.reminder_hour = payload.reminder_hour
    if payload.reminder_channel is not None and payload.reminder_channel in ("telegram", "email", "both"):
        user.reminder_channel = payload.reminder_channel
    if payload.email is not None:
        user.email = payload.email.strip().lower() if payload.email.strip() else None
    if payload.active_card_types is not None:
        valid_types = [t for t in payload.active_card_types if t in ALL_CARD_TYPES]
        if valid_types:
            user.active_card_types = valid_types

    await session.commit()
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
        reminder_channel=getattr(user, "reminder_channel", "telegram") or "telegram",
        active_card_types=getattr(user, "active_card_types", None) or ALL_CARD_TYPES,
    )


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_email(
    token: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    verified = verify_unsubscribe_token(token)
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Недействительный или устаревший токен отписки",
        )

    user_id, _email = verified
    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    # Disable email channel (switch to telegram)
    user.reminder_channel = "telegram"
    await session.commit()

    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
          <meta charset="utf-8">
          <title>Отписка от напоминаний — ENG Tutor</title>
          <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0c; color: #ededed; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
            .card { background: #18181b; border: 1px solid #27272a; border-radius: 12px; padding: 32px; max-width: 440px; text-align: center; }
            .icon { font-size: 40px; margin-bottom: 12px; }
            h2 { margin: 0 0 10px 0; color: #fff; font-size: 20px; }
            p { color: #a1a1aa; font-size: 14px; line-height: 1.6; margin: 0 0 20px 0; }
            a { display: inline-block; background: #22c55e; color: #000; text-decoration: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; font-size: 14px; }
          </style>
        </head>
        <body>
          <div class="card">
            <div class="icon">✓</div>
            <h2>Вы успешно отписались</h2>
            <p>Email-напоминания о повторении слов отключены. Вы всегда можете включить их снова в настройках профиля или продолжить обучение в Telegram.</p>
            <a href="/app">Вернуться в кабинет</a>
          </div>
        </body>
        </html>
        """
    )


@router.get("/analytics", response_model=UserAnalyticsResponse)
async def get_analytics(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserAnalyticsResponse:
    analytics_data = await get_user_analytics(
        session=session, user_id=user.id, user_tz=user.timezone
    )
    return UserAnalyticsResponse(**analytics_data)


@router.get("/recommendations", response_model=list[RecommendationItem])
async def get_recommendations(
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[RecommendationItem]:
    items = await get_user_recommendations(session=session, user=user, limit=limit)
    return [
        RecommendationItem(
            word=WordOut(**item["word"]),
            score=item["score"],
            reasons=item["reasons"],
        )
        for item in items
    ]
