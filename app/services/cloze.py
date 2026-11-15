import re


def _generate_inflection_patterns(lemma: str) -> list[str]:
    """Generates regex patterns for English lemmas and their common inflections."""
    clean = lemma.strip().lower()
    escaped = re.escape(clean)
    patterns = [rf"\b{escaped}\b"]

    # Simple suffix rules
    if clean.endswith("y") and len(clean) > 2 and clean[-2] not in "aeiou":
        base = re.escape(clean[:-1])
        patterns.extend([rf"\b{base}ies\b", rf"\b{base}ied\b", rf"\b{base}ying\b"])
    elif clean.endswith("e"):
        base = re.escape(clean[:-1])
        patterns.extend([rf"\b{base}ed\b", rf"\b{base}ing\b", rf"\b{escaped}s\b", rf"\b{base}er\b"])
    else:
        patterns.extend(
            [
                rf"\b{escaped}s\b",
                rf"\b{escaped}es\b",
                rf"\b{escaped}ed\b",
                rf"\b{escaped}ing\b",
                rf"\b{escaped}{clean[-1]}ed\b" if len(clean) > 2 else "",
                rf"\b{escaped}{clean[-1]}ing\b" if len(clean) > 2 else "",
            ]
        )

    # If lemma is multi-word (e.g. phrasal verb "look up" or "carry out")
    parts = clean.split()
    if len(parts) > 1:
        patterns.insert(0, rf"\b{re.escape(clean)}\b")

    return [p for p in patterns if p]


def mask_target_word(
    sentence_en: str,
    lemma: str,
    mask: str = "[ ... ]",
) -> tuple[str, str]:
    """
    Finds lemma or its inflected form in sentence_en and replaces it with mask.
    Returns (masked_sentence, matched_word_form).
    """
    if not sentence_en:
        return sentence_en, lemma

    patterns = _generate_inflection_patterns(lemma)
    for pat in patterns:
        match = re.search(pat, sentence_en, flags=re.IGNORECASE)
        if match:
            matched_form = match.group(0)
            masked = sentence_en[: match.start()] + mask + sentence_en[match.end() :]
            return masked, matched_form

    # Substring / partial fallback: look for words sharing a long common prefix
    tokens = re.finditer(r"\b[A-Za-z'-]+\b", sentence_en)
    clean_lemma = lemma.strip().lower()
    best_match = None
    best_len = 0
    min_prefix = min(4, len(clean_lemma))

    for token in tokens:
        word = token.group(0).lower()
        if (
            len(clean_lemma) >= min_prefix
            and word.startswith(clean_lemma[:min_prefix])
            and len(word) > best_len
        ):
            best_len = len(word)
            best_match = token

    if best_match is not None:
        matched_form = best_match.group(0)
        masked = sentence_en[: best_match.start()] + mask + sentence_en[best_match.end() :]
        return masked, matched_form

    # Ultimate fallback if word is completely irregular or missing from sentence
    return f"{sentence_en} (Пропуск: {mask})", lemma


def format_cloze_prompt(
    sentence_en: str,
    lemma: str,
    translation_ru: str,
    part_of_speech: str | None = None,
) -> tuple[str, str]:
    """
    Formats the cloze sentence and hint string.
    Returns (masked_sentence, answer_form).
    """
    masked_sentence, answer_form = mask_target_word(sentence_en, lemma, mask="[ ... ]")
    return masked_sentence, answer_form
