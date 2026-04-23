import json
from pathlib import Path

import pytest

from app.benchmarks.phase1_telemetry import (
    compute_round_jsd_trace,
    is_monotonic_nonincreasing_with_epsilon,
)


CHECKPOINTS = [12, 24, 36, 48, 60]


def _write_actions(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def test_compute_round_jsd_trace_parses_both_platforms(tmp_path):
    unit_dir = tmp_path / "unit"
    twitter_path = unit_dir / "twitter" / "actions.jsonl"
    reddit_path = unit_dir / "reddit" / "actions.jsonl"

    def entry(round_num: int, probability: float) -> dict:
        return {
            "round": round_num,
            "action_type": "INTERVIEW",
            "action_args": {"probability": probability},
        }

    twitter_entries = [
        entry(12, 0.1),
        entry(12, 0.3),
        entry(24, 0.05),
        entry(24, 0.1),
        entry(36, 0.1),
        entry(36, 0.3),
        entry(48, 0.1),
        entry(48, 0.3),
        entry(60, 0.1),
        entry(60, 0.3),
    ]
    reddit_entries = [
        entry(12, 0.6),
        entry(12, 0.9),
        entry(24, 0.2),
        entry(24, 0.24),
        entry(36, 0.6),
        entry(36, 0.9),
        entry(48, 0.6),
        entry(48, 0.9),
        entry(60, 0.6),
        entry(60, 0.9),
    ]

    _write_actions(twitter_path, twitter_entries)
    _write_actions(reddit_path, reddit_entries)

    trace = compute_round_jsd_trace(
        unit_dir,
        checkpoints=CHECKPOINTS,
        min_parsed_probability_ratio=0.5,
        resolved_label="YES",
    )

    assert trace[0] == pytest.approx(0.0)
    assert trace[1] == pytest.approx(0.5487949407, rel=1e-6)
    assert trace[2:] == pytest.approx([0.0, 0.0, 0.0])


def test_compute_round_jsd_trace_raises_on_low_coverage(tmp_path):
    unit_dir = tmp_path / "unit"
    twitter_path = unit_dir / "twitter" / "actions.jsonl"

    def entry(round_num: int, include_probability: bool) -> dict:
        payload = {"round": round_num, "action_type": "INTERVIEW", "action_args": {}}
        if include_probability:
            payload["action_args"]["probability"] = 0.2
        return payload

    entries = []
    for round_num in CHECKPOINTS:
        entries.append(entry(round_num, include_probability=True))
        entries.extend(entry(round_num, include_probability=False) for _ in range(3))

    _write_actions(twitter_path, entries)

    with pytest.raises(ValueError, match="coverage"):
        compute_round_jsd_trace(
            unit_dir,
            checkpoints=CHECKPOINTS,
            min_parsed_probability_ratio=0.5,
            resolved_label="YES",
        )


def test_compute_round_jsd_trace_ignores_non_probability_actions_for_coverage(tmp_path):
    unit_dir = tmp_path / "unit"
    twitter_path = unit_dir / "twitter" / "actions.jsonl"

    entries = [
        {"round": 12, "action_type": "TELEMETRY_PROBE", "action_args": {"yes_probability": 0.6}},
        {"round": 12, "action_type": "TELEMETRY_PROBE", "action_args": {"yes_probability": 0.4}},
    ]
    entries.extend(
        {"round": 12, "action_type": "LIKE_POST", "action_args": {"post_id": f"p{i}"}}
        for i in range(8)
    )

    _write_actions(twitter_path, entries)

    trace = compute_round_jsd_trace(
        unit_dir,
        checkpoints=[12],
        min_parsed_probability_ratio=0.5,
        resolved_label="YES",
    )

    assert len(trace) == 1
    assert trace[0] >= 0.0


def test_compute_round_jsd_trace_parses_probability_text_for_resolved_label(tmp_path):
    unit_dir = tmp_path / "unit"
    twitter_path = unit_dir / "twitter" / "actions.jsonl"

    entries = [
        {"round": 12, "action_type": "INTERVIEW", "action_args": {"prediction": "P(NO)=0.10"}},
        {"round": 12, "action_type": "INTERVIEW", "action_args": {"prediction": "P(NO)=0.30"}},
        {"round": 12, "action_type": "INTERVIEW", "action_args": {"prediction": "P(NO)=0.60"}},
        {"round": 12, "action_type": "INTERVIEW", "action_args": {"prediction": "P(NO)=0.90"}},
    ]

    _write_actions(twitter_path, entries)

    trace = compute_round_jsd_trace(
        unit_dir,
        checkpoints=[12],
        min_parsed_probability_ratio=1.0,
        resolved_label="NO",
    )

    assert trace == pytest.approx([0.0])


def test_compute_round_jsd_trace_skips_unmatched_resolved_label(tmp_path):
    unit_dir = tmp_path / "unit"
    twitter_path = unit_dir / "twitter" / "actions.jsonl"

    entries = [
        {
            "round": 12,
            "action_type": "INTERVIEW",
            "action_args": {"probabilities": {"NO": 0.9}},
        }
    ]

    _write_actions(twitter_path, entries)

    with pytest.raises(ValueError, match="coverage"):
        compute_round_jsd_trace(
            unit_dir,
            checkpoints=[12],
            min_parsed_probability_ratio=1.0,
            resolved_label="YES",
        )


def test_compute_round_jsd_trace_carries_forward_latest_nonempty_round(tmp_path):
    unit_dir = tmp_path / "unit"
    twitter_path = unit_dir / "twitter" / "actions.jsonl"
    entries = [
        {"round": 0, "action_type": "CREATE_POST", "action_args": {"content": "Market leaning yes but no number yet."}},
    ]
    _write_actions(twitter_path, entries)

    trace = compute_round_jsd_trace(
        unit_dir,
        checkpoints=[6],
        min_parsed_probability_ratio=1.0,
        resolved_label="YES",
    )

    assert trace == pytest.approx([0.5487949407], rel=1e-6)


def test_compute_round_jsd_trace_parses_percentage_fallback_from_text(tmp_path):
    unit_dir = tmp_path / "unit"
    twitter_path = unit_dir / "twitter" / "actions.jsonl"
    entries = [
        {"round": 12, "action_type": "CREATE_POST", "action_args": {"content": "Estimated win chance now at 63%."}},
        {"round": 12, "action_type": "CREATE_POST", "action_args": {"content": "Confidence update: 37%."}},
    ]
    _write_actions(twitter_path, entries)

    trace = compute_round_jsd_trace(
        unit_dir,
        checkpoints=[12],
        min_parsed_probability_ratio=1.0,
        resolved_label="YES",
    )

    assert trace[0] >= 0.0


def test_is_monotonic_nonincreasing_with_epsilon_allows_small_increase():
    assert is_monotonic_nonincreasing_with_epsilon([0.5, 0.48, 0.49], epsilon=0.02)
    assert not is_monotonic_nonincreasing_with_epsilon([0.5, 0.48, 0.53], epsilon=0.02)
