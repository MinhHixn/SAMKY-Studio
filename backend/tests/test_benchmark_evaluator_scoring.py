import pytest

from app.benchmarks.evaluator import ProbabilityEvaluator, get_evaluator_system_prompt
from app.benchmarks.prompt_registry import build_evaluator_system_prompt, load_mcq_prompt_spec
from app.benchmarks.scoring import (
    brier_score,
    summarize_condition_scores,
    summarize_directional_accuracy,
    summarize_weighted_rubric_score,
    summarize_rubric_artifacts,
)
from pathlib import Path


REAL_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "ecnbench_mcq_v1.yaml"


def test_brier_score_is_zero_for_correct_certainty():
    assert brier_score({"A": 1.0, "B": 0.0, "C": 0.0}, "A") == 0.0


def test_brier_score_matches_multiclass_expected_value():
    score = brier_score({"A": 0.2, "B": 0.5, "C": 0.3}, "B")
    assert score == pytest.approx(0.38)


def test_brier_score_treats_missing_truth_label_as_zero_probability():
    score = brier_score({"A": 0.7, "B": 0.3}, "C")
    assert score == pytest.approx(1.58)


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


def test_summarize_rubric_artifacts_counts_presence_and_scale_keys():
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 2, "high": 3, "very_high": 4} for key in dimension_keys
    }
    rows = [
        {
            "full_simulation_completed": True,
            "mcq_dimensions": mcq_dimensions,
            "validated_scales": {
                "schema_version": "v1",
                "scores": {
                    "calibration_consistency": 0.7,
                    "evidence_alignment": 0.8,
                }
            },
        },
        {"full_simulation_completed": True},
    ]

    summary = summarize_rubric_artifacts(rows)

    assert summary["rubric_completed_count"] == 1
    assert summary["rubric_missing_count"] == 1
    assert summary["validated_scale_keys"] == ["calibration_consistency", "evidence_alignment"]


def test_summarize_rubric_artifacts_excludes_malformed_rubric_dicts():
    valid_dimensions = {
        key: {"very_low": 1, "low": 2, "high": 3, "very_high": 4}
        for key in [
            "prediction_accuracy",
            "polarization",
            "herd_effect",
            "deliberation_quality",
            "susceptibility",
            "convergence",
            "information_diversity",
        ]
    }
    rows = [
        {
            "full_simulation_completed": True,
            "mcq_dimensions": valid_dimensions,
            "validated_scales": {"schema_version": "v1", "scores": {"evidence_alignment": 0.8}},
        },
        {
            "full_simulation_completed": True,
            "mcq_dimensions": {"prediction_accuracy": {"very_low": 1, "low": 1, "high": 1, "very_high": 1}},
            "validated_scales": {"schema_version": "v1", "scores": {"evidence_alignment": 0.8}},
        },
        {
            "full_simulation_completed": True,
            "mcq_dimensions": valid_dimensions,
            "validated_scales": {"schema_version": "v2", "scores": {"evidence_alignment": 0.8}},
        },
    ]

    summary = summarize_rubric_artifacts(rows)

    assert summary["rubric_completed_count"] == 1
    assert summary["rubric_missing_count"] == 2
    assert summary["validated_scale_keys"] == ["evidence_alignment"]


def test_probability_evaluator_normalizes_probabilities_and_uses_evaluator_role():
    calls = []
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 2, "high": 3, "very_high": 4} for key in dimension_keys
    }

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
            return {
                "probabilities": {"A": 2, "B": 3, "C": 5},
                "mcq_dimensions": mcq_dimensions,
                "validated_scales": {
                    "schema_version": "v1",
                    "scores": {"evidence_alignment": 0.8, "reasoning_quality": 0.6},
                },
                "rationale": "ok",
            }

    class FakeRouter:
        def client_for(self, role):
            assert role == "evaluator"
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())
    result = evaluator.evaluate("Will it rain?", "B", "evidence text")

    assert result["normalized_probabilities"] == {"A": 0.2, "B": 0.3, "C": 0.5}
    assert result["probabilities"] == {"A": 0.2, "B": 0.3, "C": 0.5}
    assert calls and calls[0]["messages"][0]["role"] == "system"
    system_prompt = calls[0]["messages"][0]["content"]
    assert "probabilities" in system_prompt
    assert "mcq_dimensions" in system_prompt
    assert "validated_scales" in system_prompt
    assert "schema_version" in system_prompt
    assert "v1" in system_prompt
    assert "scores" in system_prompt
    assert "numeric" in system_prompt
    for key in dimension_keys:
        assert key in system_prompt
    for bucket_key in ("very_low", "low", "high", "very_high"):
        assert bucket_key in system_prompt


def test_evaluator_system_prompt_uses_shipped_prompt_contract():
    spec = load_mcq_prompt_spec(REAL_PROMPT_PATH)
    expected_prompt = build_evaluator_system_prompt(spec)
    actual_prompt = get_evaluator_system_prompt()

    assert actual_prompt == expected_prompt
    assert "probabilities" in actual_prompt
    assert "mcq_dimensions" in actual_prompt
    assert "validated_scales" in actual_prompt
    assert "schema_version" in actual_prompt
    assert "scores" in actual_prompt
    assert "prediction_accuracy" in actual_prompt
    assert "polarization" in actual_prompt
    assert "herd_effect" in actual_prompt
    assert "deliberation_quality" in actual_prompt
    assert "susceptibility" in actual_prompt
    assert "convergence" in actual_prompt
    assert "information_diversity" in actual_prompt


@pytest.mark.parametrize(
    "payload, match",
    [
        ({}, r"probabilities"),
        ({"probabilities": {"A": 0, "B": 0, "C": 0}}, r"mass"),
        ({"probabilities": {"A": 1, "B": "x", "C": 0}}, r"[Ii]nvalid"),
        ({"probabilities": {"A": -1, "B": 2, "C": 0}}, r"non-negative"),
    ],
)
def test_probability_evaluator_rejects_missing_invalid_or_zero_mass_probabilities(payload, match):
    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return payload

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=match):
        evaluator.evaluate("Q", "A", "E")


@pytest.mark.parametrize(
    "payload, match",
    [
        ({"probabilities": {"A": float("nan"), "B": 1, "C": 1}}, r"finite"),
        ({"probabilities": {"A": float("inf"), "B": 1, "C": 1}}, r"finite"),
        ({"probabilities": {"A": 1, "B": -float("inf"), "C": 1}}, r"finite"),
    ],
)
def test_probability_evaluator_rejects_non_finite_probabilities(payload, match):
    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return payload

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=match):
        evaluator.evaluate("Q", "A", "E")


def test_probability_evaluator_returns_normalized_rubric_and_validated_scales():
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    bucket_values = {"very_low": 1, "low": 2, "high": 3, "very_high": 4}
    mcq_dimensions = {key: dict(bucket_values) for key in dimension_keys}

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return {
                "probabilities": {"A": 2, "B": 3, "C": 5},
                "mcq_dimensions": mcq_dimensions,
                "validated_scales": {
                    "schema_version": "v1",
                    "scores": {"evidence_alignment": 0.8, "reasoning_quality": 0.6},
                },
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())
    result = evaluator.evaluate("Q", "A", "E")

    assert set(result["mcq_dimensions"].keys()) == set(dimension_keys)
    for buckets in result["mcq_dimensions"].values():
        assert set(buckets.keys()) == {"very_low", "low", "high", "very_high"}
        assert sum(buckets.values()) == pytest.approx(1.0)

    assert result["validated_scales"]["schema_version"] == "v1"
    expected_keys = {
        "prediction_accuracy_score",
        "polarization_score",
        "herd_effect_score",
        "deliberation_quality_score",
        "susceptibility_score",
        "convergence_score",
        "information_diversity_score",
        "weighted_rubric_score",
    }
    assert set(result["validated_scales"]["scores"].keys()) == expected_keys
    assert 0.0 <= result["validated_scales"]["scores"]["weighted_rubric_score"] <= 1.0


def test_probability_evaluator_rejects_missing_rubric_dimension():
    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return {
                "probabilities": {"A": 1, "B": 2, "C": 3},
                "mcq_dimensions": {
                    "prediction_accuracy": {
                        "very_low": 1,
                        "low": 1,
                        "high": 1,
                        "very_high": 1,
                    }
                },
                "validated_scales": {
                    "schema_version": "v1",
                    "scores": {"evidence_alignment": 0.8, "reasoning_quality": 0.6},
                },
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=r"mcq_dimensions"):
        evaluator.evaluate("Q", "A", "E")


def test_probability_evaluator_rejects_missing_validated_scales():
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 1, "high": 1, "very_high": 1} for key in dimension_keys
    }

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return {"probabilities": {"A": 1, "B": 2, "C": 3}, "mcq_dimensions": mcq_dimensions}

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=r"validated_scales"):
        evaluator.evaluate("Q", "A", "E")


def test_probability_evaluator_rejects_invalid_validated_scales_schema_version():
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 1, "high": 1, "very_high": 1} for key in dimension_keys
    }

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return {
                "probabilities": {"A": 1, "B": 2, "C": 3},
                "mcq_dimensions": mcq_dimensions,
                "validated_scales": {
                    "schema_version": "v0",
                    "scores": {"evidence_alignment": 0.8},
                },
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=r"schema_version"):
        evaluator.evaluate("Q", "A", "E")


def test_probability_evaluator_rejects_invalid_mcq_bucket_keys():
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 1, "high": 1, "very_high": 1} for key in dimension_keys
    }
    mcq_dimensions["prediction_accuracy"] = {"very_low": 1, "low": 1, "high": 1}

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return {
                "probabilities": {"A": 1, "B": 2, "C": 3},
                "mcq_dimensions": mcq_dimensions,
                "validated_scales": {
                    "schema_version": "v1",
                    "scores": {"evidence_alignment": 0.8},
                },
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=r"bucket keys"):
        evaluator.evaluate("Q", "A", "E")


@pytest.mark.parametrize(
    "scores",
    [
        {"evidence_alignment": float("nan")},
        {"evidence_alignment": float("inf")},
        {"evidence_alignment": "bad"},
    ],
)
def test_probability_evaluator_rejects_invalid_validated_scales_scores(scores):
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 1, "high": 1, "very_high": 1} for key in dimension_keys
    }

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return {
                "probabilities": {"A": 1, "B": 2, "C": 3},
                "mcq_dimensions": mcq_dimensions,
                "validated_scales": {"schema_version": "v1", "scores": scores},
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=r"validated_scales\.scores"):
        evaluator.evaluate("Q", "A", "E")


def test_probability_evaluator_retries_invalid_json_then_succeeds(monkeypatch):
    attempts = []
    sleep_calls = []
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 1, "high": 1, "very_high": 1} for key in dimension_keys
        for key in dimension_keys
    }

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            attempts.append(repair_truncated_json)
            if len(attempts) < 3:
                raise ValueError("Invalid JSON format from LLM: {")
            return {
                "probabilities": {"A": 1, "B": 2, "C": 3},
                "mcq_dimensions": mcq_dimensions,
                "validated_scales": {"schema_version": "v1", "scores": {"evidence_alignment": 0.8}},
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    monkeypatch.setattr("time.sleep", sleep_calls.append)

    evaluator = ProbabilityEvaluator(FakeRouter())
    result = evaluator.evaluate("Q", "A", "E")

    assert result["probabilities"] == pytest.approx({"A": 1 / 6, "B": 2 / 6, "C": 3 / 6})
    assert attempts == [True, True, True]
    assert sleep_calls == [0.1, 0.2]


def test_probability_evaluator_raises_after_two_invalid_json_retries(monkeypatch):
    attempts = 0
    sleep_calls = []

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            nonlocal attempts
            attempts += 1
            raise ValueError("Invalid JSON format from LLM: invalid")

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    monkeypatch.setattr("time.sleep", sleep_calls.append)

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=r"Invalid JSON format from LLM:"):
        evaluator.evaluate("Q", "A", "E")

    assert attempts == 3
    assert sleep_calls == [0.1, 0.2]


def test_probability_evaluator_does_not_retry_non_json_validation_errors():
    attempts = 0
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 1, "high": 1, "very_high": 1} for key in dimension_keys
    }

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            nonlocal attempts
            attempts += 1
            return {
                "probabilities": {"A": 0, "B": 0, "C": 0},
                "mcq_dimensions": mcq_dimensions,
                "validated_scales": {"schema_version": "v1", "scores": {"evidence_alignment": 0.8}},
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=r"mass"):
        evaluator.evaluate("Q", "A", "E")

    assert attempts == 1


def test_probability_evaluator_does_not_retry_non_json_valueerror_from_client():
    attempts = 0

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            nonlocal attempts
            attempts += 1
            raise ValueError("Some other value error")

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())

    with pytest.raises(ValueError, match=r"Some other value error"):
        evaluator.evaluate("Q", "A", "E")

    assert attempts == 1


def test_probability_evaluator_uses_deterministic_scales_not_free_form_scores():
    dimension_keys = [
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    ]
    mcq_dimensions = {
        key: {"very_low": 1, "low": 2, "high": 3, "very_high": 4}
        for key in dimension_keys
    }

    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, repair_truncated_json=False):
            return {
                "probabilities": {"A": 2, "B": 3, "C": 5},
                "mcq_dimensions": mcq_dimensions,
                "validated_scales": {
                    "schema_version": "v1",
                    "scores": {"free_form": 123.0},
                },
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    evaluator = ProbabilityEvaluator(FakeRouter())
    result = evaluator.evaluate("Q", "A", "E")

    assert "free_form" not in result["validated_scales"]["scores"]
    assert "weighted_rubric_score" in result["validated_scales"]["scores"]


def test_summarize_directional_accuracy_by_condition_and_delta():
    rows = [
        {"full_simulation_completed": True, "condition": "A", "directional_correct": 1},
        {"full_simulation_completed": True, "condition": "A", "directional_correct": 0},
        {"full_simulation_completed": True, "condition": "B", "directional_correct": 1},
        {"full_simulation_completed": True, "condition": "C", "directional_correct": 1},
    ]

    summary = summarize_directional_accuracy(rows)

    assert summary["overall"] == pytest.approx(0.75)
    assert summary["by_condition"]["A"] == pytest.approx(0.5)
    assert summary["by_condition"]["B"] == pytest.approx(1.0)
    assert summary["by_condition"]["C"] == pytest.approx(1.0)
    assert summary["delta"]["A_to_B"] == pytest.approx(0.5)
    assert summary["delta"]["A_to_C"] == pytest.approx(0.5)
    assert summary["delta"]["B_to_C"] == pytest.approx(0.0)


def test_summarize_weighted_rubric_score_by_condition_and_delta():
    rows = [
        {"full_simulation_completed": True, "condition": "A", "weighted_rubric_score": 0.25},
        {"full_simulation_completed": True, "condition": "A", "weighted_rubric_score": 0.5},
        {"full_simulation_completed": True, "condition": "B", "weighted_rubric_score": 0.75},
        {"full_simulation_completed": True, "condition": "C", "weighted_rubric_score": 0.5},
        {"full_simulation_completed": True, "condition": "C", "weighted_rubric_score": None},
    ]

    summary = summarize_weighted_rubric_score(rows)

    assert summary["overall"] == pytest.approx(0.5)
    assert summary["by_condition"]["A"] == pytest.approx(0.375)
    assert summary["by_condition"]["B"] == pytest.approx(0.75)
    assert summary["by_condition"]["C"] == pytest.approx(0.5)
    assert summary["delta"]["A_to_B"] == pytest.approx(0.375)
    assert summary["delta"]["A_to_C"] == pytest.approx(0.125)
    assert summary["delta"]["B_to_C"] == pytest.approx(-0.25)
