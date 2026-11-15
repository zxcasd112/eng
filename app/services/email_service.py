import base64
import hashlib
import hmac
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def generate_unsubscribe_token(user_id: int, email: str) -> str:
    settings = get_settings()
    secret = (settings.app_secret_key or "default-secret-salt-32-chars-long!").encode()
    payload = f"{user_id}:{email.strip().lower()}"
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:24]
    combined = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(combined.encode()).decode()


def verify_unsubscribe_token(token: str) -> tuple[int, str] | None:
    settings = get_settings()
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        user_id_str, email, sig = parts
        user_id = int(user_id_str)

        secret = (settings.app_secret_key or "default-secret-salt-32-chars-long!").encode()
        expected_sig = hmac.new(secret, f"{user_id}:{email}".encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        return user_id, email
    except Exception:  # noqa: BLE001
        return None


async def send_email_reminder(
    to_email: str, due_count: int, study_url: str, unsubscribe_url: str
) -> bool:
    """Sends an email notification for due FSRS cards.

    In development/test, logs the message cleanly.
    """
    subject = f"⏰ ENG Tutor: У вас {due_count} карточек к повторению сегодня"
    body = (
        f"Здравствуйте!\n\n"
        f"В вашей FSRS-колоде ENG Tutor накопилось {due_count} карточек, готовых к повторению.\n"
        f"Регулярное повторение по алгоритму FSRS гарантирует 95% удержания слов в долговременной памяти.\n\n"
        f"Начать сессию повторения:\n{study_url}\n\n"
        f"---\n"
        f"Если вы больше не хотите получать email-напоминания, нажмите ссылку для отписки в 1 клик:\n"
        f"{unsubscribe_url}\n"
    )

    logger.info(
        "EMAIL DISPATCH to %s | Subject: %s | Study URL: %s | Unsub: %s | Length: %d",
        to_email,
        subject,
        study_url,
        unsubscribe_url,
        len(body),
    )
    return True
