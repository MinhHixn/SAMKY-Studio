import json
from pathlib import Path

import pytest

from app.benchmarks.weight_registry import REQUIRED_WEIGHT_KEYS, load_benchmark_weights


def test_load_benchmark_weights_happy_path(tmp_path):
    path = tmp_path / "weights.json"
    path.write_text(
        """
        {
          "prediction_accuracy": 0.30,
          "convergence": 0.20,
          "susceptibility": 0.15,
          "herd_effect": 0.15,
          "dqi": 0.10,
          "polarization": 0.05,
          "info_diversity": 0.05
        }
        """.strip(),
        encoding="utf-8",
    )

    weights = load_benchmark_weights(path)

    assert set(weights) == REQUIRED_WEIGHT_KEYS
    assert abs(sum(weights.values()) - 1.0) <= 1e-6


def test_load_benchmark_weights_rejects_missing_key(tmp_path):
    path = tmp_path / "weights.json"
    path.write_text(
        '{"prediction_accuracy":0.30,"convergence":0.20,"susceptibility":0.15,"herd_effect":0.15,"dqi":0.10,"polarization":0.05}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing benchmark weight keys"):
        load_benchmark_weights(path)


def test_load_benchmark_weights_rejects_extra_key(tmp_path):
    path = tmp_path / "weights.json"
    path.write_text(
        '{"prediction_accuracy":0.30,"convergence":0.20,"susceptibility":0.15,"herd_effect":0.15,"dqi":0.10,"polarization":0.05,"info_diversity":0.05,"bonus":0.0}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unexpected benchmark weight keys"):
        load_benchmark_weights(path)


def test_load_benchmark_weights_rejects_bad_sum(tmp_path):
    path = tmp_path / "weights.json"
    path.write_text(
        '{"prediction_accuracy":0.31,"convergence":0.20,"susceptibility":0.15,"herd_effect":0.15,"dqi":0.10,"polarization":0.05,"info_diversity":0.05}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sum to 1.0"):
        load_benchmark_weights(path)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("dqi", '"high"', "must be numeric"),
        ("polarization", -0.01, "must be non-negative"),
    ],
)
def test_load_benchmark_weights_rejects_invalid_values(tmp_path, key, value, message):
    path = tmp_path / "weights.json"
    payload = {
        "prediction_accuracy": 0.30,
        "convergence": 0.20,
        "susceptibility": 0.15,
        "herd_effect": 0.15,
        "dqi": 0.10,
        "polarization": 0.05,
        "info_diversity": 0.05,
    }
    payload[key] = value
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_benchmark_weights(path)
