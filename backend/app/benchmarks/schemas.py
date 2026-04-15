from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

REQUIRED_EVENT_RESULT_KEYS: tuple[str, ...] = (
    "event_id",
    "condition",
    "repeat",
    "simulation_status",
    "probabilities",
    "brier",
    "round_jsd",
    "convergence_monotonic",
    "baseline_scores",
    "rps",
    "calibration_bracket",
    "delta_conformity",
)

REQUIRED_SUMMARY_BLOCKS: tuple[str, ...] = (
    "composite_score",
    "convergence",
    "content_susceptibility",
    "signed_susceptibility",
    "evaluator_reliability",
    "power_analysis",
    "effect_size",
    "rps",
    "calibration",
    "delta_conformity",
)

VALID_SIMULATION_STATUSES = frozenset({"completed", "simulation_failed", "evaluation_failed"})
ROUND_JSD_CONDITIONS = frozenset({"B", "C"})


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _validate_probabilities_mapping(probabilities: Any, *, require_non_empty: bool) -> None:
    if not isinstance(probabilities, Mapping):
        if require_non_empty:
            raise ValueError("'probabilities' must be a non-empty mapping for completed rows")
        raise ValueError("'probabilities' must be a mapping when present")
    if require_non_empty and not probabilities:
        raise ValueError("'probabilities' must be a non-empty mapping for completed rows")
    for key in sorted(probabilities.keys(), key=lambda item: str(item)):
        label = str(key)
        value = probabilities.get(key)
        if not _is_finite_number(value):
            raise ValueError(f"'probabilities.{label}' must be finite numeric")


def _validate_round_jsd_trace(round_jsd: Any) -> None:
    if not isinstance(round_jsd, list):
        raise ValueError("'round_jsd' must be a list of finite numeric values")
    for index, value in enumerate(round_jsd):
        if not _is_finite_number(value):
            raise ValueError(f"'round_jsd[{index}]' must be finite numeric")


def _has_explicit_telemetry_error(row: Mapping[str, Any]) -> bool:
    error = row.get("error")
    return isinstance(error, str) and "Telemetry error:" in error


def validate_event_result_row(row: Mapping[str, Any]) -> None:
    if not isinstance(row, Mapping):
        raise ValueError("event result row must be a mapping")

    missing_keys = [key for key in REQUIRED_EVENT_RESULT_KEYS if key not in row]
    if missing_keys:
        raise ValueError(f"missing required keys: {', '.join(missing_keys)}")

    event_id = row.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("'event_id' must be a non-empty string")

    condition = row.get("condition")
    if not isinstance(condition, str) or not condition.strip():
        raise ValueError("'condition' must be a non-empty string")

    repeat = row.get("repeat")
    if isinstance(repeat, bool) or not isinstance(repeat, int):
        raise ValueError("'repeat' must be an integer")

    simulation_status = row.get("simulation_status")
    if not isinstance(simulation_status, str) or simulation_status not in VALID_SIMULATION_STATUSES:
        allowed = ", ".join(sorted(VALID_SIMULATION_STATUSES))
        raise ValueError(f"'simulation_status' must be one of: {allowed}")

    probabilities = row.get("probabilities")
    if probabilities is not None:
        _validate_probabilities_mapping(probabilities, require_non_empty=False)

    brier = row.get("brier")
    if brier is not None and not _is_finite_number(brier):
        raise ValueError("'brier' must be finite")

    round_jsd = row.get("round_jsd")
    if round_jsd is not None:
        _validate_round_jsd_trace(round_jsd)

    convergence_monotonic = row.get("convergence_monotonic")
    if convergence_monotonic is not None and not isinstance(convergence_monotonic, bool):
        raise ValueError("'convergence_monotonic' must be a boolean when present")

    baseline_scores = row.get("baseline_scores")
    if baseline_scores is not None and not isinstance(baseline_scores, Mapping):
        raise ValueError("'baseline_scores' must be a mapping when present")

    rps = row.get("rps")
    if rps is not None and not _is_finite_number(rps):
        raise ValueError("'rps' must be finite when present")

    calibration_bracket = row.get("calibration_bracket")
    if calibration_bracket is not None and not isinstance(calibration_bracket, str):
        raise ValueError("'calibration_bracket' must be a string when present")

    delta_conformity = row.get("delta_conformity")
    if delta_conformity is not None and not _is_finite_number(delta_conformity):
        raise ValueError("'delta_conformity' must be finite when present")

    if simulation_status != "completed":
        return

    _validate_probabilities_mapping(probabilities, require_non_empty=True)
    if not _is_finite_number(brier):
        raise ValueError("'brier' must be finite for completed rows")
    if not isinstance(baseline_scores, Mapping) or not baseline_scores:
        raise ValueError("'baseline_scores' must be a non-empty mapping for completed rows")
    if not _is_finite_number(rps):
        raise ValueError("'rps' must be finite for completed rows")
    if not isinstance(calibration_bracket, str) or not calibration_bracket.strip():
        raise ValueError("'calibration_bracket' must be a non-empty string for completed rows")

    telemetry_error = _has_explicit_telemetry_error(row)
    if condition in ROUND_JSD_CONDITIONS and not telemetry_error:
        if not isinstance(round_jsd, list) or len(round_jsd) != 5:
            raise ValueError(f"'round_jsd' must be a list of length 5 for completed condition {condition}")
        if not isinstance(convergence_monotonic, bool):
            raise ValueError(f"'convergence_monotonic' must be a boolean for completed condition {condition}")


def validate_event_results(rows: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("event results payload must be a list")
    for index, row in enumerate(rows):
        try:
            validate_event_result_row(row)
        except ValueError as exc:
            raise ValueError(f"rows[{index}] {exc}") from exc


def validate_summary_payload(summary: Mapping[str, Any]) -> None:
    if not isinstance(summary, Mapping):
        raise ValueError("summary payload must be a mapping")

    missing_blocks = [key for key in REQUIRED_SUMMARY_BLOCKS if key not in summary]
    if missing_blocks:
        raise ValueError(f"missing required blocks: {', '.join(missing_blocks)}")

    for key in REQUIRED_SUMMARY_BLOCKS:
        if not isinstance(summary.get(key), Mapping):
            raise ValueError(f"summary block '{key}' must be a mapping")

    convergence = summary["convergence"]
    mean_round_jsd = convergence.get("mean_round_jsd")
    if mean_round_jsd is not None and not _is_finite_number(mean_round_jsd):
        raise ValueError("summary block 'convergence.mean_round_jsd' must be finite when present")

    monotonic_count = convergence.get("monotonic_count")
    if monotonic_count is not None and (isinstance(monotonic_count, bool) or not isinstance(monotonic_count, int)):
        raise ValueError("summary block 'convergence.monotonic_count' must be an integer when present")
