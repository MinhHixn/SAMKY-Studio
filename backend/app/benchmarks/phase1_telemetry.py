"""Telemetry extraction helpers for Phase 1 convergence signals."""

from __future__ import annotations

import json
import math
import re
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

_TEXT_PROBABILITY_PATTERN = re.compile(
    r"p\(\s*(?P<label>[^)]+?)\s*\)\s*=\s*(?P<value>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
    re.IGNORECASE,
)
_LABEL_PATTERN = re.compile(r"p\(\s*(?P<label>[^)]+?)\s*\)", re.IGNORECASE)
_NUMERIC_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_TEXT_FALLBACK_ACTION_TYPES = {"CREATE_POST", "QUOTE_POST", "CREATE_COMMENT", "TELEMETRY_PROBE", "INTERVIEW"}


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
    resolved_label: str | None = None,
) -> list[float]:
    unit_path = Path(unit_dir)
    checkpoint_list = [int(checkpoint) for checkpoint in checkpoints]
    totals_by_round: dict[int, int] = {}
    probabilities_by_round: dict[int, list[float]] = {}

    for log_path in (
        unit_path / "twitter" / "actions.jsonl",
        unit_path / "reddit" / "actions.jsonl",
    ):
        if not log_path.exists():
            continue
        for entry in _read_actions(log_path):
            round_num = _extract_round(entry)
            if round_num is None:
                continue
            if _is_round_marker(entry):
                continue
            totals_by_round[round_num] = totals_by_round.get(round_num, 0) + 1
            probability = _extract_probability(entry, resolved_label)
            if probability is not None:
                probabilities_by_round.setdefault(round_num, []).append(probability)

    trace: list[float] = []
    min_ratio = float(min_parsed_probability_ratio)
    for checkpoint in checkpoint_list:
        total = totals_by_round.get(checkpoint, 0)
        parsed_probabilities = list(probabilities_by_round.get(checkpoint, []))
        if total == 0:
            fallback_round = _latest_nonempty_round_before(checkpoint, totals_by_round)
            if fallback_round is not None:
                total = totals_by_round.get(fallback_round, 0)
                parsed_probabilities = list(probabilities_by_round.get(fallback_round, []))
        parsed = len(parsed_probabilities)
        ratio = parsed / total if total else 0.0
        if ratio < min_ratio:
            raise ValueError(
                f"Telemetry probability coverage below minimum at round {checkpoint}: "
                f"{parsed}/{total} ({ratio:.3f})"
            )
        trace.append(_jsd_against_uniform(parsed_probabilities))
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


def _extract_probability(entry: Mapping[str, Any], resolved_label: str | None) -> float | None:
    for payload in (
        entry.get("action_args"),
        entry.get("result"),
        entry.get("response"),
        entry,
    ):
        probability = _extract_probability_from_payload(payload, resolved_label)
        if probability is not None:
            return probability
    fallback_probability = _extract_fallback_probability(entry)
    if fallback_probability is not None:
        return fallback_probability
    return None


def _latest_nonempty_round_before(checkpoint: int, totals_by_round: Mapping[int, int]) -> int | None:
    candidates = [round_num for round_num, total in totals_by_round.items() if round_num < checkpoint and total > 0]
    if not candidates:
        return None
    return max(candidates)


def _extract_fallback_probability(entry: Mapping[str, Any]) -> float | None:
    action_type = entry.get("action_type")
    if not isinstance(action_type, str) or action_type.strip().upper() not in _TEXT_FALLBACK_ACTION_TYPES:
        return None

    for payload in (entry.get("action_args"), entry.get("result"), entry.get("response"), entry):
        if not isinstance(payload, Mapping):
            continue
        for key in ("content", "post_content", "quote_content", "comment_content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                parsed = _extract_numeric_probability_from_text(value)
                if parsed is not None:
                    return parsed
                # If action contains narrative text but no explicit probability, use neutral fallback.
                return 0.5
    return None


def _extract_numeric_probability_from_text(text: str) -> float | None:
    matched_probability = _parse_probability_text(text, resolved_label=None)
    if matched_probability is not None:
        return matched_probability
    for match in _NUMERIC_PATTERN.finditer(text):
        try:
            numeric = float(match.group(0))
        except ValueError:
            continue
        normalized = _normalize_probability(numeric)
        if normalized is not None:
            return normalized
    return None


def _extract_probability_from_payload(payload: Any, resolved_label: str | None) -> float | None:
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        for key in _PROBABILITY_KEYS:
            if key in payload:
                return _extract_probability_from_payload(payload[key], resolved_label)
        for key in ("probabilities", "normalized_probabilities"):
            if key in payload:
                mapping = payload.get(key)
                if isinstance(mapping, Mapping):
                    return _extract_probability_from_mapping(mapping, resolved_label)
        return _extract_probability_from_mapping(payload, resolved_label)
    return _as_probability(payload, resolved_label)


def _extract_probability_from_mapping(mapping: Mapping[str, Any], resolved_label: str | None) -> float | None:
    resolved_norm = _normalize_label(resolved_label)
    if resolved_norm:
        for key, value in mapping.items():
            label = _extract_label_from_key(key)
            if label == resolved_norm:
                numeric = _as_probability(value, resolved_label)
                if numeric is not None:
                    return numeric
            key_probability = _parse_probability_text(str(key), resolved_label)
            if key_probability is not None:
                return key_probability
        return None
    else:
        for key, value in mapping.items():
            label = _extract_label_from_key(key)
            if label in {"yes", "true"}:
                numeric = _as_probability(value, resolved_label)
                if numeric is not None:
                    return numeric
            key_probability = _parse_probability_text(str(key), resolved_label)
            if key_probability is not None:
                return key_probability
    numeric_values = [_as_probability(value, resolved_label) for value in mapping.values()]
    numeric_values = [value for value in numeric_values if value is not None]
    if len(numeric_values) == 1:
        return numeric_values[0]
    return None


def _normalize_probability(numeric: float) -> float | None:
    if not math.isfinite(numeric) or numeric < 0.0 or numeric > 1.0:
        return None
    return numeric


def _normalize_label(label: str | None) -> str | None:
    if label is None:
        return None
    normalized = str(label).strip()
    if not normalized:
        return None
    return normalized.casefold()


def _extract_label_from_key(key: Any) -> str | None:
    if not isinstance(key, str):
        return None
    stripped = key.strip()
    if not stripped:
        return None
    match = _LABEL_PATTERN.fullmatch(stripped)
    if match:
        return match.group("label").strip().casefold()
    return stripped.casefold()


def _parse_probability_text(text: str, resolved_label: str | None) -> float | None:
    match = _TEXT_PROBABILITY_PATTERN.search(text)
    if not match:
        return None
    label = match.group("label").strip().casefold()
    resolved_norm = _normalize_label(resolved_label)
    if resolved_norm is None:
        if label not in {"yes", "true"}:
            return None
    elif label != resolved_norm:
        return None
    try:
        numeric = float(match.group("value"))
    except ValueError:
        return None
    return _normalize_probability(numeric)


def _as_probability(value: Any, resolved_label: str | None) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _normalize_probability(float(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            numeric = float(stripped)
        except ValueError:
            return _parse_probability_text(stripped, resolved_label)
        return _normalize_probability(numeric)
    return None


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
