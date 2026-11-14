from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import quiz_mc_kb, quiz_menu_kb, quiz_next_kb
from app.db.session import AsyncSessionLocal
from app.services.llm import LLMService
from app.services.quiz_service import (
    create_matching_quiz,
    create_multiple_choice_quiz,
    create_sentence_scramble_quiz,
    verify_multiple_choice_answer,
)
from app.services.vocabulary import get_or_create_user_by_telegram

router = Router(name="quiz")
_llm_service = LLMService()


@router.message(Command("quiz"))
async def cmd_quiz(message: Message) -> None:
    await message.answer(
        "🧠 <b>Выбери режим тренировки:</b>\n\n"
        "1. <b>Множественный выбор</b> — выбери правильный перевод из 4 вариантов\n"
        "2. <b>Собери предложение</b> — расставь перемешанные слова в верном порядке\n"
        "3. <b>Подбор пар</b> — найди соответствия между английскими и русскими словами",
        parse_mode="HTML",
        reply_markup=quiz_menu_kb(),
    )


@router.callback_query(F.data == "qz:type:mc")
async def cb_start_mc_quiz(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=callback.from_user.id
        )
        q = await create_multiple_choice_quiz(session, user.id, _llm_service)
        await session.commit()

    if q is None:
        await callback.message.answer(
            "В твоей колоде пока нет слов для теста. Сначала отправь пару слов или предложений!"
        )
        return

    lines = [
        "🎯 <b>Множественный выбор</b>\n",
        f"Слово: <b>{escape(q.lemma)}</b>",
    ]
    if q.context_sentence:
        lines.append(f"💬 Контекст: <i>\"{escape(q.context_sentence)}\"</i>")
    lines.append("\nВыбери правильный русский перевод:")

    await callback.message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=quiz_mc_kb(q.quiz_id, q.options),
    )


@router.callback_query(F.data.startswith("qz:mc:"))
async def cb_answer_mc_quiz(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        return

    parts = callback.data.split(":")
    quiz_id = parts[2]

    # Find the chosen option text from message keyboard
    chosen_text = ""
    if callback.message.reply_markup and callback.message.reply_markup.inline_keyboard:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data == callback.data:
                    chosen_text = btn.text
                    break

    res = verify_multiple_choice_answer(quiz_id, chosen_text)
    if not res.get("valid"):
        await callback.answer("Тест устарел, начни новый через /quiz.", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)

    if res["is_correct"]:
        await callback.answer("Верно! 🎉")
        await callback.message.answer(
            f"✅ <b>Правильно!</b>\n<b>{escape(res['lemma'])}</b> = <b>{escape(res['correct_answer'])}</b>",
            parse_mode="HTML",
            reply_markup=quiz_next_kb(),
        )
    else:
        await callback.answer("Неверно ❌")
        await callback.message.answer(
            f"❌ <b>Неверно.</b>\nТвой ответ: {escape(chosen_text)}\n"
            f"Правильный перевод для <b>{escape(res['lemma'])}</b>: <b>{escape(res['correct_answer'])}</b>",
            parse_mode="HTML",
            reply_markup=quiz_next_kb(),
        )


@router.callback_query(F.data == "qz:type:scramble")
async def cb_start_scramble_quiz(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=callback.from_user.id
        )
        q = await create_sentence_scramble_quiz(session, user.id)
        await session.commit()

    if q is None:
        await callback.message.answer(
            "Не найдено подходящих предложений в колоде. Отправь предложение из книги или статьи!"
        )
        return

    shuffled_str = "  /  ".join(f"<code>{escape(tok)}</code>" for tok in q.shuffled_tokens)
    lines = [
        "🧩 <b>Собери предложение</b>\n",
        f"Перемешанные слова:\n{shuffled_str}\n",
    ]
    if q.translation_ru:
        lines.append(f"🇷🇺 Перевод: <i>\"{escape(q.translation_ru)}\"</i>\n")
    lines.append(f"Правильный ответ: <b>{escape(q.original_sentence)}</b>")

    await callback.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=quiz_next_kb())


@router.callback_query(F.data == "qz:type:matching")
async def cb_start_matching_quiz(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session, telegram_id=callback.from_user.id
        )
        q = await create_matching_quiz(session, user.id, pair_count=4)
        await session.commit()

    if q is None:
        await callback.message.answer(
            "Для подбора пар нужно хотя бы 3-4 слова в колоде. Добавь ещё слов!"
        )
        return

    en_list = "\n".join(f"{i + 1}. <b>{escape(w)}</b>" for i, w in enumerate(q.shuffled_en))
    ru_letters = ["A", "B", "C", "D", "E"]
    ru_list = "\n".join(
        f"{ru_letters[i]}. {escape(t)}" for i, t in enumerate(q.shuffled_ru[: len(ru_letters)])
    )

    lines = [
        "🔗 <b>Подбор пар: найди соответствия</b>\n",
        "<b>Английские слова:</b>",
        en_list,
        "",
        "<b>Русские переводы:</b>",
        ru_list,
        "",
        "<i>Проверь себя:</i>",
    ]
    for en, ru in q.pairs:
        lines.append(f"• <b>{escape(en)}</b> ➔ {escape(ru)}")

    await callback.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=quiz_next_kb())


@router.callback_query(F.data == "qz:next")
async def cb_quiz_next(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()
    await cb_start_mc_quiz(callback)
