from app.services.cefr import (
    compare_cefr,
    get_cefr_distance,
    get_level_feedback,
    normalize_cefr,
)


def test_normalize_cefr():
    assert normalize_cefr("b1") == "B1"
    assert normalize_cefr("C2") == "C2"
    assert normalize_cefr("invalid", default="B1") == "B1"


def test_compare_cefr():
    assert compare_cefr("A1", "A2") == -1
    assert compare_cefr("B2", "B1") == 1
    assert compare_cefr("C1", "C1") == 0


def test_cefr_distance_and_pedagogy():
    dist = get_cefr_distance("B1", "B2")
    assert dist == 1
    fb = get_level_feedback("B1", "B2")
    assert "i+1" in fb["badge"]

    fb_exact = get_level_feedback("B1", "B1")
    assert "Твой уровень" in fb_exact["badge"]
