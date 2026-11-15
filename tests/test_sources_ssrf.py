from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, Response
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
async def test_ssrf_blocking_private_and_loopback_ips(test_env):
    client, _ = test_env

    # Login
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "ssrf_tester@test.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "ssrf_tester@test.com", "code": code})

    # Test SSRF loopback & private addresses
    forbidden_urls = [
        "http://localhost:8000/internal",
        "http://127.0.0.1:8000/secret",
        "http://127.0.0.1/admin",
        "http://10.0.0.1/keys",
        "http://192.168.1.100/router",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://example.com/file.txt",
    ]

    for url in forbidden_urls:
        resp = await client.post("/api/v1/sources/url", json={"url": url})
        assert resp.status_code == 400, f"URL {url} was not blocked!"
        assert "ssrf" in resp.json()["detail"].lower() or "протокол" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_custom_text_and_valid_url_ingest(test_env):
    client, session_factory = test_env

    # Login
    send_resp = await client.post("/api/v1/auth/email/send-code", json={"email": "ingester@test.com"})
    code = send_resp.json()["test_code"]
    await client.post("/api/v1/auth/email/verify-code", json={"email": "ingester@test.com", "code": code})

    # 1. Custom text ingest
    resp_text = await client.post(
        "/api/v1/sources/text",
        json={
            "title": "My Note on Habits",
            "text": "Consistency in language acquisition is far more impactful than occasional intensive study sessions.",
            "topic": "Language Learning",
            "cefr_level": "B2",
        },
    )
    assert resp_text.status_code == 200
    data_text = resp_text.json()
    assert data_text["source_type"] == "custom"
    assert data_text["title"] == "My Note on Habits"

    # Verify saved in texts table
    async with session_factory() as session:
        s_res = await session.execute(select(SavedText).where(SavedText.id == data_text["id"]))
        saved = s_res.scalar_one_or_none()
        assert saved is not None
        assert saved.source_type == "custom"

    # 2. Mock valid article fetch
    sample_html = """
    <!DOCTYPE html>
    <html>
      <head><title>Deep Work and Mastery</title></head>
      <body>
        <nav><a href="/">Home</a></nav>
        <main>
          <h1>Deep Work and Cognitive Focus</h1>
          <p>Developing deep focus enables knowledge workers to accomplish demanding tasks with exceptional precision.</p>
          <p>By eliminating constant distractions and digital interruptions, learners achieve meaningful breakthroughs.</p>
        </main>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """

    mock_response = Response(
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        text=sample_html,
        request=httpx.Request("GET", "https://93.184.216.34/article"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        resp_url = await client.post(
            "/api/v1/sources/url",
            json={"url": "https://93.184.216.34/article"},
        )
        assert resp_url.status_code == 200
        data_url = resp_url.json()
        assert data_url["source_type"] == "url"
        assert "Deep Work" in data_url["title"]
        assert "breakthroughs" in data_url["body"]
