import math

import pytest

from app.benchmarks.schemas import (
    validate_event_result_row,
    validate_event_results,
    validate_summary_payload,
)


def _valid_completed_row(*, condition: str = "B", telemetry_error: bool = False):
    return {
        "event_id": "E1",
        "condition": condition,
        "repeat": 1,
        "simulation_status": "completed",
        "probabilities": {"YES": 0.7, "NO": 0.3},
        "brier": 0.09,
        "round_jsd": None if telemetry_error else [0.2, 0.15, 0.1, 0.05, 0.01],
        "convergence_monotonic": None if telemetry_error else True,
        "baseline_scores": {"uniform_random": {"brier": 0.5}},
        "rps": 0.18,
        "calibration_bracket": "0.5-0.75",
        "delta_conformity": 0.2,
        "error": "Telemetry error: missing trace" if telemetry_error else None,
    }


def _valid_summary():
    return {
        "composite_score": {"composite_score": 0.41},
        "convergence": {"mean_round_jsd": 0.12, "monotonic_count": 3},
        "content_susceptibility": {"delta": {"B_minus_C": 0.1}},
        "signed_susceptibility": {"directional_accuracy": 0.66},
        "evaluator_reliability": {"evaluator_unstable": False},
        "power_analysis": {"actual_n": 4},
        "effect_size": {"cohens_d": 0.42},
        "rps": {"overall": {"mean": 0.2}},
        "calibration": {"overall": {"mean_observed": 0.4}},
    }


def test_validate_event_result_row_schema_accepts_completed_row():
    validate_event_result_row(_valid_completed_row())


def test_validate_event_result_row_schema_rejects_missing_required_key():
    row = _valid_completed_row()
    row.pop("rps")

    with pytest.raises(ValueError, match="missing required keys: rps"):
        validate_event_result_row(row)


def test_validate_event_result_row_schema_rejects_empty_probabilities_for_completed():
    row = _valid_completed_row()
    row["probabilities"] = {}

    with pytest.raises(ValueError, match="'probabilities' must be a non-empty mapping"):
        validate_event_result_row(row)


def test_validate_event_result_row_schema_rejects_non_finite_brier_for_completed():
    row = _valid_completed_row()
    row["brier"] = math.inf

    with pytest.raises(ValueError, match="'brier' must be finite"):
        validate_event_result_row(row)


def test_validate_event_result_row_schema_rejects_short_round_jsd_without_telemetry_error():
    row = _valid_completed_row(condition="C")
    row["round_jsd"] = [0.2, 0.1]

    with pytest.raises(ValueError, match="'round_jsd' must be a list of length 5 for completed condition C"):
        validate_event_result_row(row)


def test_validate_event_result_row_schema_allows_missing_round_jsd_with_explicit_telemetry_error():
    validate_event_result_row(_valid_completed_row(condition="C", telemetry_error=True))


def test_validate_event_results_schema_prefixes_row_index_in_error():
    rows = [_valid_completed_row(), {"event_id": "E2"}]

    with pytest.raises(ValueError, match=r"rows\[1\] missing required keys"):
        validate_event_results(rows)


def test_validate_summary_payload_schema_accepts_required_blocks():
    validate_summary_payload(_valid_summary())


def test_validate_summary_payload_schema_rejects_missing_required_blocks():
    summary = _valid_summary()
    summary.pop("power_analysis")

    with pytest.raises(ValueError, match="missing required blocks: power_analysis"):
        validate_summary_payload(summary)
