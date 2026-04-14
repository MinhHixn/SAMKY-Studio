"""Load and validate Phase 1 benchmark configuration (phase1_v1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict
import math

from .phase1_baselines import BASELINE_AGENT_IDS

REQUIRED_PHASE1_KEYS: set[str] = {
    "version",
    "telemetry_checkpoints",
    "jsd_monotonic_tolerance_epsilon",
    "prior_sum_tolerance",
    "min_parsed_probability_ratio",
    "baseline_agents",
}


def _require_non_negative(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number >= 0")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite number >= 0")
    return value


def _require_ratio(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number in [0, 1]")
    value = float(value)
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError(f"{name} must be a finite number in [0, 1]")
    return value


def load_phase1_config(path: Path | str) -> Dict[str, object]:
    """Load phase1_v1 benchmark config from JSON and validate required keys."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("phase1 config must be a JSON object")

    keys = set(payload.keys())
    missing = REQUIRED_PHASE1_KEYS - keys
    extra = keys - REQUIRED_PHASE1_KEYS
    if missing:
        raise ValueError(f"missing required phase1 config keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"unexpected keys: {sorted(extra)}")

    expected_checkpoints = [12, 24, 36, 48, 60]
    tc = payload.get("telemetry_checkpoints")
    if tc != expected_checkpoints:
        raise ValueError(f"telemetry_checkpoints must be exactly {expected_checkpoints}")

    if payload.get("version") != "phase1_v1":
        raise ValueError('unsupported phase1 config version: expected "phase1_v1"')

    _require_non_negative("jsd_monotonic_tolerance_epsilon", payload.get("jsd_monotonic_tolerance_epsilon"))
    _require_non_negative("prior_sum_tolerance", payload.get("prior_sum_tolerance"))
    _require_ratio("min_parsed_probability_ratio", payload.get("min_parsed_probability_ratio"))

    baseline_agents = payload.get("baseline_agents")
    expected_baseline_agents = list(BASELINE_AGENT_IDS)
    if (
        not isinstance(baseline_agents, list)
        or any(not isinstance(agent, str) for agent in baseline_agents)
        or baseline_agents != expected_baseline_agents
    ):
        raise ValueError(f"baseline_agents must be exactly {expected_baseline_agents}")

    return payload
