import hashlib
import hmac
import time

from app.services.auth import create_access_token, decode_access_token, verify_telegram_login


def _sign_telegram_payload(payload: dict, bot_token: str) -> dict:
    signed = dict(payload)
    items = [f"{k}={v}" for k, v in sorted(signed.items()) if v is not None]
    check_str = "\n".join(items)
    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    signed["hash"] = hmac.new(secret, check_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return signed


def test_verify_telegram_login_valid_and_tampered():
    token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    payload = _sign_telegram_payload(
        {
            "id": 424242,
            "first_name": "Alice",
            "username": "alice_en",
            "auth_date": int(time.time()),
        },
        bot_token=token,
    )
    assert verify_telegram_login(payload, bot_token=token) is True

    tampered = dict(payload)
    tampered["first_name"] = "Mallory"
    assert verify_telegram_login(tampered, bot_token=token) is False


def test_verify_telegram_login_rejects_expired():
    token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    payload = _sign_telegram_payload(
        {
            "id": 424242,
            "auth_date": int(time.time()) - 200000,
        },
        bot_token=token,
    )
    assert verify_telegram_login(payload, bot_token=token, max_age_seconds=86400) is False


def test_jwt_roundtrip():
    token = create_access_token(user_id=7, telegram_id=999000)
    claims = decode_access_token(token)
    assert claims["sub"] == "7"
    assert claims["tg_id"] == 999000
