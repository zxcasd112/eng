import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers.quiz import router as quiz_router
from app.bot.handlers.review import router as review_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.words import router as words_router
from app.bot.scheduler import create_scheduler
from app.config import get_settings
from app.db.session import init_db


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings = get_settings()
    if not settings.telegram_bot_token or settings.telegram_bot_token.startswith("your_"):
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. Скопируйте .env.example в .env и укажите токен бота."
        )

    await init_db()

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(start_router)
    dp.include_router(review_router)
    dp.include_router(quiz_router)
    dp.include_router(words_router)

    scheduler = None
    if settings.review_reminder_enabled:
        scheduler = create_scheduler(bot)
        scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
