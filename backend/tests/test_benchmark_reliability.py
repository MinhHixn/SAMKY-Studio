import pytest

from app.benchmarks.reliability import cohens_kappa, dominant_bucket_label, kappa_by_dimension


def test_dominant_bucket_label_selects_highest_probability_bucket():
    assert (
        dominant_bucket_label({"very_low": 0.1, "low": 0.2, "high": 0.6, "very_high": 0.1})
        == "high"
    )


def test_cohens_kappa_returns_one_for_perfect_agreement():
    categories = ["very_low", "low", "high", "very_high"]
    assert cohens_kappa(["low", "high", "very_high"], ["low", "high", "very_high"], categories) == pytest.approx(
        1.0
    )


def test_cohens_kappa_returns_negative_for_systematic_disagreement():
    categories = ["very_low", "low", "high", "very_high"]
    assert cohens_kappa(["low", "high"], ["high", "low"], categories) == pytest.approx(-1.0)


def test_kappa_by_dimension_uses_completed_rows_only():
    rows = [
        {
            "simulation_status": "completed",
            "evaluator_dimension_labels": {
                "convergence": {"run1": "high", "run2": "high"},
                "herd_effect": {"run1": "low", "run2": "high"},
            },
        },
        {
            "simulation_status": "completed",
            "evaluator_dimension_labels": {
                "convergence": {"run1": "low", "run2": "low"},
                "herd_effect": {"run1": "high", "run2": "low"},
            },
        },
        {
            "simulation_status": "evaluation_failed",
            "evaluator_dimension_labels": {
                "convergence": {"run1": "very_low", "run2": "very_high"},
            },
        },
    ]

    kappas = kappa_by_dimension(rows)

    assert kappas["convergence"] == pytest.approx(1.0)
    assert kappas["herd_effect"] == pytest.approx(-1.0)
