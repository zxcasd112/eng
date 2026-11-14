from dataclasses import dataclass
from html import escape

from app.db.models import Card
from app.services.cloze import mask_target_word

CARD_TYPE_EN_RU = "en_ru"
CARD_TYPE_RU_EN = "ru_en"
CARD_TYPE_CLOZE = "cloze"
CARD_TYPE_AUDIO = "audio"

ALL_CARD_TYPES = [
    CARD_TYPE_EN_RU,
    CARD_TYPE_RU_EN,
    CARD_TYPE_CLOZE,
    CARD_TYPE_AUDIO,
]

CARD_TYPE_LABELS_RU = {
    CARD_TYPE_EN_RU: "EN ➔ RU (контекст)",
    CARD_TYPE_RU_EN: "RU ➔ EN (активное воспоминание)",
    CARD_TYPE_CLOZE: "Пропуск в предложении (cloze)",
    CARD_TYPE_AUDIO: "Аудиокарточка (на слух)",
}


@dataclass
class CardPrompt:
    card_id: int
    card_type: str
    type_label: str
    prompt_text: str
    audio_required: bool
    target_lemma: str


def interleave_cards(cards: list[Card]) -> list[Card]:
    """
    Interleaving algorithm:
    Distributes cards so that adjacent items in the study queue alternate both
    card_type and word_id as much as possible, avoiding homogeneous streaks.
    """
    if len(cards) <= 1:
        return list(cards)

    # Separate into queues by card_type
    by_type: dict[str, list[Card]] = {ct: [] for ct in ALL_CARD_TYPES}
    other_type: list[Card] = []
    for c in cards:
        if c.card_type in by_type:
            by_type[c.card_type].append(c)
        else:
            other_type.append(c)

    # Sort each sub-bucket by due_at
    for cards_list in by_type.values():
        cards_list.sort(key=lambda x: x.due_at)

    result: list[Card] = []
    total = len(cards)
    types_cycle = [ct for ct in ALL_CARD_TYPES if by_type[ct]]
    if not types_cycle and other_type:
        return sorted(cards, key=lambda x: x.due_at)

    type_idx = 0
    last_word_id: int | None = None

    while len(result) < total:
        placed = False
        attempts = 0
        while attempts < len(types_cycle):
            ct = types_cycle[type_idx % len(types_cycle)]
            queue = by_type[ct]
            type_idx += 1
            attempts += 1

            if not queue:
                continue

            # Prefer card with different word_id from the immediate predecessor
            candidate_idx = 0
            if last_word_id is not None and len(queue) > 1:
                for idx, c in enumerate(queue):
                    if c.word_id != last_word_id:
                        candidate_idx = idx
                        break

            chosen = queue.pop(candidate_idx)
            result.append(chosen)
            last_word_id = chosen.word_id
            placed = True
            break

        if not placed:
            # Drain remaining from other_type or any leftover
            if other_type:
                result.append(other_type.pop(0))
            else:
                for queue in by_type.values():
                    if queue:
                        result.append(queue.pop(0))
                        break

    return result


def format_card_question(card: Card, remaining_count: int) -> CardPrompt:
    word = card.word
    ex = card.example
    c_type = card.card_type or CARD_TYPE_EN_RU
    type_label = CARD_TYPE_LABELS_RU.get(c_type, "Повторение")

    lines: list[str] = [
        f"🧠 <b>Повторение: {escape(type_label)}</b> (осталось: {remaining_count})",
        "",
    ]

    audio_required = False

    if c_type == CARD_TYPE_CLOZE:
        if ex and ex.sentence_en:
            masked, _ = mask_target_word(ex.sentence_en, word.lemma)
            lines.append(f'💬 <i>"{escape(masked)}"</i>')
        else:
            lines.append(f'💬 [ ... ] — <i>"{escape(word.translation_ru)}"</i>')
        lines.append(f"\n🇷🇺 Значение: <b>{escape(word.translation_ru)}</b>")
        if word.part_of_speech:
            lines.append(f"Часть речи: <i>{escape(word.part_of_speech)}</i>")
        lines.append("\nВспомни пропущенное слово и нажми «Показать ответ».")

    elif c_type == CARD_TYPE_RU_EN:
        lines.append(f"🇷🇺 <b>{escape(word.translation_ru)}</b>")
        if word.part_of_speech:
            lines.append(f"Часть речи: <i>{escape(word.part_of_speech)}</i>")
        if ex and ex.sentence_ru:
            lines.append(f'\n💬 Контекст: <i>"{escape(ex.sentence_ru)}"</i>')
        lines.append("\nВспомни, как это будет по-английски, и нажми «Показать ответ».")

    elif c_type == CARD_TYPE_AUDIO:
        audio_required = True
        lines.append("🎧 <b>Послушай аудиозапись ⬆️</b>")
        lines.append("\nЗапиши или вспомни слово, его значение и правописание.")
        lines.append("Затем нажми «Показать ответ».")

    else:
        # Default: EN_RU
        lines.append(f"<b>{escape(word.lemma)}</b>")
        if word.part_of_speech:
            lines.append(f"<i>{escape(word.part_of_speech)}</i>")
        if ex and ex.sentence_en:
            lines.append(f'\n💬 <i>"{escape(ex.sentence_en)}"</i>')
        lines.append("\nВспомни перевод и нажми «Показать ответ».")

    return CardPrompt(
        card_id=card.id,
        card_type=c_type,
        type_label=type_label,
        prompt_text="\n".join(lines),
        audio_required=audio_required,
        target_lemma=word.lemma,
    )


def format_card_answer(card: Card) -> str:
    word = card.word
    ex = card.example
    ipa = f" <code>{escape(word.transcription)}</code>" if word.transcription else ""
    lvl = f" [{escape(word.cefr_level)}]" if word.cefr_level else ""

    lines = [
        f"<b>{escape(word.lemma)}</b>{ipa}{lvl}",
        f"🇷🇺 <b>{escape(word.translation_ru)}</b>",
    ]

    if word.definition_en:
        lines.append(f"📖 {escape(word.definition_en)}")

    if ex and ex.sentence_en:
        lines.append(f'\n💬 <i>"{escape(ex.sentence_en)}"</i>')
        if ex.sentence_ru:
            lines.append(f'↳ <i>"{escape(ex.sentence_ru)}"</i>')

    if word.collocations:
        colls = ", ".join(escape(c) for c in word.collocations[:3])
        lines.append(f"\n🔗 <b>Коллокации:</b> {colls}")

    if word.grammar_note:
        lines.append(f"💡 <b>Грамматика:</b> {escape(word.grammar_note)}")

    lines.append("\nКак хорошо ты вспомнил(а) слово?")
    return "\n".join(lines)
