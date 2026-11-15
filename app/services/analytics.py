import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import Card, Example, Review, Source, User, Word
from app.services.cefr import get_cefr_distance, normalize_cefr
from app.services.review_engine import ALL_CARD_TYPES


async def get_user_analytics(session: AsyncSession, user_id: int) -> dict:
    """Compute comprehensive cognitive learning analytics for a user."""
    now_utc = datetime.now(UTC)
    thirty_days_ago = now_utc - timedelta(days=30)

    # 1. 30-day Retention and Daily Retention
    rev_stmt = (
        select(
            Review.reviewed_at,
            Review.rating,
        )
        .where(Review.user_id == user_id, Review.reviewed_at >= thirty_days_ago)
        .order_by(Review.reviewed_at.asc())
    )
    rev_rows = (await session.execute(rev_stmt)).all()

    total_30d = len(rev_rows)
    passed_30d = sum(1 for r in rev_rows if r.rating >= 3)
    retention_30d = round((passed_30d / total_30d) * 100, 1) if total_30d else 0.0

    daily_map = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in rev_rows:
        dt = (
            r.reviewed_at.astimezone(UTC)
            if r.reviewed_at.tzinfo
            else r.reviewed_at.replace(tzinfo=UTC)
        )
        d_str = dt.strftime("%Y-%m-%d")
        daily_map[d_str]["total"] += 1
        if r.rating >= 3:
            daily_map[d_str]["passed"] += 1

    retention_daily = []
    for day_offset in range(30, -1, -1):
        target_date = (now_utc - timedelta(days=day_offset)).strftime("%Y-%m-%d")
        stats = daily_map.get(target_date, {"total": 0, "passed": 0})
        pct = round((stats["passed"] / stats["total"]) * 100, 1) if stats["total"] else 0.0
        retention_daily.append(
            {
                "date": target_date,
                "reviews_count": stats["total"],
                "passed_count": stats["passed"],
                "retention_pct": pct,
            }
        )

    # 2. Card Types Breakdown
    card_types_breakdown = []
    for c_type in ALL_CARD_TYPES:
        c_count = (
            await session.scalar(
                select(func.count(Card.id)).where(Card.user_id == user_id, Card.card_type == c_type)
            )
            or 0
        )
        r_stats = (
            await session.execute(
                select(
                    func.count(Review.id).label("total"),
                    func.sum(case((Review.rating >= 3, 1), else_=0)).label("passed"),
                )
                .join(Card, Card.id == Review.card_id)
                .where(Review.user_id == user_id, Card.card_type == c_type)
            )
        ).one_or_none()

        r_total = (r_stats.total or 0) if r_stats else 0
        r_passed = (r_stats.passed or 0) if r_stats else 0
        acc = round((r_passed / r_total) * 100, 1) if r_total else 0.0

        card_types_breakdown.append(
            {
                "card_type": c_type,
                "cards_count": c_count,
                "reviews_count": r_total,
                "passed_count": r_passed,
                "accuracy_pct": acc,
            }
        )

    # 3. Problem Words (High lapses, low avg rating, frequent Again)
    problem_words_stmt = (
        select(
            Word.id,
            Word.lemma,
            Word.translation_ru,
            func.max(Card.lapses).label("total_lapses"),
            func.count(Review.id).label("total_reviews"),
            func.sum(case((Review.rating == 1, 1), else_=0)).label("again_count"),
            func.avg(Review.rating).label("avg_rating"),
        )
        .join(Card, Card.word_id == Word.id)
        .outerjoin(Review, Review.card_id == Card.id)
        .where(Card.user_id == user_id)
        .group_by(Word.id)
        .having(
            or_(func.max(Card.lapses) > 0, func.sum(case((Review.rating == 1, 1), else_=0)) > 0)
        )
        .order_by(func.max(Card.lapses).desc(), func.avg(Review.rating).asc())
        .limit(10)
    )
    problem_rows = (await session.execute(problem_words_stmt)).all()
    problem_words = [
        {
            "word_id": r.id,
            "lemma": r.lemma,
            "translation_ru": r.translation_ru,
            "lapses": int(r.total_lapses or 0),
            "again_count": int(r.again_count or 0),
            "avg_rating": round(float(r.avg_rating or 0), 2),
        }
        for r in problem_rows
    ]

    # 4. Workload Forecast (Next 7 Days)
    workload_forecast_7d = []
    start_today = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=UTC)
    for day_i in range(7):
        day_date = start_today + timedelta(days=day_i)
        next_date = day_date + timedelta(days=1)
        d_str = day_date.strftime("%Y-%m-%d")

        if day_i == 0:
            due_cnt = (
                await session.scalar(
                    select(func.count(Card.id)).where(
                        Card.user_id == user_id, Card.due_at < next_date
                    )
                )
                or 0
            )
        else:
            due_cnt = (
                await session.scalar(
                    select(func.count(Card.id)).where(
                        Card.user_id == user_id,
                        Card.due_at >= day_date,
                        Card.due_at < next_date,
                    )
                )
                or 0
            )

        workload_forecast_7d.append(
            {
                "date": d_str,
                "due_cards_count": due_cnt,
            }
        )

    # 5. Stability & Difficulty Distributions
    cards_stats_res = await session.execute(
        select(Card.stability, Card.difficulty).where(Card.user_id == user_id)
    )
    all_cards_stats = cards_stats_res.all()

    stabilities = [r.stability for r in all_cards_stats if r.stability is not None]
    difficulties = [r.difficulty for r in all_cards_stats if r.difficulty is not None]

    def _calc_dist(
        values: list[float], label_prefix: str, step_size: float, bucket_count: int = 5
    ) -> dict:
        if not values:
            return {"mean": 0.0, "min": 0.0, "max": 0.0, "median": 0.0, "distribution": []}
        mean_v = round(float(statistics.mean(values)), 2)
        min_v = round(float(min(values)), 2)
        max_v = round(float(max(values)), 2)
        med_v = round(float(statistics.median(values)), 2)

        buckets = []
        for i in range(bucket_count):
            low = i * step_size
            high = (i + 1) * step_size
            if i == bucket_count - 1:
                cnt = sum(1 for v in values if v >= low)
                lbl = f"{low:.1f}+"
            else:
                cnt = sum(1 for v in values if low <= v < high)
                lbl = f"{low:.1f}–{high:.1f}"
            buckets.append({"range_label": lbl, "count": cnt})

        return {
            "mean": mean_v,
            "min": min_v,
            "max": max_v,
            "median": med_v,
            "distribution": buckets,
        }

    stability_stats = _calc_dist(stabilities, "S", step_size=5.0, bucket_count=5)
    difficulty_stats = _calc_dist(difficulties, "D", step_size=2.0, bucket_count=5)

    return {
        "retention_30d": retention_30d,
        "retention_daily": retention_daily,
        "card_types_breakdown": card_types_breakdown,
        "problem_words": problem_words,
        "workload_forecast_7d": workload_forecast_7d,
        "stability_stats": stability_stats,
        "difficulty_stats": difficulty_stats,
    }


async def get_user_recommendations(
    session: AsyncSession, user: User, limit: int = 10
) -> list[dict]:
    """
    Recommend words to study next based on:
    - User sources words not yet added
    - CEFR distance to user level (Krashen i+1)
    - Word frequency in user sources and examples
    - Unreviewed cards in user's deck
    """
    settings = get_settings()
    user_cefr = normalize_cefr(user.cefr_level)

    # 1. Collect user's card word IDs
    user_word_ids_stmt = (
        select(Card.word_id, func.min(Card.reps).label("min_reps"))
        .where(Card.user_id == user.id)
        .group_by(Card.word_id)
    )
    user_cards_summary = {
        r.word_id: int(r.min_reps or 0) for r in (await session.execute(user_word_ids_stmt)).all()
    }

    # 2. Collect words that appeared in user's sources
    user_source_words_stmt = (
        select(Example.word_id, func.count(Example.id).label("freq"))
        .join(Source, Source.id == Example.source_id)
        .where(Source.user_id == user.id)
        .group_by(Example.word_id)
    )
    user_source_freq = {
        r.word_id: r.freq for r in (await session.execute(user_source_words_stmt)).all()
    }

    # 3. Candidate words pool (all words in DB)
    all_words_stmt = (
        select(Word).options(selectinload(Word.examples)).order_by(Word.id.desc()).limit(300)
    )
    candidates = (await session.execute(all_words_stmt)).scalars().all()

    scored_items = []
    for w in candidates:
        score = 0.0
        reasons: list[str] = []

        is_in_deck = w.id in user_cards_summary
        min_reps = user_cards_summary.get(w.id, 0)
        source_freq = user_source_freq.get(w.id, 0)

        # Factor A: Word from user source not yet in deck or encountered often
        if source_freq > 0:
            if not is_in_deck:
                score += settings.rec_weight_source
                reasons.append("Встретилось в твоих добавленных текстах (ещё не в колоде)")
            else:
                score += settings.rec_weight_frequency * min(source_freq, 3)
                reasons.append(f"Часто встречается в твоих материалах ({source_freq}x)")

        # Factor B: CEFR Krashen i+1 proximity
        w_cefr = normalize_cefr(w.cefr_level, default="B1")
        dist = get_cefr_distance(user_cefr, w_cefr)

        if dist == 1:
            score += settings.rec_weight_cefr * 1.0
            reasons.append(f"Зона ближайшего развития i+1 ({user_cefr} ➔ {w_cefr})")
        elif dist == 0:
            score += settings.rec_weight_cefr * 0.8
            reasons.append(f"Точное соответствие твоему уровню ({user_cefr})")
        elif dist == -1:
            score += settings.rec_weight_cefr * 0.4
            reasons.append(f"Базовый уровень {w_cefr} для беглости речи")
        elif dist > 1:
            score += settings.rec_weight_cefr * 0.3
            reasons.append(f"Продвинутая лексика уровня {w_cefr}")

        # Factor C: Words in deck that user added but hasn't practiced yet (reps == 0)
        if is_in_deck and min_reps == 0:
            score += settings.rec_weight_unreviewed
            reasons.append("Слово уже в колоде, но ещё ни разу не повторялось")
        elif not is_in_deck:
            score += 1.0
            reasons.append("Новое популярное выражение из курса")

        if score > 0:
            word_dict = {
                "id": w.id,
                "lemma": w.lemma,
                "transcription": w.transcription,
                "part_of_speech": w.part_of_speech,
                "cefr_level": w.cefr_level,
                "translation_ru": w.translation_ru,
                "definition_en": w.definition_en,
                "collocations": w.collocations,
                "synonyms": w.synonyms,
                "antonyms": w.antonyms,
                "grammar_note": w.grammar_note,
            }
            scored_items.append(
                {
                    "word": word_dict,
                    "score": round(score, 2),
                    "reasons": reasons,
                }
            )

    scored_items.sort(key=lambda x: x["score"], reverse=True)
    return scored_items[:limit]
