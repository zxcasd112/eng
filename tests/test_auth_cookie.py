import hashlib
import hmac
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.main import create_app
from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db


def _sign_telegram_payload(payload: dict, bot_token: str) -> dict:
    signed = dict(payload)
    items = [f"{k}={v}" for k, v in sorted(signed.items()) if v is not None]
    check_str = "\n".join(items)
    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    signed["hash"] = hmac.new(secret, check_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return signed


@pytest.fixture
async def auth_test_client(monkeypatch):
    bot_token = "123456:TEST_AUTH_TOKEN_SECRET"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, bot_token

    get_settings.cache_clear()
    await engine.dispose()


async def test_telegram_auth_valid_and_cookie_session(auth_test_client):
    client, bot_token = auth_test_client

    # 1. Valid Telegram signature
    payload = _sign_telegram_payload(
        {"id": 112233, "first_name": "Alice", "username": "alice_w", "auth_date": int(time.time())},
        bot_token=bot_token,
    )
    resp = await client.post("/api/v1/auth/telegram", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["telegram_id"] == 112233

    # Check that httpOnly cookie was set in the response
    assert "access_token" in resp.cookies
    token_cookie = resp.cookies["access_token"]
    assert token_cookie == data["access_token"]

    # 2. Access protected endpoint using cookie (WITHOUT Authorization header)
    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["telegram_id"] == 112233
    assert me_data["first_name"] == "Alice"

    # 3. Logout (clears cookie)
    logout_resp = await client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "ok"

    # 4. Verify unauthenticated after logout (cookie removed from client session)
    client.cookies.clear()
    me_after_logout = await client.get("/api/v1/auth/me")
    assert me_after_logout.status_code == 401


async def test_telegram_auth_invalid_signature(auth_test_client):
    client, _bot_token = auth_test_client

    # Bad hash
    bad_payload = {
        "id": 998877,
        "first_name": "Attacker",
        "auth_date": int(time.time()),
        "hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }
    resp = await client.post("/api/v1/auth/telegram", json=bad_payload)
    assert resp.status_code == 401
    assert "Invalid Telegram authentication signature" in resp.json()["detail"]


async def test_telegram_auth_expired_signature(auth_test_client):
    client, bot_token = auth_test_client

    # Expired signature (2 days ago)
    old_payload = _sign_telegram_payload(
        {"id": 445566, "first_name": "OldSession", "auth_date": int(time.time()) - 200000},
        bot_token=bot_token,
    )
    resp = await client.post("/api/v1/auth/telegram", json=old_payload)
    assert resp.status_code == 401


async def test_cookie_secure_flag_in_production(monkeypatch):
    bot_token = "123456:TEST_PROD_AUTH_TOKEN"
    prod_secret = "super-secret-production-key-at-least-32-chars-long"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", prod_secret)
    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = _sign_telegram_payload(
            {"id": 556677, "first_name": "ProdUser", "auth_date": int(time.time())},
            bot_token=bot_token,
        )
        resp = await client.post("/api/v1/auth/telegram", json=payload)
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "secure" in set_cookie.lower()

    get_settings.cache_clear()
    await engine.dispose()
