import json
from pathlib import Path

import pytest

from app.benchmarks.phase1_registry import REQUIRED_PHASE1_KEYS, load_benchmark_phase1_config


def test_load_benchmark_phase1_happy_path(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "v1",
        "seed_mapping": "seeds_mapping.txt",
        "rounds": 4,
        "agents": 100,
        "telemetry_checkpoints": [12, 24, 36, 48, 60],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    spec = load_benchmark_phase1_config(path)

    assert spec["version"] == "v1"
    assert set(spec.keys()) == REQUIRED_PHASE1_KEYS


def test_load_benchmark_phase1_missing_required_key(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "v1",
        "seed_mapping": "seeds_mapping.txt",
        "rounds": 4,
        # "agents" missing
        "telemetry_checkpoints": [12, 24, 36, 48, 60],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required keys"):
        load_benchmark_phase1_config(path)


def test_load_benchmark_phase1_missing_telemetry_checkpoints(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "v1",
        "seed_mapping": "seeds_mapping.txt",
        "rounds": 4,
        "agents": 100,
        # telemetry_checkpoints missing
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required keys"):
        load_benchmark_phase1_config(path)


def test_load_benchmark_phase1_invalid_telemetry_checkpoints(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "v1",
        "seed_mapping": "seeds_mapping.txt",
        "rounds": 4,
        "agents": 100,
        "telemetry_checkpoints": [1, 2, 3],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="telemetry_checkpoints must be exactly"):
        load_benchmark_phase1_config(path)
