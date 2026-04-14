"""Telemetry extraction helpers for Phase 1 convergence signals."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

_PROBABILITY_KEYS = (
    "probability",
    "prob",
    "p_yes",
    "yes_probability",
    "forecast",
    "prediction",
    "belief",
)


def is_monotonic_nonincreasing_with_epsilon(values: Iterable[float], epsilon: float) -> bool:
    previous: float | None = None
    for value in values:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(numeric):
            return False
        if previous is not None and numeric > previous + float(epsilon):
            return False
        previous = numeric
    return True


def compute_round_jsd_trace(
    unit_dir: Path | str,
    *,
    checkpoints: Iterable[int],
    min_parsed_probability_ratio: float,
) -> list[float]:
    unit_path = Path(unit_dir)
    checkpoint_list = [int(checkpoint) for checkpoint in checkpoints]
    checkpoint_set = set(checkpoint_list)
    totals = {checkpoint: 0 for checkpoint in checkpoint_list}
    probabilities: dict[int, list[float]] = {checkpoint: [] for checkpoint in checkpoint_list}

    for log_path in (
        unit_path / "twitter" / "actions.jsonl",
        unit_path / "reddit" / "actions.jsonl",
    ):
        if not log_path.exists():
            continue
        for entry in _read_actions(log_path):
            round_num = _extract_round(entry)
            if round_num is None or round_num not in checkpoint_set:
                continue
            if _is_round_marker(entry):
                continue
            totals[round_num] += 1
            probability = _extract_probability(entry)
            if probability is not None:
                probabilities[round_num].append(probability)

    trace: list[float] = []
    min_ratio = float(min_parsed_probability_ratio)
    for checkpoint in checkpoint_list:
        total = totals[checkpoint]
        parsed = len(probabilities[checkpoint])
        ratio = parsed / total if total else 0.0
        if ratio < min_ratio:
            raise ValueError(
                f"Telemetry probability coverage below minimum at round {checkpoint}: "
                f"{parsed}/{total} ({ratio:.3f})"
            )
        trace.append(_jsd_against_uniform(probabilities[checkpoint]))
    return trace


def _read_actions(path: Path) -> Iterable[Mapping[str, Any]]:
    for line_num, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path} at line {line_num}") from exc
        if isinstance(entry, Mapping):
            yield entry


def _extract_round(entry: Mapping[str, Any]) -> int | None:
    value = entry.get("round")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_round_marker(entry: Mapping[str, Any]) -> bool:
    return "event_type" in entry


def _extract_probability(entry: Mapping[str, Any]) -> float | None:
    for payload in (
        entry.get("action_args"),
        entry.get("result"),
        entry.get("response"),
        entry,
    ):
        probability = _extract_probability_from_payload(payload)
        if probability is not None:
            return probability
    return None


def _extract_probability_from_payload(payload: Any) -> float | None:
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        for key in _PROBABILITY_KEYS:
            if key in payload:
                return _extract_probability_from_payload(payload[key])
        for key in ("probabilities", "normalized_probabilities"):
            if key in payload:
                mapping = payload.get(key)
                if isinstance(mapping, Mapping):
                    return _extract_probability_from_mapping(mapping)
        return _extract_probability_from_mapping(payload)
    return _as_probability(payload)


def _extract_probability_from_mapping(mapping: Mapping[str, Any]) -> float | None:
    for key, value in mapping.items():
        if str(key).strip().casefold() in {"yes", "true"}:
            numeric = _as_probability(value)
            if numeric is not None:
                return numeric
    numeric_values = [_as_probability(value) for value in mapping.values()]
    numeric_values = [value for value in numeric_values if value is not None]
    if len(numeric_values) == 1:
        return numeric_values[0]
    return None


def _as_probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(numeric) or numeric < 0.0 or numeric > 1.0:
        return None
    return numeric


def _jsd_against_uniform(probabilities: Iterable[float]) -> float:
    counts = [0, 0, 0, 0]
    for probability in probabilities:
        index = _bin_index(probability)
        if index is None:
            continue
        counts[index] += 1
    total = sum(counts)
    if total <= 0:
        return 0.0
    distribution = [count / total for count in counts]
    uniform = [0.25, 0.25, 0.25, 0.25]
    mixture = [(p + u) / 2.0 for p, u in zip(distribution, uniform)]
    jsd = 0.0
    for p, u, m in zip(distribution, uniform, mixture):
        if p > 0:
            jsd += 0.5 * p * math.log2(p / m)
        if u > 0:
            jsd += 0.5 * u * math.log2(u / m)
    return jsd


def _bin_index(probability: float) -> int | None:
    if not math.isfinite(probability):
        return None
    if probability < 0.0 or probability > 1.0:
        return None
    if probability >= 1.0:
        return 3
    return min(int(probability * 4), 3)
