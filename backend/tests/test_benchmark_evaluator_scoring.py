import pytest

from app.benchmarks.evaluator import ProbabilityEvaluator
from app.benchmarks.scoring import brier_score, summarize_condition_scores


def test_brier_score_is_zero_for_correct_certainty():
    assert brier_score({"A": 1.0, "B": 0.0, "C": 0.0}, "A") == 0.0


def test_brier_score_matches_multiclass_expected_value():
    score = brier_score({"A": 0.2, "B": 0.5, "C": 0.3}, "B")
    assert score == pytest.approx(0.38)


def test_summarize_condition_scores_computes_means_and_lift():
    summary = summarize_condition_scores(
        [
            {"condition": "A", "brier": 0.2},
            {"condition": "A", "brier": 0.4},
            {"condition": "B", "brier": 0.1},
            {"condition": "C", "brier": 0.25},
        ]
    )

    assert summary["condition_mean_brier"] == {"A": 0.3, "B": 0.1, "C": 0.25}
    assert summary["lift"] == {"A_to_B": 0.2, "A_to_C": 0.05, "B_to_C": -0.15}


def test_probability_evaluator_normalizes_probabilities_and_uses_evaluator_role():
    calls = []

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096):
            calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
            return {"probabilities": {"A": 2, "B": 3, "C": 5}, "rationale": "ok"}

    class FakeRouter:
        def client_for(self, role):
            assert role == "evaluator"
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())
    result = evaluator.evaluate("Will it rain?", "B", "evidence text")

    assert result["normalized_probabilities"] == {"A": 0.2, "B": 0.3, "C": 0.5}
    assert result["probabilities"] == {"A": 0.2, "B": 0.3, "C": 0.5}
    assert calls and calls[0]["messages"][0]["role"] == "system"


@pytest.mark.parametrize(
    "payload, match",
    [
        ({}, r"probabilities"),
        ({"probabilities": {"A": 0, "B": 0, "C": 0}}, r"mass"),
        ({"probabilities": {"A": 1, "B": "x", "C": 0}}, r"[Ii]nvalid"),
    ],
)
def test_probability_evaluator_rejects_missing_invalid_or_zero_mass_probabilities(payload, match):
    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096):
            return payload

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=match):
        evaluator.evaluate("Q", "A", "E")
