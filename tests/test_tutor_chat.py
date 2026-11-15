import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.models import LLMUsage, Word
from app.db.session import get_db
from app.services.llm import LLMService


@pytest.fixture
async def test_env(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-32-chars-long-minimum!")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999999:TEST_BOT_TOKEN")
    monkeypatch.setenv("TUTOR_DAILY_LIMIT", "2")
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
async def test_tutor_chat_tools_and_rate_limit(test_env):
    client, session_factory = test_env

    # 1. Login user
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "student_tutor@test.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "student_tutor@test.com", "code": code})

    # 2. First chat request: explain word tool
    resp1 = await client.post(
        "/api/v1/tutor/chat",
        json={"message": "Объясни слово serendipity"},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert "reply" in data1
    assert len(data1["tool_calls_executed"]) >= 1
    assert data1["tool_calls_executed"][0]["tool_name"] == "explain_word"
    assert data1["daily_requests_remaining"] == 1

    # 3. Check LLM usage table in database
    async with session_factory() as session:
        u_res = await session.execute(
            select(LLMUsage).where(LLMUsage.task_type == "tutor_chat")
        )
        usages = u_res.scalars().all()
        assert len(usages) == 1
        assert usages[0].tokens_in > 0

    # 4. Second chat request: add word tool
    resp2 = await client.post(
        "/api/v1/tutor/chat",
        json={"message": "Добавь слово ephemeral"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["daily_requests_remaining"] == 0

    # Verify word was added to deck by tool
    async with session_factory() as session:
        w_res = await session.execute(select(Word).where(Word.lemma == "ephemeral"))
        assert w_res.scalar_one_or_none() is not None

    # 5. Third request exceeds limit (limit is 2) -> 429 Too Many Requests
    resp3 = await client.post(
        "/api/v1/tutor/chat",
        json={"message": "Еще один вопрос"},
    )
    assert resp3.status_code == 429
    assert "лимит" in resp3.json()["detail"].lower()

    # 6. Check history endpoint
    hist_resp = await client.get("/api/v1/tutor/history")
    assert hist_resp.status_code == 200
    assert len(hist_resp.json()) == 2
