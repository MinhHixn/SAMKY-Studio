"""Load and validate Phase 1 benchmark configuration (v1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

REQUIRED_PHASE1_KEYS: set[str] = {
    "version",
    "seed_mapping",
    "rounds",
    "agents",
}


def load_benchmark_phase1_config(path: Path | str) -> Dict[str, object]:
    """Load phase1 benchmark config from JSON and validate required keys."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark phase1 config must be a JSON object")

    keys = set(payload.keys())
    missing = REQUIRED_PHASE1_KEYS - keys
    extra = keys - REQUIRED_PHASE1_KEYS
    if missing:
        raise ValueError(f"missing required keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"unexpected keys: {sorted(extra)}")

    return payload
