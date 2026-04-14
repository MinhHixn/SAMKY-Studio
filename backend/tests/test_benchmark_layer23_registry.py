import json
from pathlib import Path

import pytest

from app.benchmarks.layer23_registry import REQUIRED_LAYER23_KEYS, load_layer23_config


def _write_payload(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "layer23.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_layer23_happy_path(tmp_path):
    payload = {
        "version": "layer23_v1",
        "kappa_cutoff": 0.7,
        "jsd_monotonic_tolerance_epsilon": 0.002,
        "leakage_min_days_before_resolution": 14,
        "leakage_outcome_regex": r"(?i)resolved|closed",
        "power_target_delta_brier": 0.05,
        "power_assumed_sigma": 0.12,
        "power_target": 0.8,
        "calibration_brackets": [[0.0, 0.25], [0.25, 0.5], [0.5, 0.75], [0.75, 1.0]],
    }

    spec = load_layer23_config(_write_payload(tmp_path, payload))

    assert spec == payload
    assert set(spec.keys()) == REQUIRED_LAYER23_KEYS


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "version": "layer23_v1",
                "kappa_cutoff": 0.7,
                "jsd_monotonic_tolerance_epsilon": 0.002,
                "leakage_min_days_before_resolution": 14,
                "leakage_outcome_regex": r"(?i)resolved|closed",
                "power_target_delta_brier": 0.05,
                "power_assumed_sigma": 0.12,
                "power_target": 0.8,
            },
            "missing required layer23 config keys",
        ),
        (
            {
                "version": "layer23_v1",
                "kappa_cutoff": 0.7,
                "jsd_monotonic_tolerance_epsilon": 0.002,
                "leakage_min_days_before_resolution": 14,
                "leakage_outcome_regex": r"(?i)resolved|closed",
                "power_target_delta_brier": 0.05,
                "power_assumed_sigma": 0.12,
                "power_target": 0.8,
                "calibration_brackets": [[0.0, 0.25], [0.25, 0.5], [0.5, 0.75], [0.75, 1.0]],
                "unexpected": True,
            },
            "unexpected keys",
        ),
    ],
)
def test_load_layer23_contract_keys(payload, message, tmp_path):
    with pytest.raises(ValueError, match=message):
        load_layer23_config(_write_payload(tmp_path, payload))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", "layer23_v2", "unsupported layer23 config version"),
        ("kappa_cutoff", -0.1, "kappa_cutoff"),
        ("kappa_cutoff", 1.1, "kappa_cutoff"),
        ("jsd_monotonic_tolerance_epsilon", float("inf"), "jsd_monotonic_tolerance_epsilon"),
        ("jsd_monotonic_tolerance_epsilon", -0.1, "jsd_monotonic_tolerance_epsilon"),
        ("leakage_min_days_before_resolution", -1, "leakage_min_days_before_resolution"),
        ("leakage_min_days_before_resolution", 1.5, "leakage_min_days_before_resolution"),
        ("leakage_outcome_regex", "", "leakage_outcome_regex"),
        ("leakage_outcome_regex", "(", "invalid leakage_outcome_regex"),
        ("power_target_delta_brier", 0.0, "power_target_delta_brier"),
        ("power_target_delta_brier", float("nan"), "power_target_delta_brier"),
        ("power_assumed_sigma", 0.0, "power_assumed_sigma"),
        ("power_assumed_sigma", float("inf"), "power_assumed_sigma"),
        ("power_target", 0.0, "power_target"),
        ("power_target", 1.0, "power_target"),
        (
            "calibration_brackets",
            [[0.1, 0.25], [0.25, 0.5], [0.5, 0.75], [0.75, 1.0]],
            "calibration_brackets",
        ),
        (
            "calibration_brackets",
            [[0.0, 0.25], [0.25, 0.5], [0.51, 0.75], [0.75, 1.0]],
            "calibration_brackets",
        ),
        (
            "calibration_brackets",
            [[0.0, 0.25], [0.25, 0.5], [0.5, 0.75]],
            "calibration_brackets",
        ),
    ],
)
def test_load_layer23_rejects_invalid_values(field, value, message, tmp_path):
    payload = {
        "version": "layer23_v1",
        "kappa_cutoff": 0.7,
        "jsd_monotonic_tolerance_epsilon": 0.002,
        "leakage_min_days_before_resolution": 14,
        "leakage_outcome_regex": r"(?i)resolved|closed",
        "power_target_delta_brier": 0.05,
        "power_assumed_sigma": 0.12,
        "power_target": 0.8,
        "calibration_brackets": [[0.0, 0.25], [0.25, 0.5], [0.5, 0.75], [0.75, 1.0]],
    }
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        load_layer23_config(_write_payload(tmp_path, payload))


def test_layer23_bundled_config_validates():
    config_path = Path(__file__).resolve().parents[1] / "config" / "benchmark_layer23_v1.json"

    spec = load_layer23_config(config_path)

    assert spec["version"] == "layer23_v1"
    assert set(spec.keys()) == REQUIRED_LAYER23_KEYS
