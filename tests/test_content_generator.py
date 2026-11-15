import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.models import SavedText
from app.db.session import get_db
from app.services.llm import LLMService


@pytest.fixture
async def test_env(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-32-chars-long-minimum!")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999999:TEST_BOT_TOKEN")
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    def override_llm():
        return LLMService(client=None)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_service] = override_llm

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session_factory

    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_content_generator_and_saved_texts(test_env):
    client, session_factory = test_env

    # 1. Login user
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "reader@test.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "reader@test.com", "code": code})

    # 2. Generate content (fallback/offline mode)
    gen_resp = await client.post(
        "/api/v1/content/generate",
        json={
            "cefr_level": "B2",
            "topic": "Machine Learning",
            "word_count": 120,
            "format": "text",
            "target_words": ["algorithm", "neural", "precision"],
        },
    )
    assert gen_resp.status_code == 200
    data = gen_resp.json()
    assert "title" in data
    assert "text" in data
    assert len(data["comprehension_questions"]) >= 1
    text_id = data["id"]

    # 3. Verify in database
    async with session_factory() as session:
        t_res = await session.execute(select(SavedText).where(SavedText.id == text_id))
        saved = t_res.scalar_one_or_none()
        assert saved is not None
        assert saved.topic == "Machine Learning"
        assert saved.cefr_level == "B2"

    # 4. Check list saved texts endpoint
    list_resp = await client.get("/api/v1/content/texts")
    assert list_resp.status_code == 200
    texts = list_resp.json()
    assert len(texts) == 1
    assert texts[0]["id"] == text_id

    # 5. Check get single text endpoint
    get_resp = await client.get(f"/api/v1/content/texts/{text_id}")
    assert get_resp.status_code == 200
    single = get_resp.json()
    assert single["title"] == data["title"]
    assert len(single["comprehension_questions"]) == len(data["comprehension_questions"])
