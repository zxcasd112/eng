import asyncio
import base64
import hashlib
import hmac
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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


def _send_smtp_sync(
    host: str,
    port: int,
    user: str,
    password: str,
    from_email: str,
    use_tls: bool,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"ENG Tutor <{from_email or user}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            if use_tls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email via SMTP to %s: %s", to_email, exc)
        return False


async def _dispatch_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> bool:
    settings = get_settings()
    if settings.smtp_host:
        return await asyncio.to_thread(
            _send_smtp_sync,
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_user,
            settings.smtp_password,
            settings.smtp_from_email,
            settings.smtp_use_tls,
            to_email,
            subject,
            html_body,
            text_body,
        )

    # In development/test or if SMTP is not set up, cleanly log the dispatch
    logger.info(
        "EMAIL DISPATCH (Local / Dev) to %s | Subject: %s | Length: %d",
        to_email,
        subject,
        len(text_body),
    )
    return True


async def send_verification_email(to_email: str, code: str) -> bool:
    """Sends a 6-digit confirmation code to user's email address."""
    subject = f"🔐 ENG Tutor: Ваш код подтверждения — {code}"

    text_body = (
        f"Здравствуйте!\n\n"
        f"Ваш код для входа в ENG Tutor: {code}\n\n"
        f"Код действителен в течение 10 минут.\n"
        f"Если вы не запрашивали данный код, просто проигнорируйте это письмо.\n\n"
        f"С уважением,\nКоманда ENG Tutor\n"
    )

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Код подтверждения ENG Tutor</title>
</head>
<body style="margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #09090b; color: #f4f4f5;">
  <div style="max-width: 520px; margin: 0 auto; background: #18181b; border: 1px solid #27272a; border-radius: 12px; padding: 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.4);">
    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 24px;">
      <span style="font-size: 20px; font-weight: 700; color: #fafafa; letter-spacing: -0.5px;">ENG Tutor</span>
    </div>
    <h2 style="font-size: 18px; font-weight: 600; margin-top: 0; margin-bottom: 12px; color: #fafafa;">Код для входа в кабинет</h2>
    <p style="font-size: 14px; line-height: 1.6; color: #a1a1aa; margin-bottom: 24px;">
      Вы запросили авторизацию по email. Введите указанный ниже 6-значный код на сайте:
    </p>
    <div style="text-align: center; margin: 28px 0;">
      <div style="display: inline-block; font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #f43f5e; background: #27272a; padding: 14px 28px; border-radius: 8px; border: 1px solid #3f3f46; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;">
        {code}
      </div>
    </div>
    <p style="font-size: 13px; color: #71717a; margin-bottom: 20px;">
      ⏳ Код действителен в течение <strong>10 минут</strong>. Не сообщайте его посторонним лицам.
    </p>
    <hr style="border: none; border-top: 1px solid #27272a; margin: 24px 0;">
    <p style="font-size: 12px; color: #52525b; margin: 0;">
      Если вы не запрашивали данный код, просто проигнорируйте это письмо.
    </p>
  </div>
</body>
</html>"""

    return await _dispatch_email(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )


async def send_email_reminder(
    to_email: str, due_count: int, study_url: str, unsubscribe_url: str
) -> bool:
    """Sends an email notification for due FSRS cards."""
    subject = f"⏰ ENG Tutor: У вас {due_count} карточек к повторению сегодня"
    text_body = (
        f"Здравствуйте!\n\n"
        f"В вашей FSRS-колоде ENG Tutor накопилось {due_count} карточек, готовых к повторению.\n"
        f"Регулярное повторение по алгоритму FSRS гарантирует 95% удержания слов в долговременной памяти.\n\n"
        f"Начать сессию повторения:\n{study_url}\n\n"
        f"---\n"
        f"Если вы больше не хотите получать email-напоминания, нажмите ссылку для отписки в 1 клик:\n"
        f"{unsubscribe_url}\n"
    )

    html_body = f"""<!DOCTYPE html>
<html>
<body style="margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #09090b; color: #f4f4f5;">
  <div style="max-width: 520px; margin: 0 auto; background: #18181b; border: 1px solid #27272a; border-radius: 12px; padding: 32px;">
    <h2 style="font-size: 18px; font-weight: 600; margin-top: 0; color: #fafafa;">Карточки готовы к повторению</h2>
    <p style="font-size: 14px; line-height: 1.6; color: #a1a1aa;">
      В вашей FSRS-колоде накопилось <strong>{due_count}</strong> карточек. Повторите их сегодня, чтобы закрепить в долговременной памяти.
    </p>
    <div style="text-align: center; margin: 24px 0;">
      <a href="{study_url}" style="display: inline-block; background: #f43f5e; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 14px;">
        Начать сессию повторения →
      </a>
    </div>
    <hr style="border: none; border-top: 1px solid #27272a; margin: 24px 0;">
    <p style="font-size: 12px; color: #52525b;">
      <a href="{unsubscribe_url}" style="color: #71717a; text-decoration: underline;">Отписаться от email-напоминаний в 1 клик</a>
    </p>
  </div>
</body>
</html>"""

    return await _dispatch_email(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
