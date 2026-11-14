CEFR_LEVELS: list[str] = ["A1", "A2", "B1", "B2", "C1", "C2"]

CEFR_DESCRIPTIONS: dict[str, str] = {
    "A1": "Beginner (Начальный)",
    "A2": "Elementary (Базовый)",
    "B1": "Intermediate (Средний)",
    "B2": "Upper-Intermediate (Выше среднего)",
    "C1": "Advanced (Продвинутый)",
    "C2": "Proficiency (В совершенстве)",
}


def normalize_cefr(level: str | None, default: str = "B1") -> str:
    if not level:
        return default
    cleaned = level.strip().upper()
    return cleaned if cleaned in CEFR_LEVELS else default


def cefr_index(level: str | None) -> int:
    norm = normalize_cefr(level)
    return CEFR_LEVELS.index(norm)


def compare_cefr(level_a: str | None, level_b: str | None) -> int:
    idx_a = cefr_index(level_a)
    idx_b = cefr_index(level_b)
    if idx_a < idx_b:
        return -1
    if idx_a > idx_b:
        return 1
    return 0


def get_cefr_distance(user_level: str | None, word_level: str | None) -> int:
    """Returns (word_level_index - user_level_index)."""
    return cefr_index(word_level) - cefr_index(user_level)


def get_level_feedback(user_level: str | None, word_level: str | None) -> dict[str, str]:
    """
    Krashen's Comprehensible Input (i+1) pedagogical recommendation.
    """
    u_norm = normalize_cefr(user_level)
    w_norm = normalize_cefr(word_level)
    dist = get_cefr_distance(u_norm, w_norm)

    if dist == 1:
        badge = "🚀 i+1 (Идеально)"
        message = f"Оптимально для роста: чуть выше твоего уровня ({u_norm} ➔ {w_norm})."
    elif dist == 0:
        badge = "🎯 Твой уровень"
        message = f"Слово точно соответствует твоему уровню {u_norm}."
    elif dist > 1:
        badge = "🔥 Продвинутый уровень"
        message = f"Слово уровня {w_norm} — отличный вызов для расширения лексикона!"
    else:
        badge = "🟢 Фундамент"
        message = f"Слово уровня {w_norm} для быстрого распознавания и закрепления автоматизма."

    return {
        "user_level": u_norm,
        "word_level": w_norm,
        "distance": str(dist),
        "badge": badge,
        "message": message,
    }
