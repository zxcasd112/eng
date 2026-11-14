from app.services.cloze import format_cloze_prompt, mask_target_word


def test_mask_exact_word():
    sentence = "The scientist conducted an important research in biology."
    masked, form = mask_target_word(sentence, "research")
    assert "[ ... ]" in masked
    assert form.lower() == "research"
    assert "conducted an important [ ... ] in biology." in masked


def test_mask_inflected_verb():
    sentence = "She is discovering new methods every single day."
    masked, form = mask_target_word(sentence, "discover")
    assert "[ ... ]" in masked
    assert form.lower() == "discovering"
    assert "She is [ ... ] new methods" in masked


def test_mask_plural_noun():
    sentence = "We reviewed several breakthroughs in the field."
    masked, form = mask_target_word(sentence, "breakthrough")
    assert "[ ... ]" in masked
    assert form.lower() == "breakthroughs"


def test_format_cloze_prompt():
    sentence = "Regular practice is crucial for success."
    masked, form = format_cloze_prompt(sentence, "crucial", "решающий", "adjective")
    assert "[ ... ]" in masked
    assert form.lower() == "crucial"
