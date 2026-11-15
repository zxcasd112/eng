import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_llm_service
from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.models import Card, User
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
async def test_mistakes_journal_and_cloze_conversion(test_env):
    client, session_factory = test_env

    # 1. Login user
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "student@test.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "student@test.com", "code": code})

    # 2. Add word and card
    w_resp = await client.post("/api/v1/words", json={"lemma": "meticulous", "translation_ru": "дотошный"})
    assert w_resp.status_code == 200
    card_id = w_resp.json()["card"]["id"]

    # 3. Simulate Review Again (rating=1) -> Auto-records review mistake
    rev_resp = await client.post(f"/api/v1/cards/{card_id}/review", json={"rating": 1})
    assert rev_resp.status_code == 200

    # 4. Check Mistakes endpoint
    m_resp = await client.get("/api/v1/mistakes")
    assert m_resp.status_code == 200
    mistakes = m_resp.json()
    assert len(mistakes) == 1
    assert mistakes[0]["source"] == "review"
    assert "meticulous" in mistakes[0]["original"].lower()
    mistake_id = mistakes[0]["id"]

    # 5. Convert mistake to cloze card
    conv_resp = await client.post(f"/api/v1/mistakes/{mistake_id}/to-cards")
    assert conv_resp.status_code == 200
    conv_data = conv_resp.json()
    assert "card_id" in conv_data

    # 6. Verify cloze card in database
    async with session_factory() as session:
        u_res = await session.execute(select(User).where(User.email == "student@test.com"))
        user = u_res.scalar_one()

        c_res = await session.execute(
            select(Card).where(Card.user_id == user.id, Card.card_type == "cloze")
        )
        cloze_card = c_res.scalar_one_or_none()
        assert cloze_card is not None
        assert cloze_card.source == "mistake"

    # 7. Check that listing mistakes now reports has_card = True
    m_resp2 = await client.get("/api/v1/mistakes")
    assert m_resp2.status_code == 200
    assert m_resp2.json()[0]["has_card"] is True

    # 8. Test filtering by source
    m_filter_resp = await client.get("/api/v1/mistakes?source=writing")
    assert m_filter_resp.status_code == 200
    assert len(m_filter_resp.json()) == 0

    m_filter_review = await client.get("/api/v1/mistakes?source=review")
    assert m_filter_review.status_code == 200
    assert len(m_filter_review.json()) == 1

    # 9. Test writing correction creates writing mistake
    writing_resp = await client.post(
        "/api/v1/practice/writing/review",
        json={"text": "i have went to London yesterday. It was very nice."},
    )
    assert writing_resp.status_code == 200
    m_writing = await client.get("/api/v1/mistakes?source=writing")
    assert m_writing.status_code == 200
    assert len(m_writing.json()) >= 1
