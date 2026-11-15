import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards import card_types_kb, cefr_level_kb
from app.db.models import User
from app.db.session import AsyncSessionLocal
from app.services.llm import LLMService
from app.services.review_engine import ALL_CARD_TYPES
from app.services.vocabulary import (
    get_or_create_user_by_telegram,
    get_user_stats,
    get_word_explanation,
)

logger = logging.getLogger(__name__)
router = Router(name="start")
_llm_service = LLMService()

WELCOME_TEXT = (
    "👋 <b>Привет, {name}!</b>\n\n"
    "Я помогу учить английские слова по методу интервального повторения <b>FSRS</b>, "
    "контекстного обучения и активного воспоминания.\n\n"
    "<b>Как пользоваться:</b>\n"
    "• Отправь <b>слово или фразу</b> — я переведу, добавлю транскрипцию, пример, озвучку, "
    "коллокации и создам карточки разных типов.\n"
    "• Отправь <b>целое предложение</b> из книги или статьи — я выделю новые слова и предложу добавить их в колоду.\n\n"
    "<b>Команды:</b>\n"
    "/review — повторить карточки на сегодня (чередование типов)\n"
    "/quiz — тесты: множественный выбор, собери предложение, подбор пар\n"
    "/explain &lt;слово&gt; — глубокий грамматический разбор и синонимы\n"
    "/cardtypes — настроить активные типы карточек\n"
    "/stats — твой прогресс, retention и streak\n"
    "/level — выбрать уровень (сейчас: <b>{level}</b>)\n"
    "/reminder — настроить время напоминаний (сейчас: <b>{reminder}</b>)"
)


def _format_reminder(hour: int | None) -> str:
    return f"{hour:02d}:00 UTC" if hour is not None else "выкл"


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if not message.from_user:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await session.commit()

    name = escape(message.from_user.first_name or "друг")
    await message.answer(
        WELCOME_TEXT.format(
            name=name,
            level=escape(user.cefr_level),
            reminder=_format_reminder(user.reminder_hour),
        ),
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Команды бота:</b>\n"
        "/review — начать тренировку (active recall + FSRS + чередование типов)\n"
        "/quiz — интерактивные тесты (выбор, составление предложения, пары)\n"
        "/explain &lt;слово&gt; — разбор грамматики, предлогов, коллокаций и синонимов\n"
        "/cardtypes — включить/отключить типы карточек (EN➔RU, RU➔EN, cloze, аудио)\n"
        "/stats — статистика обучения и retention\n"
        "/level — выбрать уровень CEFR (A1–C2)\n"
        "/reminder 19 — напоминать в 19:00 UTC (или /reminder off)\n\n"
        "Просто напиши любое английское слово, фразу или предложение!",
        parse_mode="HTML",
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not message.from_user:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        stats = await get_user_stats(session, user.id)
        await session.commit()

    breakdown = stats.get("card_types_breakdown", {})
    breakdown_str = ", ".join(f"{k}: {v}" for k, v in breakdown.items()) if breakdown else "нет"

    await message.answer(
        "📊 <b>Твоя статистика:</b>\n\n"
        f"🃏 Всего карточек: <b>{stats['total_cards']}</b>\n"
        f"⏰ К повторению сейчас: <b>{stats['due_cards']}</b>\n"
        f"📅 Повторено сегодня: <b>{stats['reviewed_today']}</b>\n"
        f"🔥 Серия дней (streak): <b>{stats['streak_days']}</b>\n"
        f"🎯 Retention: <b>{stats['retention_percent']}%</b>\n"
        f"📁 По типам: {breakdown_str}",
        parse_mode="HTML",
    )


@router.message(Command("cardtypes"))
async def cmd_card_types(message: Message) -> None:
    if not message.from_user:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=message.from_user.id,
        )
        active = user.active_card_types or list(ALL_CARD_TYPES)
        await session.commit()

    await message.answer(
        "⚙️ <b>Типы карточек для повторений:</b>\n\n"
        "Нажимай на кнопки, чтобы включить или выключить нужные форматы карточек в колоде:",
        parse_mode="HTML",
        reply_markup=card_types_kb(active),
    )


@router.callback_query(F.data.startswith("ct:toggle:"))
async def cb_toggle_card_type(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    c_type = callback.data.split(":", 2)[2]

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=callback.from_user.id,
        )
        current = list(user.active_card_types or ALL_CARD_TYPES)
        if c_type in current:
            if len(current) > 1:
                current.remove(c_type)
            else:
                await callback.answer(
                    "Хотя бы один тип карточек должен быть активен!", show_alert=True
                )
                return
        else:
            current.append(c_type)

        user.active_card_types = current
        await session.commit()

    await callback.answer(f"Обновлено: {c_type}")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=card_types_kb(current))


@router.message(Command("explain"))
async def cmd_explain(message: Message) -> None:
    if not message.from_user or not message.text:
        return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Укажи слово для разбора, например: <code>/explain versatile</code>", parse_mode="HTML"
        )
        return

    target = parts[1].strip()
    wait_msg = await message.answer(
        f"⏳ Готовлю подробный разбор для <b>{escape(target)}</b>...", parse_mode="HTML"
    )

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=message.from_user.id,
        )
        try:
            exp = await get_word_explanation(session, user, target, _llm_service)
            await session.commit()
        except Exception:
            logger.exception("Failed to get word explanation for target=%s", target)
            await wait_msg.edit_text("Не удалось получить разбор от LLM. Проверь настройки .env.")
            return

    lines = [
        f"📖 <b>Разбор слова: {escape(exp.lemma)}</b> [{escape(exp.cefr_level)}]",
        f"🇷🇺 {escape(exp.translation_ru)}",
        "",
    ]
    if exp.grammar_rules:
        lines.append("⚡ <b>Грамматика:</b>")
        for g in exp.grammar_rules[:3]:
            lines.append(f"• {escape(g)}")
        lines.append("")

    if exp.prepositions_and_patterns:
        lines.append("📌 <b>Предлоги и паттерны:</b>")
        for p in exp.prepositions_and_patterns[:3]:
            lines.append(f"• {escape(p)}")
        lines.append("")

    if exp.collocations:
        lines.append("🔗 <b>Коллокации:</b>")
        for c in exp.collocations[:4]:
            lines.append(f"• <i>{escape(c)}</i>")
        lines.append("")

    if exp.synonyms_with_nuances:
        lines.append("🔄 <b>Синонимы:</b>")
        for s in exp.synonyms_with_nuances[:3]:
            lines.append(f"• {escape(s)}")
        lines.append("")

    if exp.common_mistakes:
        lines.append("⚠️ <b>Ошибки:</b>")
        for m in exp.common_mistakes[:2]:
            lines.append(f"• {escape(m)}")

    await wait_msg.edit_text("\n".join(lines), parse_mode="HTML")


@router.message(Command("level"))
async def cmd_level(message: Message) -> None:
    await message.answer(
        "Выбери свой текущий уровень английского (CEFR), чтобы примеры подбирались точнее:",
        reply_markup=cefr_level_kb(),
    )


@router.callback_query(F.data.startswith("lvl:"))
async def cb_set_level(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    level = callback.data.split(":", 1)[1]
    if level not in {"A1", "A2", "B1", "B2", "C1", "C2"}:
        await callback.answer("Неизвестный уровень", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=callback.from_user.id,
        )
        user.cefr_level = level
        await session.commit()

    await callback.answer(f"Уровень обновлён: {level}")
    if callback.message:
        await callback.message.edit_text(
            f"✅ Уровень установлен: <b>{level}</b>",
            parse_mode="HTML",
        )


@router.message(Command("reminder"))
async def cmd_reminder(message: Message) -> None:
    if not message.from_user or not message.text:
        return
    parts = message.text.strip().split()
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = res.scalar_one_or_none()
        if user is None:
            user = await get_or_create_user_by_telegram(
                session=session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )

        if len(parts) == 1:
            await session.commit()
            await message.answer(
                f"Сейчас напоминания: <b>{_format_reminder(user.reminder_hour)}</b>\n"
                "Чтобы изменить, отправь: <code>/reminder 19</code> (час UTC от 0 до 23) или <code>/reminder off</code>.",
                parse_mode="HTML",
            )
            return

        arg = parts[1].lower()
        if arg in {"off", "0ff", "выкл", "disable"}:
            user.reminder_hour = None
            await session.commit()
            await message.answer("🔕 Напоминания отключены.")
            return

        try:
            hour = int(arg)
            if not 0 <= hour <= 23:
                raise ValueError
        except ValueError:
            await message.answer(
                "Укажи час от 0 до 23, например: <code>/reminder 19</code>", parse_mode="HTML"
            )
            return

        user.reminder_hour = hour
        await session.commit()
        await message.answer(
            f"🔔 Напоминания установлены на <b>{hour:02d}:00 UTC</b>.", parse_mode="HTML"
        )
