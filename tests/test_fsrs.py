from datetime import UTC, datetime, timedelta

from app.services.fsrs_service import (
    ensure_utc,
    new_card_state,
    preview_intervals,
    review_fsrs_card,
)


def test_new_card_and_review_good_progression():
    t0 = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    initial = new_card_state(now=t0)
    assert initial["state"] == 1
    assert initial["due_at"] == t0

    # First review: Good -> advances step in Learning
    res1 = review_fsrs_card(initial["fsrs_state"], rating_value=3, review_time=t0)
    assert res1["due_at"] > t0
    assert res1["stability"] is not None
    assert res1["difficulty"] is not None

    # Second review: Good -> graduates to Review state (>= 1 day later)
    t1 = res1["due_at"]
    res2 = review_fsrs_card(res1["fsrs_state"], rating_value=3, review_time=t1)
    assert res2["state"] == 2  # Review
    assert res2["due_at"] >= t1 + timedelta(days=1)


def test_preview_intervals_returns_all_four_ratings():
    t0 = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    initial = new_card_state(now=t0)
    previews = preview_intervals(initial["fsrs_state"], review_time=t0)
    assert set(previews.keys()) == {1, 2, 3, 4}
    assert all(isinstance(v, str) and len(v) > 0 for v in previews.values())


def test_ensure_utc_handles_naive_datetime():
    naive = datetime(2026, 11, 14, 12, 0)
    aware = ensure_utc(naive)
    assert aware is not None
    assert aware.tzinfo == UTC
