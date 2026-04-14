"""Load and validate Layer 2/3 benchmark configuration (layer23_v1)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List

REQUIRED_LAYER23_KEYS: set[str] = {
    "version",
    "kappa_cutoff",
    "jsd_monotonic_tolerance_epsilon",
    "leakage_min_days_before_resolution",
    "leakage_outcome_regex",
    "power_target_delta_brier",
    "power_assumed_sigma",
    "power_target",
    "calibration_brackets",
}


def _require_finite_number(name: str, value: object, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and numeric < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and numeric > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return numeric


def _require_integer(name: str, value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    if value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _require_non_empty_string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_calibration_brackets(value: object) -> List[List[float]]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("calibration_brackets must be exactly four contiguous bins from 0 to 1")

    expected_left = 0.0
    brackets: List[List[float]] = []
    for bracket in value:
        if not isinstance(bracket, list) or len(bracket) != 2:
            raise ValueError("calibration_brackets must be exactly four contiguous bins from 0 to 1")
        left, right = bracket
        left_num = _require_finite_number("calibration_brackets", left)
        right_num = _require_finite_number("calibration_brackets", right)
        if left_num != expected_left or right_num <= left_num:
            raise ValueError("calibration_brackets must be exactly four contiguous bins from 0 to 1")
        brackets.append([left_num, right_num])
        expected_left = right_num

    if brackets[0][0] != 0.0 or brackets[-1][1] != 1.0:
        raise ValueError("calibration_brackets must be exactly four contiguous bins from 0 to 1")

    return brackets


def load_layer23_config(path: Path | str) -> Dict[str, object]:
    """Load Layer 2/3 benchmark config from JSON and validate the contract."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("layer23 config must be a JSON object")

    keys = set(payload.keys())
    missing = REQUIRED_LAYER23_KEYS - keys
    extra = keys - REQUIRED_LAYER23_KEYS
    if missing:
        raise ValueError(f"missing required layer23 config keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"unexpected keys: {sorted(extra)}")

    if payload.get("version") != "layer23_v1":
        raise ValueError('unsupported layer23 config version: expected "layer23_v1"')

    _require_finite_number("kappa_cutoff", payload.get("kappa_cutoff"), minimum=0.0, maximum=1.0)
    _require_finite_number(
        "jsd_monotonic_tolerance_epsilon",
        payload.get("jsd_monotonic_tolerance_epsilon"),
        minimum=0.0,
    )
    _require_integer("leakage_min_days_before_resolution", payload.get("leakage_min_days_before_resolution"), minimum=7)
    leakage_outcome_regex = _require_non_empty_string("leakage_outcome_regex", payload.get("leakage_outcome_regex"))
    try:
        re.compile(leakage_outcome_regex)
    except re.error as exc:
        raise ValueError(f"invalid leakage_outcome_regex: {exc}") from exc
    _require_finite_number("power_target_delta_brier", payload.get("power_target_delta_brier"), minimum=0.0)
    if float(payload.get("power_target_delta_brier")) <= 0.0:
        raise ValueError("power_target_delta_brier must be > 0")
    _require_finite_number("power_assumed_sigma", payload.get("power_assumed_sigma"), minimum=0.0)
    if float(payload.get("power_assumed_sigma")) <= 0.0:
        raise ValueError("power_assumed_sigma must be > 0")
    _require_finite_number("power_target", payload.get("power_target"), minimum=0.0, maximum=1.0)
    if not (0.0 < float(payload.get("power_target")) < 1.0):
        raise ValueError("power_target must be in (0, 1)")
    payload["calibration_brackets"] = _validate_calibration_brackets(payload.get("calibration_brackets"))

    return payload
