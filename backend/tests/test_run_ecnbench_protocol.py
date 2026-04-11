import json

import pytest

from scripts import run_ecnbench_protocol as protocol_script


def test_build_condition_matrix_counts_and_contents():
    events = [{"event_id": "E1"}, {"event_id": "E2"}]

    matrix = protocol_script.build_condition_matrix(events, repeats=2)

    assert len(matrix) == 12
    assert matrix[:6] == [
        {"event_id": "E1", "condition": "A", "repeat": 1},
        {"event_id": "E1", "condition": "A", "repeat": 2},
        {"event_id": "E1", "condition": "B", "repeat": 1},
        {"event_id": "E1", "condition": "B", "repeat": 2},
        {"event_id": "E1", "condition": "C", "repeat": 1},
        {"event_id": "E1", "condition": "C", "repeat": 2},
    ]


def test_resolve_default_injection_bank_prefers_first_existing_path(monkeypatch, tmp_path):
    first = tmp_path / "missing" / "step30_injection_bank.json"
    second = tmp_path / "data" / "injections" / "step30_injection_bank.json"
    second.parent.mkdir(parents=True, exist_ok=True)
    second.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        protocol_script,
        "_default_injection_bank_candidates",
        lambda: [first, second],
    )

    assert protocol_script._resolve_default_injection_bank() == str(second)


def test_resolve_default_injection_bank_returns_deterministic_fallback(monkeypatch, tmp_path):
    first = tmp_path / "missing" / "step30_injection_bank.json"
    second = tmp_path / "also_missing" / "step30_injection_bank.json"

    monkeypatch.setattr(
        protocol_script,
        "_default_injection_bank_candidates",
        lambda: [first, second],
    )

    assert protocol_script._resolve_default_injection_bank() == str(first)


def test_load_events_from_nested_payload_shape(tmp_path):
    payload = {
        "dataset": {
            "items": [
                {"id": "E1", "question": "Q1", "outcome": "A", "options": ["A", "B"]},
                {
                    "wrapper": {
                        "event": {
                            "event_id": "E2",
                            "question": "Q2",
                            "answer": "B",
                            "choices": ["A", "B", "C"],
                        }
                    }
                },
            ],
            "groups": [
                {
                    "nested": [
                        {"id": "E3", "question": "Q3", "label": "C", "options": {"A": 1, "C": 2}},
                    ]
                }
            ],
        }
    }
    path = tmp_path / "events.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    events = protocol_script.load_events_from_raw(path)

    assert [event["event_id"] for event in events] == ["E1", "E2", "E3"]
    assert events[0]["question"] == "Q1"
    assert events[0]["outcome"] == "A"
    assert events[1]["outcome"] == "B"
    assert events[2]["outcome"] == "C"
    assert events[2]["options"] == [1, 2]


def test_build_event_result_row_full_simulation_completed_logic():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    incomplete = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=False,
        probabilities={"A": 1.0},
        brier=0.0,
    )
    complete = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 1.0},
        brier=0.0,
    )

    assert incomplete["full_simulation_completed"] is False
    assert complete["full_simulation_completed"] is True


def test_write_summary_includes_failure_counts(tmp_path):
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "full_simulation_completed": True,
            "simulation_status": "completed",
        },
        {
            "condition": "B",
            "brier": None,
            "full_simulation_completed": False,
            "simulation_status": "simulation_failed",
        },
        {
            "condition": "C",
            "brier": None,
            "full_simulation_completed": False,
            "simulation_status": "evaluation_failed",
        },
    ]

    summary = protocol_script.write_summary(tmp_path, rows)
    written = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert summary == written
    assert summary["simulation_failure_count"] == 1
    assert summary["evaluation_failure_count"] == 1
    assert summary["full_simulation_completed_count"] == 1
