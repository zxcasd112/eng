import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy import select

from app.bot.keyboards import rating_kb, show_answer_kb
from app.db.models import Word
from app.db.session import AsyncSessionLocal
from app.services.fsrs_service import RATING_LABELS_RU, format_interval_ru
from app.services.llm import LLMService
from app.services.review_engine import format_card_answer, format_card_question
from app.services.tts import TTSService
from app.services.vocabulary import (
    get_card_rating_previews,
    get_card_with_details,
    get_due_cards,
    get_or_create_user_by_telegram,
    get_word_explanation,
    submit_review,
)

logger = logging.getLogger(__name__)
router = Router(name="review")
_tts_service = TTSService()
_llm_service = LLMService()


async def send_next_due_card(target_message: Message, telegram_id: int) -> None:
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=telegram_id,
        )
        due = await get_due_cards(session, user.id, limit=20, interleave=True)
        await session.commit()

        if not due:
            await target_message.answer(
                "🎉 <b>На сегодня всё повторено!</b>\n"
                "Отправь новое слово или предложение, чтобы пополнить колоду, или запусти /quiz для тренировки.",
                parse_mode="HTML",
            )
            return

        card = due[0]
        prompt = format_card_question(card, len(due))

        # If audio card, send pronunciation first
        if prompt.audio_required:
            word = card.word
            if word.telegram_file_id:
                await target_message.answer_audio(word.telegram_file_id, title="Аудиозадание")
            else:
                audio_path = await _tts_service.get_or_create_audio(word.lemma)
                if audio_path is not None:
                    sent = await target_message.answer_audio(
                        FSInputFile(audio_path),
                        title="Аудиозадание",
                    )
                    if sent.audio:
                        word.telegram_file_id = sent.audio.file_id
                        word.audio_path = str(audio_path)
                        await session.commit()

    await target_message.answer(
        prompt.prompt_text,
        parse_mode="HTML",
        reply_markup=show_answer_kb(card.id),
    )


@router.message(Command("review"))
async def cmd_review(message: Message) -> None:
    if not message.from_user:
        return
    await send_next_due_card(message, message.from_user.id)


@router.callback_query(F.data == "rev:start")
async def cb_start_review(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    await callback.answer()
    await send_next_due_card(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("rev:show:"))
async def cb_show_answer(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        return
    card_id = int(callback.data.split(":")[2])

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=callback.from_user.id,
        )
        card = await get_card_with_details(session, user.id, card_id)
        if card is None:
            await callback.answer("Карточка не найдена", show_alert=True)
            return

        previews = get_card_rating_previews(card)
        answer_text = format_card_answer(card)

        await callback.message.edit_text(
            answer_text,
            parse_mode="HTML",
            reply_markup=rating_kb(card.id, card.word.id, previews),
        )
        await callback.answer()

        # Attach pronunciation audio on reveal if not an audio-only card
        if card.card_type != "audio":
            word = card.word
            if word.telegram_file_id:
                await callback.message.answer_audio(word.telegram_file_id, title=word.lemma)
            else:
                audio_path = await _tts_service.get_or_create_audio(word.lemma)
                if audio_path is not None:
                    sent = await callback.message.answer_audio(
                        FSInputFile(audio_path),
                        title=word.lemma,
                    )
                    if sent.audio:
                        word.telegram_file_id = sent.audio.file_id
                        word.audio_path = str(audio_path)
                        await session.commit()


@router.callback_query(F.data.startswith("rev:rate:"))
async def cb_rate_card(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    card_id = int(parts[2])
    rating = int(parts[3])

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=callback.from_user.id,
        )
        try:
            card, _review = await submit_review(
                session=session,
                user_id=user.id,
                card_id=card_id,
                rating=rating,
            )
            await session.commit()
        except ValueError:
            await callback.answer("Карточка не найдена", show_alert=True)
            return

        label = RATING_LABELS_RU.get(rating, "OK")
        delta_sec = (
            max(60.0, (card.due_at - card.last_review_at).total_seconds())
            if card.last_review_at
            else 60.0
        )
        next_in = format_interval_ru(delta_sec)

    await callback.answer(f"{label} • следующее повторение через {next_in}")
    await callback.message.edit_reply_markup(reply_markup=None)
    await send_next_due_card(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("rev:exp:"))
async def cb_explain_card_word(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        return
    word_id = int(callback.data.split(":")[2])

    await callback.answer("Загружаю разбор слова...")
    wait_msg = await callback.message.answer("⏳ Анализирую грамматику и синонимы...")

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=callback.from_user.id,
        )
        word_res = await session.execute(select(Word).where(Word.id == word_id))
        word = word_res.scalar_one_or_none()
        if not word:
            await wait_msg.edit_text("Слово не найдено.")
            return

        try:
            exp = await get_word_explanation(session, user, word.lemma, _llm_service)
            await session.commit()
        except Exception:
            logger.exception("Failed to get word explanation for lemma=%s", word.lemma)
            await wait_msg.edit_text("Не удалось получить разбор от LLM. Попробуй позже.")
            return

    lines = [
        f"📖 <b>Разбор слова: {escape(exp.lemma)}</b> [{escape(exp.cefr_level)}]",
        f"🇷🇺 {escape(exp.translation_ru or word.translation_ru)}",
        "",
    ]
    if exp.grammar_rules:
        lines.append("⚡ <b>Грамматика и конструкции:</b>")
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
        lines.append("🔄 <b>Синонимы и нюансы:</b>")
        for s in exp.synonyms_with_nuances[:3]:
            lines.append(f"• {escape(s)}")
        lines.append("")

    if exp.common_mistakes:
        lines.append("⚠️ <b>Частые ошибки:</b>")
        for m in exp.common_mistakes[:2]:
            lines.append(f"• {escape(m)}")

    await wait_msg.edit_text("\n".join(lines), parse_mode="HTML")
