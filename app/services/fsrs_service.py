from datetime import UTC, datetime
from typing import Any

from fsrs import Card as FSRSCard
from fsrs import Rating, Scheduler, State

_scheduler = Scheduler()

RATING_LABELS_RU: dict[int, str] = {
    Rating.Again.value: "Не знаю",
    Rating.Hard.value: "Сложно",
    Rating.Good.value: "Знаю",
    Rating.Easy.value: "Легко",
}


def ensure_utc(dt: datetime | str | None) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def new_card_state(now: datetime | None = None) -> dict[str, Any]:
    now_utc = ensure_utc(now) or datetime.now(UTC)
    card = FSRSCard(due=now_utc)
    data = card.to_dict()
    return {
        "fsrs_state": data,
        "due_at": ensure_utc(data["due"]),
        "stability": data["stability"],
        "difficulty": data["difficulty"],
        "step": data["step"],
        "state": int(data["state"]),
        "last_review_at": ensure_utc(data["last_review"]),
    }


def _load_fsrs_card(fsrs_state: dict[str, Any]) -> FSRSCard:
    normalized = dict(fsrs_state)
    due = ensure_utc(normalized.get("due"))
    if due is not None:
        normalized["due"] = due.isoformat()
    last_review = ensure_utc(normalized.get("last_review"))
    if last_review is not None:
        normalized["last_review"] = last_review.isoformat()
    return FSRSCard.from_dict(normalized)


def format_interval_ru(delta_seconds: float) -> str:
    minutes = max(1, round(delta_seconds / 60))
    if minutes < 60:
        return f"{minutes} мин"
    hours = round(minutes / 60)
    if hours < 24:
        return f"{hours} ч"
    days = round(hours / 24)
    if days < 30:
        return f"{days} дн"
    months = round(days / 30)
    if months < 12:
        return f"{months} мес"
    years = round(days / 365)
    return f"{years} г"


def review_fsrs_card(
    fsrs_state: dict[str, Any],
    rating_value: int,
    review_time: datetime | None = None,
) -> dict[str, Any]:
    now_utc = ensure_utc(review_time) or datetime.now(UTC)
    card = _load_fsrs_card(fsrs_state)
    prev_review = ensure_utc(card.last_review)
    elapsed_days = max(0, (now_utc - prev_review).days) if prev_review else 0

    rating = Rating(rating_value)
    updated_card, _log = _scheduler.review_card(card, rating, review_datetime=now_utc)
    updated_dict = updated_card.to_dict()
    due_utc = ensure_utc(updated_dict["due"]) or now_utc
    scheduled_days = max(0, (due_utc - now_utc).days)

    return {
        "fsrs_state": updated_dict,
        "due_at": due_utc,
        "stability": updated_dict["stability"],
        "difficulty": updated_dict["difficulty"],
        "step": updated_dict["step"],
        "state": int(updated_dict["state"]),
        "last_review_at": ensure_utc(updated_dict["last_review"]),
        "elapsed_days": elapsed_days,
        "scheduled_days": scheduled_days,
        "is_lapse": rating == Rating.Again and card.state == State.Review,
    }


def preview_intervals(
    fsrs_state: dict[str, Any],
    review_time: datetime | None = None,
) -> dict[int, str]:
    now_utc = ensure_utc(review_time) or datetime.now(UTC)
    card = _load_fsrs_card(fsrs_state)
    previews: dict[int, str] = {}
    for rating in (Rating.Again, Rating.Hard, Rating.Good, Rating.Easy):
        updated, _ = _scheduler.review_card(card, rating, review_datetime=now_utc)
        due_utc = ensure_utc(updated.due) or now_utc
        previews[rating.value] = format_interval_ru((due_utc - now_utc).total_seconds())
    return previews
