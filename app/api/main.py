import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes.auth import router as auth_router
from app.api.routes.cards import router as cards_router
from app.api.routes.explain import router as explain_router
from app.api.routes.health import router as health_router
from app.api.routes.quiz import router as quiz_router
from app.config import get_settings
from app.db.session import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings().ensure_dirs()
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
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        lifespan=lifespan,
    )

    # Enable CORS for local web development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(cards_router)
    app.include_router(explain_router)
    app.include_router(quiz_router)

    # Mount web app static files if they exist
    candidates = [
        Path(__file__).resolve().parent.parent / "web",
        Path(__file__).resolve().parent.parent.parent / "web" / "dist",
    ]
    for web_dir in candidates:
        if web_dir.exists():
            app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
            break

    return app


app = create_app()
