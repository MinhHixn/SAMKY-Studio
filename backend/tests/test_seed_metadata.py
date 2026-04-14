import json

import pytest

from app.benchmarks.seed_metadata import load_seed_metadata


def test_load_seed_metadata_accepts_valid_injection_direction(tmp_path):
    seed_dir = tmp_path / "seed-1"
    seed_dir.mkdir()
    (seed_dir / "metadata.json").write_text(
        json.dumps({"event_id": "E1", "injection_direction": "pro_YES"}),
        encoding="utf-8",
    )

    metadata = load_seed_metadata(seed_dir)

    assert metadata["event_id"] == "E1"
    assert metadata["injection_direction"] == "pro_YES"


def test_load_seed_metadata_rejects_invalid_injection_direction(tmp_path):
    seed_dir = tmp_path / "seed-1"
    seed_dir.mkdir()
    (seed_dir / "metadata.json").write_text(
        json.dumps({"event_id": "E1", "injection_direction": "sideways"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        load_seed_metadata(seed_dir)

    assert "injection_direction" in str(exc.value)
