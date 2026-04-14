import json
from pathlib import Path

import pytest

from app.benchmarks.phase1_registry import REQUIRED_PHASE1_KEYS, load_phase1_config


def test_load_phase1_happy_path(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "phase1_v1",
        "telemetry_checkpoints": [12, 24, 36, 48, 60],
        "jsd_monotonic_tolerance_epsilon": 0.002,
        "prior_sum_tolerance": 1e-6,
        "min_parsed_probability_ratio": 0.25,
        "baseline_agents": ["uniform_random", "market_prior"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    spec = load_phase1_config(path)

    assert spec["version"] == "phase1_v1"
    assert set(spec.keys()) == REQUIRED_PHASE1_KEYS


def test_load_phase1_missing_required_key(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "phase1_v1",
        "telemetry_checkpoints": [12, 24, 36, 48, 60],
        # missing jsd_monotonic_tolerance_epsilon
        "prior_sum_tolerance": 1e-6,
        "min_parsed_probability_ratio": 1e-5,
        "baseline_agents": ["uniform_random", "market_prior"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required phase1 config keys"):
        load_phase1_config(path)


def test_load_phase1_invalid_telemetry_checkpoints(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "phase1_v1",
        "telemetry_checkpoints": [1, 2, 3],
        "jsd_monotonic_tolerance_epsilon": 1e-8,
        "prior_sum_tolerance": 1e-6,
        "min_parsed_probability_ratio": 1e-5,
        "baseline_agents": ["uniform_random", "market_prior"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="telemetry_checkpoints must be exactly"):
        load_phase1_config(path)


def test_load_phase1_rejects_extra_keys(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "phase1_v1",
        "telemetry_checkpoints": [12, 24, 36, 48, 60],
        "jsd_monotonic_tolerance_epsilon": 0.002,
        "prior_sum_tolerance": 1e-6,
        "min_parsed_probability_ratio": 0.25,
        "baseline_agents": ["uniform_random", "market_prior"],
        "unexpected": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected keys"):
        load_phase1_config(path)


def test_load_phase1_rejects_invalid_version(tmp_path):
    path = tmp_path / "phase1.json"
    payload = {
        "version": "phase1_v2",
        "telemetry_checkpoints": [12, 24, 36, 48, 60],
        "jsd_monotonic_tolerance_epsilon": 0.002,
        "prior_sum_tolerance": 1e-6,
        "min_parsed_probability_ratio": 0.25,
        "baseline_agents": ["uniform_random", "market_prior"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported phase1 config version"):
        load_phase1_config(path)


def test_load_phase1_non_object_payload(tmp_path):
    path = tmp_path / "phase1.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ValueError, match="phase1 config must be a JSON object"):
        load_phase1_config(path)
