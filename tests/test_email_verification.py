from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.api.routes.auth import _EMAIL_CODES
from app.config import get_settings
from app.services.email_service import send_verification_email


@pytest.mark.asyncio
async def test_send_verification_email_dispatches():
    # Test local / dev fallback dispatch (no SMTP configured)
    res = await send_verification_email("student@example.com", "654321")
    assert res is True


@pytest.mark.asyncio
async def test_email_otp_send_and_verify_flow():
    app = create_app()
    test_email = "alex_learner@gmail.com"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Request verification code
        resp = await client.post(
            "/api/v1/auth/email/send-code",
            json={"email": test_email},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert test_email in data["message"]
        assert test_email in _EMAIL_CODES

        code, _ = _EMAIL_CODES[test_email]
        assert len(code) == 6

        # 2. Verify with invalid code
        fail_resp = await client.post(
            "/api/v1/auth/email/verify-code",
            json={"email": test_email, "code": "000000"},
        )
        assert fail_resp.status_code == 400

        # 3. Verify with correct code
        ok_resp = await client.post(
            "/api/v1/auth/email/verify-code",
            json={"email": test_email, "code": code},
        )
        assert ok_resp.status_code == 200
        auth_data = ok_resp.json()
        assert auth_data["email"] == test_email
        assert "access_token" in auth_data
        assert auth_data["user_id"] > 0


@pytest.mark.asyncio
async def test_smtp_dispatch_when_configured():
    settings = get_settings()
    with (
        patch.object(settings, "smtp_host", "smtp.gmail.com"),
        patch.object(settings, "smtp_user", "test@gmail.com"),
        patch.object(settings, "smtp_password", "secretpass"),
        patch("app.services.email_service._send_smtp_sync", return_value=True) as mock_send,
    ):
        res = await send_verification_email("target@example.com", "112233")
        assert res is True
        assert mock_send.called
        assert mock_send.call_args[0][6] == "target@example.com"
        assert "112233" in mock_send.call_args[0][7]  # Subject has code
