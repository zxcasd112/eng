import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.auth import router as auth_router
from app.api.routes.cards import router as cards_router
from app.api.routes.content import router as content_router
from app.api.routes.explain import router as explain_router
from app.api.routes.health import router as health_router
from app.api.routes.mistakes import router as mistakes_router
from app.api.routes.practice import router as practice_router
from app.api.routes.profile import router as profile_router
from app.api.routes.quiz import router as quiz_router
from app.api.routes.sources import router as sources_router
from app.api.routes.tutor import router as tutor_router
from app.api.routes.words import router as words_router
from app.config import get_settings
from app.db.session import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    await init_db()
    try:
        from sqlalchemy import func, select

        from app.db.models import Word
        from app.db.session import AsyncSessionLocal
        from scripts.seed_lessons import seed_all_lessons

        async with AsyncSessionLocal() as session:
            count = await session.scalar(select(func.count(Word.id)))
            if not count:
                await seed_all_lessons()
    except (OSError, RuntimeError) as err:
        logger.warning("Could not auto-seed default lessons: %s", err)

    bot_task: asyncio.Task | None = None
    bot_instance = None
    dp_instance = None
    scheduler_instance = None

    is_test_env = (
        "pytest" in sys.modules
        or os.environ.get("PYTEST_CURRENT_TEST") is not None
    ) and not os.environ.get("FORCE_INTEGRATED_BOT_TEST")

    has_token = (
        bool(settings.telegram_bot_token)
        and not settings.telegram_bot_token.startswith("your_")
        and not settings.telegram_bot_token.startswith("test_")
        and "TEST" not in settings.telegram_bot_token
    )

    if settings.run_bot_in_api and has_token and not is_test_env:
        try:
            from aiogram import Bot, Dispatcher

            from app.bot.handlers.quiz import router as quiz_router
            from app.bot.handlers.review import router as review_router
            from app.bot.handlers.start import router as start_router
            from app.bot.handlers.words import router as words_router
            from app.bot.scheduler import create_scheduler

            bot_instance = Bot(token=settings.telegram_bot_token)
            dp_instance = Dispatcher()
            dp_instance.include_router(start_router)
            dp_instance.include_router(review_router)
            dp_instance.include_router(quiz_router)
            dp_instance.include_router(words_router)

            if settings.review_reminder_enabled:
                scheduler_instance = create_scheduler(bot_instance)
                scheduler_instance.start()

            bot_task = asyncio.create_task(
                dp_instance.start_polling(bot_instance, handle_signals=False)
            )
            logger.info("Integrated Telegram bot polling started successfully")
        except Exception:
            logger.exception("Failed to start integrated Telegram bot")

    yield

    if scheduler_instance is not None:
        try:
            scheduler_instance.shutdown(wait=False)
        except (RuntimeError, OSError) as exc:
            logger.debug("Error shutting down scheduler: %s", exc)

    if dp_instance is not None and bot_task is not None:
        try:
            await dp_instance.stop_polling()
        except (RuntimeError, OSError) as exc:
            logger.debug("Error stopping bot polling: %s", exc)
        bot_task.cancel()
        try:
            await bot_task
        except (asyncio.CancelledError, RuntimeError, OSError) as exc:
            logger.debug("Bot task cancellation finished: %s", exc)

    if bot_instance is not None:
        try:
            await bot_instance.session.close()
        except (RuntimeError, OSError) as exc:
            logger.debug("Error closing bot session: %s", exc)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        lifespan=lifespan,
    )

    # Enable CORS configured via environment
    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins else ["http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(cards_router)
    app.include_router(words_router)
    app.include_router(profile_router)
    app.include_router(explain_router)
    app.include_router(quiz_router)
    app.include_router(practice_router)
    app.include_router(mistakes_router)
    app.include_router(content_router)
    app.include_router(tutor_router)
    app.include_router(sources_router)

    # Mount web app static files if they exist
    candidates = [
        Path(__file__).resolve().parent.parent / "web",
        Path(__file__).resolve().parent.parent.parent / "web" / "dist",
    ]
    for web_dir in candidates:
        if web_dir.exists():
            app_html = web_dir / "app.html"
            if app_html.exists():

                def _make_app_handler(target_file: Path):
                    async def serve_app(full_path: str = ""):
                        return FileResponse(target_file)

                    return serve_app

                handler = _make_app_handler(app_html)
                app.get("/app")(handler)
                app.get("/app/{full_path:path}")(handler)

            app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
            break

    return app


app = create_app()
