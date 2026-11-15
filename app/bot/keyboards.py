from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.review_engine import ALL_CARD_TYPES, CARD_TYPE_LABELS_RU


def show_answer_kb(card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👁 Показать ответ",
                    callback_data=f"rev:show:{card_id}",
                )
            ]
        ]
    )


def rating_kb(card_id: int, word_id: int, previews: dict[int, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"❌ Не знаю ({previews.get(1, '1 мин')})",
                    callback_data=f"rev:rate:{card_id}:1",
                ),
                InlineKeyboardButton(
                    text=f"😓 Сложно ({previews.get(2, '5 мин')})",
                    callback_data=f"rev:rate:{card_id}:2",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"✅ Знаю ({previews.get(3, '10 мин')})",
                    callback_data=f"rev:rate:{card_id}:3",
                ),
                InlineKeyboardButton(
                    text=f"⚡ Легко ({previews.get(4, '4 дн')})",
                    callback_data=f"rev:rate:{card_id}:4",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💡 Разбор слова (грамматика и синонимы)",
                    callback_data=f"rev:exp:{word_id}",
                )
            ],
        ]
    )


def card_types_kb(active_types: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for ct in ALL_CARD_TYPES:
        is_on = ct in active_types
        icon = "✅" if is_on else "⬜"
        label = CARD_TYPE_LABELS_RU.get(ct, ct)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {label}",
                    callback_data=f"ct:toggle:{ct}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cefr_level_kb() -> InlineKeyboardMarkup:
    levels = ["A1", "A2", "B1", "B2", "C1", "C2"]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=lvl, callback_data=f"lvl:{lvl}") for lvl in levels[:3]],
            [InlineKeyboardButton(text=lvl, callback_data=f"lvl:{lvl}") for lvl in levels[3:]],
        ]
    )


def sentence_words_kb(token: str, words: list[tuple[int, str, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, lemma, translation in words:
        short_tr = translation if len(translation) <= 24 else translation[:21] + "..."
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ {lemma} — {short_tr}",
                    callback_data=f"sent:add:{token}:{idx}",
                )
            ]
        )
    if len(words) > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Добавить все слова",
                    callback_data=f"sent:all:{token}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reminder_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Начать повторение",
                    callback_data="rev:start",
                )
            ]
        ]
    )


def quiz_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎯 Множественный выбор",
                    callback_data="qz:type:mc",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧩 Собери предложение (Scramble)",
                    callback_data="qz:type:scramble",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Подбор пар (Matching)",
                    callback_data="qz:type:matching",
                )
            ],
        ]
    )


def quiz_mc_kb(quiz_id: str, options: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for idx, opt in enumerate(options):
        rows.append(
            [
                InlineKeyboardButton(
                    text=opt,
                    callback_data=f"qz:mc:{quiz_id}:{idx}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quiz_next_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➡️ Следующий вопрос",
                    callback_data="qz:next",
                )
            ]
        ]
    )
