import re
import time
import uuid
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.bot.keyboards import sentence_words_kb
from app.db.session import AsyncSessionLocal
from app.services.llm import LLMNotConfiguredError, LLMService, WordEnrichment
from app.services.tts import TTSService
from app.services.vocabulary import (
    add_word_from_enrichment,
    add_word_or_phrase,
    extract_new_words_from_sentence,
    get_or_create_user_by_telegram,
)

router = Router(name="words")

_llm_service = LLMService()
_tts_service = TTSService()

# Short-lived store for extracted words from sentences awaiting user tap
_PENDING_EXTRACTIONS: dict[str, tuple[float, list[WordEnrichment]]] = {}
_EXTRACTION_TTL_SECONDS = 3600


def _cleanup_pending() -> None:
    now = time.time()
    expired = [k for k, (ts, _) in _PENDING_EXTRACTIONS.items() if now - ts > _EXTRACTION_TTL_SECONDS]
    for k in expired:
        _PENDING_EXTRACTIONS.pop(k, None)


def is_sentence_input(text: str) -> bool:
    cleaned = text.strip()
    words = re.findall(r"[A-Za-z0-9'-]+", cleaned)
    if len(words) >= 5:
        return True
    return len(words) >= 4 and any(p in cleaned for p in (".", "!", "?", ";", ","))


def _format_added_card(
    lemma: str,
    transcription: str | None,
    cefr: str | None,
    translation_ru: str,
    example_en: str | None,
    example_ru: str | None,
    created_new: bool,
) -> str:
    header = "✅ <b>Добавлено в колоду</b>" if created_new else "ℹ️ <b>Уже есть в колоде</b>"
    ipa = f" <code>{escape(transcription)}</code>" if transcription else ""
    lvl = f" [{escape(cefr)}]" if cefr else ""
    lines = [
        header,
        f"<b>{escape(lemma)}</b>{ipa}{lvl}",
        f"🇷🇺 {escape(translation_ru)}",
    ]
    if example_en:
        lines.append(f"\n💬 <i>{escape(example_en)}</i>")
        if example_ru:
            lines.append(f"↳ {escape(example_ru)}")
    return "\n".join(lines)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_input(message: Message) -> None:
    if not message.from_user or not message.text:
        return

    text = message.text.strip()
    if len(text) < 2:
        await message.answer("Отправь слово, фразу или предложение на английском.")
        return

    if is_sentence_input(text):
        await _handle_sentence(message, text)
    else:
        await _handle_word_or_phrase(message, text)


async def _handle_word_or_phrase(message: Message, text: str) -> None:
    assert message.from_user is not None
    wait_msg = await message.answer("⏳ Перевожу и собираю карточку...")

    try:
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user_by_telegram(
                session=session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
            result = await add_word_or_phrase(
                session=session,
                user=user,
                text=text,
                llm_service=_llm_service,
                source_type="bot",
            )
            await session.commit()

            word = result.word
            example = result.example
            reply_text = _format_added_card(
                lemma=word.lemma,
                transcription=word.transcription,
                cefr=word.cefr_level,
                translation_ru=word.translation_ru,
                example_en=example.sentence_en if example else None,
                example_ru=example.sentence_ru if example else None,
                created_new=result.created_new_card,
            )
            await wait_msg.edit_text(reply_text, parse_mode="HTML")

            # Send TTS pronunciation if available, caching telegram_file_id
            if word.telegram_file_id:
                await message.answer_audio(word.telegram_file_id, title=word.lemma)
            else:
                audio_path = await _tts_service.get_or_create_audio(word.lemma)
                if audio_path is not None:
                    sent = await message.answer_audio(
                        FSInputFile(audio_path),
                        title=word.lemma,
                    )
                    if sent.audio:
                        word.telegram_file_id = sent.audio.file_id
                        word.audio_path = str(audio_path)
                        await session.commit()
    except LLMNotConfiguredError as exc:
        await wait_msg.edit_text(f"⚠️ {escape(str(exc))}", parse_mode="HTML")
    except Exception:
        await wait_msg.edit_text(
            "❌ Не удалось обработать слово. Проверь настройки LLM или попробуй чуть позже."
        )
        raise


async def _handle_sentence(message: Message, sentence: str) -> None:
    assert message.from_user is not None
    wait_msg = await message.answer("🔎 Анализирую предложение и ищу новые для тебя слова...")

    try:
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user_by_telegram(
                session=session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
            candidates = await extract_new_words_from_sentence(
                session=session,
                user=user,
                sentence=sentence,
                llm_service=_llm_service,
            )
            await session.commit()
    except LLMNotConfiguredError as exc:
        await wait_msg.edit_text(f"⚠️ {escape(str(exc))}", parse_mode="HTML")
        return
    except Exception:
        await wait_msg.edit_text("❌ Ошибка при анализе предложения. Попробуй ещё раз.")
        raise

    if not candidates:
        await wait_msg.edit_text(
            "👍 Похоже, все ключевые слова из этого предложения уже есть в твоей колоде!"
        )
        return

    _cleanup_pending()
    token = uuid.uuid4().hex[:10]
    _PENDING_EXTRACTIONS[token] = (time.time(), candidates)

    lines = ["📖 <b>Новые слова из предложения:</b>\n"]
    button_items: list[tuple[int, str, str]] = []
    for idx, item in enumerate(candidates):
        ipa = f" <code>{escape(item.transcription)}</code>" if item.transcription else ""
        lines.append(
            f"{idx + 1}. <b>{escape(item.lemma)}</b>{ipa} [{escape(item.cefr_level)}] — {escape(item.translation_ru)}"
        )
        button_items.append((idx, item.lemma, item.translation_ru))

    lines.append("\nВыбери слова, которые хочешь добавить в колоду:")
    await wait_msg.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=sentence_words_kb(token, button_items),
    )


@router.callback_query(F.data.startswith("sent:"))
async def cb_sentence_add(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    parts = callback.data.split(":")
    action = parts[1]
    token = parts[2]

    entry = _PENDING_EXTRACTIONS.get(token)
    if entry is None:
        await callback.answer("Список устарел, отправь предложение заново.", show_alert=True)
        return

    _ts, items = entry
    if action == "add":
        idx = int(parts[3])
        if not 0 <= idx < len(items):
            await callback.answer("Слово не найдено", show_alert=True)
            return
        selected = [items[idx]]
    elif action == "all":
        selected = items
    else:
        return

    added_names: list[str] = []
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_telegram(
            session=session,
            telegram_id=callback.from_user.id,
        )
        for enrichment in selected:
            res = await add_word_from_enrichment(
                session=session,
                user=user,
                enrichment=enrichment,
                source_type="book",
            )
            if res.created_new_card:
                added_names.append(res.word.lemma)
        await session.commit()

    if added_names:
        await callback.answer(f"Добавлено: {', '.join(added_names)}")
    else:
        await callback.answer("Эти слова уже в колоде")

    if action == "all" and callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        if added_names:
            await callback.message.answer(
                f"✅ Добавлены в колоду: <b>{escape(', '.join(added_names))}</b>",
                parse_mode="HTML",
            )
