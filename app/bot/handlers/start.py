import csv
import io
import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from app.bot.keyboards import (
    card_types_kb,
    cefr_level_kb,
    daily_goal_kb,
    profile_menu_kb,
    recommendation_item_kb,
)
from app.db.models import Card, User, Word
from app.db.session import AsyncSessionLocal
from app.services.analytics import get_user_analytics, get_user_recommendations
from app.services.fsrs_service import new_card_state
from app.services.llm import LLMService
from app.services.review_engine import ALL_CARD_TYPES
from app.services.vocabulary import (
    delete_user_word,
    get_or_create_user_by_telegram,
    get_user_stats,
    get_user_word_detail,
    get_user_words,
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
    "/add &lt;слово&gt; — добавить слово в колоду\n"
    "/learn — умные рекомендации слов для твоего уровня\n"
    "/review — повторить карточки на сегодня (FSRS Active Recall)\n"
    "/list — список слов в твоей колоде\n"
    "/profile — профиль и настройки (уровень, цель, напоминания)\n"
    "/analytics — retention, слабые слова и прогноз нагрузки\n"
    "/quiz — тесты: множественный выбор, собери предложение, пары\n"
    "/explain &lt;слово&gt; — разбор грамматики и синонимов\n"
    "/mywords_export — скачать колоду CSV-файлом\n"
    "/cardtypes — настроить активные типы карточек"
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


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
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

    active_types_labels = [str(t) for t in (user.active_card_types or ALL_CARD_TYPES)]
    text = (
        "👤 <b>Твой профиль и настройки:</b>\n\n"
        f"• <b>Уровень CEFR:</b> {escape(user.cefr_level)}\n"
        f"• <b>Дневная цель:</b> {user.daily_goal} карточек в день\n"
        f"• <b>Часовой пояс:</b> {escape(user.timezone)}\n"
        f"• <b>Напоминания:</b> {_format_reminder(user.reminder_hour)}\n"
        f"• <b>Активные типы карточек:</b> {', '.join(active_types_labels)}\n\n"
        "Выбери параметр для изменения:"
    )
    await message.answer(text, reply_markup=profile_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "prof:level")
async def cb_profile_level(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text(
            "Выбери свой уровень английского по шкале CEFR:",
            reply_markup=cefr_level_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "prof:goal")
async def cb_profile_goal(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text(
            "Выбери дневную цель по количеству повторяемых карточек:",
            reply_markup=daily_goal_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("prof:set_goal:"))
async def cb_set_daily_goal(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    goal_val = int(callback.data.split(":", 2)[2])
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=callback.from_user.id
        )
        user.daily_goal = goal_val
        await session.commit()

    await callback.answer(f"Цель установлена: {goal_val} слов в день!")
    if callback.message:
        await callback.message.edit_text(
            f"✅ Дневная цель успешно обновлена: <b>{goal_val} карточек в день</b>.",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "prof:reminder")
async def cb_profile_reminder(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для настройки времени напоминаний отправь команду, например:\n"
            "<code>/reminder 19</code> (в 19:00 UTC) или <code>/reminder off</code>",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "prof:cardtypes")
async def cb_profile_cardtypes(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=callback.from_user.id
        )
        active = user.active_card_types or list(ALL_CARD_TYPES)
        await session.commit()

    await callback.message.edit_text(
        "Выбери, какие типы карточек использовать при повторении:",
        reply_markup=card_types_kb(active),
    )
    await callback.answer()


@router.message(Command("analytics"))
async def cmd_analytics(message: Message) -> None:
    if not message.from_user:
        return
    wait_msg = await message.answer("⏳ Собираю аналитику твоего обучения...")

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=message.from_user.id
        )
        data = await get_user_analytics(session=session, user_id=user.id)
        await session.commit()

    # 7-day retention calculation
    daily = data.get("retention_daily", [])
    last_7 = daily[-7:] if len(daily) >= 7 else daily
    total_7d_rev = sum(d["reviews_count"] for d in last_7)
    passed_7d_rev = sum(d["passed_count"] for d in last_7)
    ret_7d = round((passed_7d_rev / total_7d_rev) * 100, 1) if total_7d_rev else 0.0

    # Tomorrow's due forecast
    forecast = data.get("workload_forecast_7d", [])
    tomorrow_due = (
        forecast[1]["due_cards_count"]
        if len(forecast) > 1
        else (forecast[0]["due_cards_count"] if forecast else 0)
    )

    # Problem words
    problems = data.get("problem_words", [])[:3]
    problems_lines = []
    if problems:
        for p in problems:
            problems_lines.append(
                f"• <b>{escape(p['lemma'])}</b>: {p['lapses']} ошибок (ср. балл {p['avg_rating']})"
            )
    else:
        problems_lines.append("• <i>Отлично! Проблемных слов с частыми ошибками пока нет.</i>")

    text = (
        "📊 <b>Аналитика обучения (Cognitive Data Science):</b>\n\n"
        f"🎯 <b>Retention за 7 дней:</b> {ret_7d}%\n"
        f"📈 <b>Retention за 30 дней:</b> {data.get('retention_30d', 0.0)}%\n\n"
        f"🔮 <b>Прогноз нагрузки на завтра:</b> {tomorrow_due} карточек к повторению\n\n"
        f"⚠️ <b>Слова, требующие внимания:</b>\n" + "\n".join(problems_lines) + "\n\n"
        "💡 Регулярное повторение карточек по алгоритму FSRS повышает долговременное удержание лексики до 95%."
    )
    await wait_msg.edit_text(text, parse_mode="HTML")


@router.message(Command("learn"))
async def cmd_learn(message: Message) -> None:
    if not message.from_user:
        return
    wait_msg = await message.answer("🔍 Подбираю оптимальные слова для изучения...")

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=message.from_user.id
        )
        recs = await get_user_recommendations(session=session, user=user, limit=5)
        await session.commit()

    if not recs:
        await wait_msg.edit_text(
            "🎉 Все доступные слова уже в твоей колоде! Добавь новые тексты или слова через <code>/add &lt;слово&gt;</code>.",
            parse_mode="HTML",
        )
        return

    await wait_msg.delete()
    intro = (
        f"🎯 <b>Рекомендованные слова для твоего уровня ({escape(user.cefr_level)}):</b>\n"
        "<i>Основано на правиле i+1, частотности и твоих материалах:</i>\n"
    )
    await message.answer(intro, parse_mode="HTML")

    for idx, r in enumerate(recs, start=1):
        w = r["word"]
        reasons_text = " • ".join(escape(rs) for rs in r.get("reasons", []))
        lvl = f"[{escape(w.get('cefr_level') or 'B1')}]"
        card_text = (
            f"<b>{idx}. {escape(w['lemma'])}</b> {lvl}\n"
            f"🇷🇺 {escape(w['translation_ru'])}\n"
            f"💡 <i>{reasons_text}</i>"
        )
        await message.answer(
            card_text, reply_markup=recommendation_item_kb(w["id"]), parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("learn:add:"))
async def cb_learn_add(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    word_id = int(callback.data.split(":", 2)[2])

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=callback.from_user.id
        )
        word = await session.get(Word, word_id)
        if not word:
            await callback.answer("Слово не найдено", show_alert=True)
            return

        active_types = user.active_card_types or list(ALL_CARD_TYPES)
        created_count = 0
        for c_type in active_types:
            card_res = await session.execute(
                select(Card).where(
                    Card.user_id == user.id, Card.word_id == word.id, Card.card_type == c_type
                )
            )
            card = card_res.scalar_one_or_none()
            if card is None:
                st = new_card_state()
                new_card = Card(
                    user_id=user.id,
                    word_id=word.id,
                    card_type=c_type,
                    source="bot_learn",
                    status="learning",
                    fsrs_state=st["fsrs_state"],
                    due_at=st["due_at"],
                    stability=st["stability"],
                    difficulty=st["difficulty"],
                    step=st["step"],
                    state=st["state"],
                    reps=0,
                    lapses=0,
                )
                session.add(new_card)
                created_count += 1

        await session.commit()

    await callback.answer(f"✅ Добавлено ({created_count} карточек создано)")
    if callback.message:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n✅ <b>Слово добавлено в твою колоду!</b>",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("learn:skip:"))
async def cb_learn_skip(callback: CallbackQuery) -> None:
    await callback.answer("⏭ Пропущено")
    if callback.message:
        await callback.message.delete()


@router.message(Command("list"))
async def cmd_list(message: Message) -> None:
    if not message.from_user:
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=message.from_user.id
        )
        words, total = await get_user_words(session=session, user_id=user.id, page=1, page_size=10)
        await session.commit()

    if not words:
        await message.answer(
            "📚 В твоей колоде пока нет слов.\nДобавь слово через <code>/add &lt;слово&gt;</code> или пришли предложение!",
            parse_mode="HTML",
        )
        return

    lines = [f"📚 <b>Твоя колода слов (всего: {total}):</b>\n"]
    rows = []
    for idx, w in enumerate(words, start=1):
        st_icon = (
            "🟢" if w["status"] == "mastered" else ("🟡" if w["status"] == "learning" else "⚪")
        )
        lines.append(
            f"{idx}. {st_icon} <b>{escape(w['lemma'])}</b> — {escape(w['translation_ru'])} "
            f"[{escape(w.get('cefr_level') or 'B1')}]"
        )
        rows.append(
            [
                InlineKeyboardButton(text=f"ℹ️ {w['lemma']}", callback_data=f"wrd:info:{w['id']}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"wrd:del:{w['id']}"),
            ]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("wrd:info:"))
async def cb_word_info(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    word_id = int(callback.data.split(":", 2)[2])

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=callback.from_user.id
        )
        detail = await get_user_word_detail(session=session, user_id=user.id, word_id=word_id)
        await session.commit()

    if not detail:
        await callback.answer("Слово не найдено в колоде", show_alert=True)
        return

    info_lines = [
        f"<b>{escape(detail['lemma'])}</b> [{escape(detail.get('cefr_level') or 'B1')}]",
        f"Транскрипция: <code>{escape(detail.get('transcription') or '')}</code>",
        f"🇷🇺 Перевод: {escape(detail['translation_ru'])}",
        f"Статус: <b>{detail['status']}</b> · Карточек: {len(detail['cards'])}",
    ]
    if detail.get("collocations"):
        info_lines.append("🔗 <i>" + ", ".join(detail["collocations"][:3]) + "</i>")
    if detail.get("examples"):
        info_lines.append(f'\n💬 "{escape(detail["examples"][0]["sentence_en"])}"')

    await callback.answer()
    if callback.message:
        await callback.message.answer("\n".join(info_lines), parse_mode="HTML")


@router.callback_query(F.data.startswith("wrd:del:"))
async def cb_word_del(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    word_id = int(callback.data.split(":", 2)[2])

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=callback.from_user.id
        )
        deleted = await delete_user_word(session=session, user_id=user.id, word_id=word_id)
        await session.commit()

    if deleted:
        await callback.answer("🗑 Слово удалено из твоей колоды")
        if callback.message:
            await callback.message.edit_text(
                f"{callback.message.text}\n\n<i>(Слово #{word_id} удалено)</i>",
                parse_mode="HTML",
            )
    else:
        await callback.answer("Слово не найдено в колоде", show_alert=True)


@router.message(Command("mywords_export"))
async def cmd_mywords_export(message: Message) -> None:
    if not message.from_user:
        return
    wait_msg = await message.answer("⏳ Формирую CSV-файл со словами колоды...")

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=message.from_user.id
        )
        words, _total = await get_user_words(
            session=session, user_id=user.id, page=1, page_size=10000
        )
        await session.commit()

    if not words:
        await wait_msg.edit_text("Твоя колода пуста — экспортировать нечего.")
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["word", "translation", "cefr_level", "status", "source", "reps", "lapses"])

    for w in words:
        writer.writerow(
            [
                w["lemma"],
                w["translation_ru"],
                w.get("cefr_level") or "B1",
                w["status"],
                w["source"],
                w["total_reps"],
                w["total_lapses"],
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8")
    doc = BufferedInputFile(csv_bytes, filename="my_deck_words.csv")
    await wait_msg.delete()
    await message.answer_document(
        document=doc,
        caption=f"📥 <b>Экспорт завершён:</b> {len(words)} слов из твоей колоды.",
        parse_mode="HTML",
    )
