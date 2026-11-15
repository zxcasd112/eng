from fastapi import APIRouter, Depends, Query
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
        active_card_types=getattr(user, "active_card_types", None) or ALL_CARD_TYPES,
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
