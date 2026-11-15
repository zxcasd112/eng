import logging
from datetime import UTC, datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from app.bot.keyboards import reminder_prompt_kb
from app.db.models import Card, User
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def send_due_reminders(bot: Bot) -> None:
    now_utc = datetime.now(UTC)
    current_hour = now_utc.hour

    async with AsyncSessionLocal() as session:
        stmt = (
            select(
                User.id,
                User.telegram_id,
                User.email,
                User.reminder_channel,
                func.count(Card.id).label("due_count"),
            )
            .join(Card, Card.user_id == User.id)
            .where(
                User.reminder_hour == current_hour,
                Card.due_at <= now_utc,
            )
            .group_by(User.id, User.telegram_id, User.email, User.reminder_channel)
        )
        rows = (await session.execute(stmt)).all()

    for user_id, telegram_id, email, reminder_channel, due_count in rows:
        if due_count <= 0:
            continue
        channel = (reminder_channel or "telegram").lower()

        # 1. Telegram Dispatch
        if channel in ("telegram", "both") and telegram_id:
            try:
                await bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        f"⏰ <b>Время повторить слова!</b>\n"
                        f"У тебя накопилось карточек к повторению: <b>{due_count}</b>."
                    ),
                    parse_mode="HTML",
                    reply_markup=reminder_prompt_kb(),
                )
            except Exception:
                logger.exception("Failed to send review reminder to telegram_id=%s", telegram_id)

        # 2. Email Dispatch
        if channel in ("email", "both") and email:
            try:
                from app.services.email_service import (
                    generate_unsubscribe_token,
                    send_email_reminder,
                )

                unsub_token = generate_unsubscribe_token(user_id, email)
                study_url = "https://eng-tutor-omuc.onrender.com/app/study"
                unsub_url = f"https://eng-tutor-omuc.onrender.com/api/v1/profile/unsubscribe?token={unsub_token}"
                await send_email_reminder(email, due_count, study_url, unsub_url)
            except Exception:
                logger.exception("Failed to send review email reminder to user_id=%s", user_id)


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        send_due_reminders,
        trigger="cron",
        minute=0,
        args=[bot],
        id="hourly_review_reminders",
        replace_existing=True,
    )
    return scheduler
