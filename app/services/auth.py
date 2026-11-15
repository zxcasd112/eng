import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.config import get_settings


def verify_telegram_login(
    payload: dict[str, Any],
    bot_token: str | None = None,
    max_age_seconds: int = 86400,
) -> bool:
    settings = get_settings()
    token = bot_token if bot_token is not None else settings.telegram_bot_token
    if not token:
        return False

    received_hash = payload.get("hash")
    auth_date = payload.get("auth_date")
    if not received_hash or not auth_date:
        return False

    try:
        auth_ts = int(auth_date)
    except (TypeError, ValueError):
        return False

    if time.time() - auth_ts > max_age_seconds:
        return False

    data_check_items = [
        f"{k}={v}" for k, v in sorted(payload.items()) if k != "hash" and v is not None
    ]
    data_check_string = "\n".join(data_check_items)

    secret_key = hashlib.sha256(token.encode("utf-8")).digest()
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_hash, str(received_hash))


def create_access_token(user_id: int, telegram_id: int, expires_days: int = 30) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "tg_id": telegram_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=expires_days)).timestamp()),
    }
    return jwt.encode(claims, settings.app_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.app_secret_key, algorithms=["HS256"])
