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
            select(User.telegram_id, func.count(Card.id))
            .join(Card, Card.user_id == User.id)
            .where(
                User.reminder_hour == current_hour,
                User.telegram_id.is_not(None),
                Card.due_at <= now_utc,
            )
            .group_by(User.id, User.telegram_id)
        )
        rows = (await session.execute(stmt)).all()

    for telegram_id, due_count in rows:
        if due_count <= 0:
            continue
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
            continue


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
