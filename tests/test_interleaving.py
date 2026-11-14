from datetime import UTC, datetime, timedelta

from app.db.models import Card, Word
from app.services.review_engine import (
    CARD_TYPE_AUDIO,
    CARD_TYPE_CLOZE,
    CARD_TYPE_EN_RU,
    CARD_TYPE_RU_EN,
    interleave_cards,
)


def _make_dummy_card(card_id: int, word_id: int, card_type: str, offset_mins: int = 0) -> Card:
    c = Card()
    c.id = card_id
    c.user_id = 1
    c.word_id = word_id
    c.card_type = card_type
    c.due_at = datetime.now(UTC) + timedelta(minutes=offset_mins)
    c.fsrs_state = {}
    c.word = Word(id=word_id, lemma=f"word_{word_id}", translation_ru=f"перевод_{word_id}")
    return c


def test_interleave_cards_alternates_types_and_words():
    # 4 cards of different types and words
    c1 = _make_dummy_card(1, 10, CARD_TYPE_EN_RU, 1)
    c2 = _make_dummy_card(2, 10, CARD_TYPE_CLOZE, 2)
    c3 = _make_dummy_card(3, 20, CARD_TYPE_RU_EN, 3)
    c4 = _make_dummy_card(4, 30, CARD_TYPE_AUDIO, 4)

    input_cards = [c1, c2, c3, c4]
    interleaved = interleave_cards(input_cards)

    assert len(interleaved) == 4
    # Ensure types alternate
    types_seq = [c.card_type for c in interleaved]
    for i in range(len(types_seq) - 1):
        assert types_seq[i] != types_seq[i + 1]


def test_interleave_single_or_empty():
    assert interleave_cards([]) == []
    c1 = _make_dummy_card(1, 10, CARD_TYPE_EN_RU)
    assert len(interleave_cards([c1])) == 1
