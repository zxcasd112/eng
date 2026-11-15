import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
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
        yield client

    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_email_otp_flow(test_env):
    client = test_env

    # 1. Send OTP code
    resp = await client.post("/api/v1/auth/email/send-code", json={"email": "student@gmail.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    test_code = data.get("test_code")
    assert test_code is not None
    assert len(test_code) == 6

    # 2. Verify with wrong code
    wrong_resp = await client.post(
        "/api/v1/auth/email/verify-code",
        json={"email": "student@gmail.com", "code": "000000"},
    )
    assert wrong_resp.status_code == 400

    # 3. Verify with correct code
    ok_resp = await client.post(
        "/api/v1/auth/email/verify-code",
        json={"email": "student@gmail.com", "code": test_code},
    )
    assert ok_resp.status_code == 200
    user_data = ok_resp.json()
    assert "user_id" in user_data
    assert "access_token" in client.cookies


@pytest.mark.asyncio
async def test_add_word_with_lemma_and_translation(test_env):
    """Test fixing the [object Object] error when adding words directly from recommendations/reading."""
    client = test_env

    # Login via email
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "learner@gmail.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "learner@gmail.com", "code": code})

    # Add word with lemma and translation_ru (no text field needed)
    resp = await client.post(
        "/api/v1/words",
        json={
            "lemma": "resilience",
            "translation_ru": "устойчивость",
            "cefr_level": "B2",
            "notes": "Learned from reading studio",
        },
    )
    assert resp.status_code in (200, 201)
    word_data = resp.json()
    assert word_data["card"]["word"]["lemma"] == "resilience"
    assert word_data["card"]["word"]["translation_ru"] == "устойчивость"


@pytest.mark.asyncio
async def test_practice_scenarios_and_reviews(test_env):
    client = test_env

    # Login
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "speaker@gmail.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "speaker@gmail.com", "code": code})

    # 1. Scenarios list
    scenarios_resp = await client.get("/api/v1/practice/scenarios")
    assert scenarios_resp.status_code == 200
    scenarios = scenarios_resp.json()
    assert len(scenarios) >= 4
    assert any(s["id"] == "job_interview" for s in scenarios)

    # 2. Writing review
    writing_resp = await client.post(
        "/api/v1/practice/writing/review",
        json={"text": "i am practicing english every day and it helps me a lot with my work."},
    )
    assert writing_resp.status_code == 200
    writing_data = writing_resp.json()
    assert "score" in writing_data
    assert "cefr_estimate" in writing_data
    assert "summary_ru" in writing_data
    assert isinstance(writing_data["corrections"], list)

    # 3. Speaking respond
    speaking_resp = await client.post(
        "/api/v1/practice/speaking/respond",
        json={
            "scenario": "job_interview",
            "user_message": "I have three years of experience building Python microservices.",
            "history": [],
        },
    )
    assert speaking_resp.status_code == 200
    speaking_data = speaking_resp.json()
    assert "ai_message" in speaking_data
    assert len(speaking_data["ai_message"]) > 0
