"""Load and validate fixed benchmark weights."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict

REQUIRED_WEIGHT_KEYS: set[str] = {
    "prediction_accuracy",
    "convergence",
    "susceptibility",
    "herd_effect",
    "dqi",
    "polarization",
    "info_diversity",
}


def load_benchmark_weights(path: Path | str) -> Dict[str, float]:
    """Load benchmark weights from JSON and validate the contract."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark weights must be a JSON object")

    keys = set(payload.keys())
    missing_keys = REQUIRED_WEIGHT_KEYS - keys
    extra_keys = keys - REQUIRED_WEIGHT_KEYS
    if missing_keys:
        raise ValueError(f"missing benchmark weight keys: {sorted(missing_keys)}")
    if extra_keys:
        raise ValueError(f"unexpected benchmark weight keys: {sorted(extra_keys)}")

    weights: Dict[str, float] = {}
    for key in sorted(REQUIRED_WEIGHT_KEYS):
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"benchmark weight {key!r} must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0.0:
            raise ValueError(f"benchmark weight {key!r} must be non-negative")
        weights[key] = numeric

    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"benchmark weights must sum to 1.0 within tolerance; got {total!r}")

    return weights
