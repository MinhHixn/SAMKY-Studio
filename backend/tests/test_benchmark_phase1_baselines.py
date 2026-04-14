import pytest

from app.benchmarks.phase1_baselines import (
    build_baseline_scores,
    validate_polymarket_opening_prior,
)


def test_validate_polymarket_opening_prior_happy_path():
    event = {
        "event_id": "E1",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": 0.55, "NO": 0.45},
    }
    validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)


def test_validate_polymarket_opening_prior_rejects_missing_label():
    event = {
        "event_id": "E1",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": 1.0},
    }
    with pytest.raises(ValueError, match="missing required outcome labels"):
        validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)


def test_validate_polymarket_opening_prior_rejects_extra_label():
    event = {
        "event_id": "E1",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": 0.5, "NO": 0.4, "MAYBE": 0.1},
    }
    with pytest.raises(ValueError, match="unexpected outcome labels"):
        validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)


def test_build_baseline_scores_returns_uniform_and_market_prior():
    event = {
        "event_id": "E1",
        "outcome": "YES",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": 0.6, "NO": 0.4},
    }
    baseline_scores = build_baseline_scores(event)
    assert set(baseline_scores.keys()) == {"uniform_random", "market_prior"}
    assert "brier" in baseline_scores["uniform_random"]
    assert "brier" in baseline_scores["market_prior"]


def test_validate_polymarket_opening_prior_rejects_non_finite_values_nan():
    event = {
        "event_id": "E1",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": float("nan"), "NO": 1.0},
    }
    with pytest.raises(ValueError, match="must be finite"):
        validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)


def test_validate_polymarket_opening_prior_rejects_non_finite_values_inf():
    event = {
        "event_id": "E1",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": float("inf"), "NO": -float("inf")},
    }
    with pytest.raises(ValueError, match="must be finite"):
        validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)

