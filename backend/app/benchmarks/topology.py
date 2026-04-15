"""Topology metadata and conformity telemetry helpers."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

_ROUND_TARGETS = {1, 3}
_DEGREE_KEYS = (
    "degree_distribution_descriptor",
    "degree_distribution",
    "degree_distribution_type",
    "degree_model",
)
_CLUSTERING_KEYS = (
    "clustering_coefficient",
    "avg_clustering_coefficient",
    "target_clustering",
    "clustering",
)
_AGENT_ID_KEYS = ("agent_id", "actor_id", "user_id", "entity_uuid", "username")
_YES_VALUE_KEYS = ("p_yes", "yes_probability", "yes_prob", "prob_yes")
_TEXT_PROBABILITY_PATTERN = re.compile(
    r"p\(\s*(?P<label>[^)]+?)\s*\)\s*=\s*(?P<value>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
    re.IGNORECASE,
)


def extract_topology_metadata(config_or_defaults: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = config_or_defaults if isinstance(config_or_defaults, Mapping) else {}
    simulation_payload = payload.get("simulation_config")
    benchmark_defaults = payload.get("benchmark_defaults")
    simulation_degree = _find_first_descriptor(simulation_payload, _DEGREE_KEYS)
    simulation_clustering = _find_first_float(simulation_payload, _CLUSTERING_KEYS)
    default_degree = _find_first_descriptor(benchmark_defaults, _DEGREE_KEYS)
    default_clustering = _find_first_float(benchmark_defaults, _CLUSTERING_KEYS)

    if simulation_degree is not None or simulation_clustering is not None:
        source = "simulation_config"
    else:
        source = "benchmark_defaults"

    degree_descriptor = simulation_degree or default_degree or "oasis-default-unspecified"
    clustering_coefficient = simulation_clustering
    if clustering_coefficient is None:
        clustering_coefficient = default_clustering

    topology: dict[str, Any] = {
        "source": source,
        "degree_distribution_descriptor": degree_descriptor,
        "clustering_coefficient": clustering_coefficient,
    }
    if isinstance(benchmark_defaults, Mapping) and benchmark_defaults:
        topology["declared_topology_parameters"] = _json_safe_mapping(benchmark_defaults)
    return topology


def compute_delta_conformity(unit_dir: Path | str) -> float | None:
    rounds: dict[int, dict[str, float]] = {1: {}, 3: {}}
    unit_path = Path(unit_dir)

    for log_path in (unit_path / "twitter" / "actions.jsonl", unit_path / "reddit" / "actions.jsonl"):
        if not log_path.exists():
            continue
        for entry in _read_actions(log_path):
            if _is_round_marker(entry):
                continue
            round_num = _extract_round(entry)
            if round_num not in _ROUND_TARGETS:
                continue
            agent_id = _extract_agent_id(entry)
            if agent_id is None:
                continue
            probability_yes = _extract_probability_yes(entry)
            if probability_yes is None:
                continue
            rounds[round_num][agent_id] = probability_yes

    round3_probabilities = rounds[3]
    if not round3_probabilities:
        return None

    yes_count = sum(1 for probability in round3_probabilities.values() if probability >= 0.5)
    no_count = len(round3_probabilities) - yes_count
    if yes_count == no_count:
        return None
    plurality_is_yes = yes_count > no_count

    common_agents = set(rounds[1]).intersection(round3_probabilities)
    if not common_agents:
        return None

    changed_to_plurality = 0
    for agent_id in common_agents:
        round1_stance_is_yes = rounds[1][agent_id] >= 0.5
        round3_stance_is_yes = round3_probabilities[agent_id] >= 0.5
        if round1_stance_is_yes != round3_stance_is_yes and round3_stance_is_yes == plurality_is_yes:
            changed_to_plurality += 1

    return round(changed_to_plurality / len(common_agents), 6)


def _iter_mappings(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        yield payload
        for value in payload.values():
            yield from _iter_mappings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _iter_mappings(value)


def _find_first_descriptor(payload: Any, keys: Iterable[str]) -> str | None:
    for mapping in _iter_mappings(payload):
        for key in keys:
            if key not in mapping:
                continue
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                return str(value)
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return None


def _find_first_float(payload: Any, keys: Iterable[str]) -> float | None:
    for mapping in _iter_mappings(payload):
        for key in keys:
            if key not in mapping:
                continue
            value = _as_probability(mapping.get(key))
            if value is not None:
                return value
    return None


def _json_safe_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _read_actions(path: Path) -> Iterable[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, Mapping):
                yield entry


def _is_round_marker(entry: Mapping[str, Any]) -> bool:
    return "event_type" in entry


def _extract_round(entry: Mapping[str, Any]) -> int | None:
    raw = entry.get("round")
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _extract_agent_id(entry: Mapping[str, Any]) -> str | None:
    for payload in (entry, entry.get("action_args"), entry.get("result"), entry.get("response")):
        if not isinstance(payload, Mapping):
            continue
        for key in _AGENT_ID_KEYS:
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return None


def _extract_probability_yes(entry: Mapping[str, Any]) -> float | None:
    for payload in (entry.get("action_args"), entry.get("result"), entry.get("response"), entry):
        probability = _extract_probability_yes_from_payload(payload)
        if probability is not None:
            return probability
    return None


def _extract_probability_yes_from_payload(payload: Any) -> float | None:
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        for key in _YES_VALUE_KEYS:
            probability = _as_probability(payload.get(key))
            if probability is not None:
                return probability
        for key in ("probabilities", "normalized_probabilities"):
            mapping = payload.get(key)
            if isinstance(mapping, Mapping):
                probability = _extract_probability_yes_from_mapping(mapping)
                if probability is not None:
                    return probability
        probability = _extract_probability_yes_from_mapping(payload)
        if probability is not None:
            return probability
    if isinstance(payload, list):
        for value in payload:
            probability = _extract_probability_yes_from_payload(value)
            if probability is not None:
                return probability
        return None
    return _as_probability_text(payload)


def _extract_probability_yes_from_mapping(payload: Mapping[str, Any]) -> float | None:
    for key, value in payload.items():
        normalized_key = str(key).strip().casefold()
        if normalized_key in {"yes", "true", "p_yes"}:
            probability = _as_probability(value)
            if probability is not None:
                return probability
        probability_from_key = _as_probability_text(key)
        if probability_from_key is not None:
            return probability_from_key
    return None


def _as_probability_text(value: Any) -> float | None:
    if isinstance(value, str):
        match = _TEXT_PROBABILITY_PATTERN.search(value)
        if not match:
            return None
        if match.group("label").strip().casefold() not in {"yes", "true"}:
            return None
        try:
            return _as_probability(float(match.group("value")))
        except ValueError:
            return None
    return None


def _as_probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            numeric = float(stripped)
        except ValueError:
            return _as_probability_text(stripped)
    elif isinstance(value, (int, float)):
        numeric = float(value)
    else:
        return None
    if not math.isfinite(numeric):
        return None
    if numeric < 0.0 or numeric > 1.0:
        return None
    return numeric
