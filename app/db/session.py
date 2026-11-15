from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.base import Base


def create_engine_from_url(database_url: str) -> AsyncEngine:
    # Normalize Postgres URLs provided by cloud hosts (Render, Railway, Heroku)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://") and not database_url.startswith("postgresql+"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    kwargs: dict = {"echo": False, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs.pop("pool_pre_ping", None)
    return create_async_engine(database_url, **kwargs)


settings = get_settings()
engine = create_engine_from_url(settings.database_url)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
