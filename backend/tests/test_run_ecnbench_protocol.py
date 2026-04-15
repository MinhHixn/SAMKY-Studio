import json
import subprocess
from pathlib import Path

import pytest

from scripts import run_ecnbench_protocol as protocol_script


@pytest.fixture(autouse=True)
def _disable_leakage_preflight_for_non_leakage_tests(monkeypatch, request):
    if "leakage" not in request.node.name:
        monkeypatch.setattr(protocol_script, "validate_leakage_preflight", lambda *_args, **_kwargs: None)


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


def test_default_injection_bank_candidates_scan_ancestors_and_deduplicate(monkeypatch, tmp_path):
    scripts_dir = tmp_path / "workspace" / "backend" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    workspace_candidate = tmp_path / "workspace" / "data" / "injections" / "step30_injection_bank.json"
    workspace_candidate.parent.mkdir(parents=True, exist_ok=True)
    workspace_candidate.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(protocol_script, "_SCRIPTS_DIR", scripts_dir)

    candidates = protocol_script._default_injection_bank_candidates()

    assert workspace_candidate.resolve() in candidates
    assert len(candidates) == len({str(path).lower() for path in candidates})


def test_default_output_dir_is_backend_absolute_path():
    assert protocol_script.DEFAULT_OUTPUT_DIR.is_absolute()
    assert protocol_script.DEFAULT_OUTPUT_DIR.parts[-3:] == ("backend", "logs", "benchmark_runs")


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


def test_load_events_ignores_taxonomy_key_value_maps(tmp_path):
    payload = {
        "study": {
            "taxonomy_axes": {
                "axis_2_resolution_horizon": {
                    "short": "2-4 weeks",
                    "medium": "1-3 months",
                }
            }
        },
        "core_events": [{"id": "S2", "question": "Q", "outcome": "YES"}],
    }
    path = tmp_path / "events.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    events = protocol_script.load_events_from_raw(path)

    assert [event["event_id"] for event in events] == ["S2"]


def test_validate_injection_coverage_raises_for_missing_event_id():
    class DummyInjectionLoader:
        def has_event(self, event_id):
            return event_id == "E1"

        def get_payload(self, event_id, condition):
            return {"event_id": event_id, "condition": condition}

    events = [{"event_id": "E1"}, {"event_id": "E2"}, {"event_id": "E3"}]

    with pytest.raises(ValueError) as exc:
        protocol_script.validate_injection_coverage(events, DummyInjectionLoader())

    message = str(exc.value)
    assert "E2" in message
    assert "E3" in message
    assert "missing event id" in message


def test_validate_injection_coverage_raises_for_missing_b_payload():
    class DummyInjectionLoader:
        def has_event(self, event_id):
            return True

        def get_payload(self, event_id, condition):
            if condition == "B":
                raise KeyError(f"Missing 'relevant_update' payload for event_id: {event_id}")
            return {"event_id": event_id, "condition": condition}

    with pytest.raises(ValueError) as exc:
        protocol_script.validate_injection_coverage([{"event_id": "E1"}], DummyInjectionLoader())

    message = str(exc.value)
    assert "E1" in message
    assert "B" in message
    assert "relevant_update" in message


def test_validate_injection_coverage_raises_for_missing_c_payload():
    class DummyInjectionLoader:
        def has_event(self, event_id):
            return True

        def get_payload(self, event_id, condition):
            if condition == "C":
                raise KeyError(f"Missing 'null_update' payload for event_id: {event_id}")
            return {"event_id": event_id, "condition": condition}

    with pytest.raises(ValueError) as exc:
        protocol_script.validate_injection_coverage([{"event_id": "E1"}], DummyInjectionLoader())

    message = str(exc.value)
    assert "E1" in message
    assert "C" in message
    assert "null_update" in message


def test_validate_injection_coverage_happy_path():
    class DummyInjectionLoader:
        def has_event(self, event_id):
            return event_id in {"E1", "E2"}

        def get_payload(self, event_id, condition):
            return {"event_id": event_id, "condition": condition}

    protocol_script.validate_injection_coverage(
        [{"event_id": "E1"}, {"event_id": "E2"}],
        DummyInjectionLoader(),
    )


def test_load_events_keeps_scalar_events_with_metadata_keys(tmp_path):
    payload = {
        "study": {
            "event": {
                "id": "M1",
                "question": "Q",
                "outcome": "YES",
                "source": "ecnb-event-pack",
                "category": "geopolitics",
            }
        }
    }
    path = tmp_path / "events.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    events = protocol_script.load_events_from_raw(path)

    assert [event["event_id"] for event in events] == ["M1"]
    assert events[0]["source"] == "ecnb-event-pack"
    assert events[0]["category"] == "geopolitics"


def test_main_fails_on_invalid_polymarket_prior_before_condition_matrix(monkeypatch, tmp_path):
    events = [
        {
            "event_id": "E1",
            "question": "Q1",
            "outcome": "YES",
            "options": ["YES", "NO"],
            "polymarket_opening_prior": {"YES": 0.5, "NO": 0.4, "MAYBE": 0.1},
        }
    ]

    class DummyRouter:
        @staticmethod
        def from_config():
            return DummyRouter()

        def model_for(self, _name):
            return "dummy-model"

    def fail_build_condition_matrix(*_args, **_kwargs):
        pytest.fail("build_condition_matrix should not run before polymarket prior validation")

    monkeypatch.setattr(protocol_script, "BenchmarkRoleRouter", DummyRouter)
    monkeypatch.setattr(protocol_script, "load_events_from_raw", lambda *_args, **_kwargs: events)
    monkeypatch.setattr(protocol_script, "load_seed_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(protocol_script, "build_profiles", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(protocol_script, "validate_injection_coverage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(protocol_script, "load_phase1_config", lambda *_args, **_kwargs: {"prior_sum_tolerance": 1e-6})
    monkeypatch.setattr(protocol_script, "Step30InjectionLoader", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(protocol_script, "build_condition_matrix", fail_build_condition_matrix)

    monkeypatch.setattr(
        protocol_script.sys,
        "argv",
        [
            "run_ecnbench_protocol.py",
            "--seeds-dir",
            str(tmp_path),
            "--events-raw",
            str(tmp_path / "events.json"),
            "--injection-bank",
            str(tmp_path / "injection.json"),
            "--output-dir",
            str(tmp_path / "output"),
        ],
    )

    with pytest.raises(ValueError, match="polymarket_opening_prior"):
        protocol_script.main()


def test_main_fails_on_leakage_before_condition_matrix(monkeypatch, tmp_path):
    seed_file = tmp_path / "seed.txt"
    seed_file.write_text("The outcome was resolved in advance.", encoding="utf-8")
    events = [
        {
            "event_id": "E1",
            "question": "Q1",
            "outcome": "YES",
            "options": ["YES", "NO"],
            "seed_date": "2024-01-01",
            "resolution_date": "2024-01-10",
        }
    ]

    class DummyRouter:
        @staticmethod
        def from_config():
            return DummyRouter()

        def model_for(self, _name):
            return "dummy-model"

    def fail_build_condition_matrix(*_args, **_kwargs):
        pytest.fail("build_condition_matrix should not run before leakage preflight")

    monkeypatch.setattr(protocol_script, "BenchmarkRoleRouter", DummyRouter)
    monkeypatch.setattr(protocol_script, "BASELINE_AGENT_IDS", [])
    monkeypatch.setattr(protocol_script, "load_events_from_raw", lambda *_args, **_kwargs: events)
    monkeypatch.setattr(protocol_script, "load_seed_files", lambda *_args, **_kwargs: [seed_file])
    monkeypatch.setattr(protocol_script, "build_profiles", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(protocol_script, "validate_injection_coverage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        protocol_script,
        "load_phase1_config",
        lambda *_args, **_kwargs: {
            "prior_sum_tolerance": 1e-6,
            "baseline_agents": [],
            "version": "v1",
            "jsd_monotonic_tolerance_epsilon": 0.0,
            "telemetry_checkpoints": [],
        },
    )
    monkeypatch.setattr(protocol_script, "load_layer23_config", lambda *_args, **_kwargs: {"leakage_min_days_before_resolution": 7, "leakage_outcome_regex": r"resolved|closed"})
    monkeypatch.setattr(protocol_script, "Step30InjectionLoader", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(protocol_script, "build_condition_matrix", fail_build_condition_matrix)
    monkeypatch.setattr(protocol_script, "validate_polymarket_opening_prior", lambda *_args, **_kwargs: None)

    monkeypatch.setattr(
        protocol_script.sys,
        "argv",
        [
            "run_ecnbench_protocol.py",
            "--seeds-dir",
            str(tmp_path),
            "--events-raw",
            str(tmp_path / "events.json"),
            "--injection-bank",
            str(tmp_path / "injection.json"),
            "--output-dir",
            str(tmp_path / "output"),
        ],
    )

    with pytest.raises(ValueError, match="Leakage preflight failed"):
        protocol_script.main()


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
    assert incomplete["unit_id"] == "E1_A_r1"
    assert complete["unit_id"] == "E1_A_r1"


def test_build_event_result_row_includes_simulation_executed_flag():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}
    row = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 1.0},
        brier=0.0,
        simulation_executed=False,
    )
    assert "simulation_executed" in row
    assert row["simulation_executed"] is False


def test_build_event_result_row_includes_telemetry_fields():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}
    baseline_scores = {
        "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
        "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
    }
    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 1.0},
        brier=0.0,
        round_jsd=[0.1, 0.2, 0.3, 0.4, 0.5],
        convergence_monotonic=True,
        baseline_scores=baseline_scores,
    )
    assert row["round_jsd"] == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert row["convergence_monotonic"] is True
    assert set(row["baseline_scores"]) == {"uniform_random", "market_prior"}

def test_build_event_result_row_rejects_invalid_round_jsd_length():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}
    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 1.0},
        brier=0.0,
        round_jsd=[0.1, 0.2],
        convergence_monotonic=True,
    )
    assert row["round_jsd"] is None
    assert row["convergence_monotonic"] is None
    assert "Telemetry error:" in row["error"]
    assert "round_jsd" in row["error"]


def test_build_event_result_row_includes_rubric_artifacts():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 1.0},
        brier=0.0,
        mcq_dimensions={"accuracy": 4, "calibration": 3},
        validated_scales={"likelihood": {"value": 4, "max": 5}},
    )

    assert row["mcq_dimensions"] == {"accuracy": 4, "calibration": 3}
    assert row["validated_scales"] == {"likelihood": {"value": 4, "max": 5}}


def test_build_event_result_row_extracts_directional_and_weighted_metrics():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.9, "B": 0.1},
        brier=0.02,
        validated_scales={"schema_version": "v1", "scores": {"weighted_rubric_score": 0.625}},
    )

    assert row["directional_accuracy"] == pytest.approx(1.0)
    assert row["weighted_rubric_score"] == pytest.approx(0.625)


def test_build_event_result_row_defaults_missing_directional_and_weighted_metrics():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities=None,
        brier=None,
        validated_scales=None,
    )

    assert row["directional_accuracy"] == pytest.approx(0.0)
    assert row["weighted_rubric_score"] is None


def test_build_event_result_row_extracts_yes_probability_and_strict_contract_flag():
    event = {"event_id": "E1", "question": "Q", "outcome": "YES", "options": ["YES", "NO"]}

    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"YES": 0.8, "NO": 0.2},
        brier=0.08,
        strict_contract=False,
    )

    assert row["yes_probability"] == pytest.approx(0.8)
    assert row["strict_contract"] is False


def test_build_event_result_row_includes_rps_and_calibration_fields():
    event = {"event_id": "E1", "question": "Q", "outcome": "B", "options": ["A", "B", "C"]}

    row = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.2, "B": 0.5, "C": 0.3},
        brier=0.2,
    )

    assert row["rps"] == pytest.approx(0.13)
    assert row["calibration_bracket"] == "0.5-0.75"
    assert row["calibration_predicted_probability"] == pytest.approx(0.5)
    assert row["calibration_hit"] == 1


def test_build_event_result_row_handles_rps_probability_option_label_mismatch():
    event = {"event_id": "E1", "question": "Q", "outcome": "B", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.2, "B": 0.3, "C": 0.5},
        brier=0.2,
    )

    assert row["rps"] is None
    assert row["calibration_bracket"] is None
    assert row["calibration_predicted_probability"] is None
    assert row["calibration_hit"] is None
    assert "RPS/calibration unavailable" in row["error"]
    assert "not present in ordered_labels" in row["error"]


def test_build_event_result_row_includes_seed_metadata_contract_keys():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.8, "B": 0.2},
        brier=0.2,
    )

    assert "injection_direction" in row
    assert "signed_delta" in row
    assert "belief_update_failure" in row
    assert row["injection_direction"] is None
    assert row["signed_delta"] is None
    assert row["belief_update_failure"] is None


def test_build_event_result_row_persists_evaluator_noisy_dimensions():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.8, "B": 0.2},
        brier=0.2,
        evaluator_noisy_dimensions=["convergence"],
    )

    assert row["evaluator_noisy_dimensions"] == ["convergence"]


def test_build_event_result_row_uses_seed_metadata_when_explicit_args_are_missing(tmp_path):
    seed_dir = tmp_path / "seed-1"
    seed_dir.mkdir()
    (seed_dir / "metadata.json").write_text(
        json.dumps(
            {
                "event_id": "E1",
                "injection_direction": "anti_YES",
                "signed_delta": -0.25,
                "belief_update_failure": True,
            }
        ),
        encoding="utf-8",
    )
    seed_file = seed_dir / "seed.txt"
    seed_file.write_text("seed payload", encoding="utf-8")
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.8, "B": 0.2},
        brier=0.2,
        seed_file=str(seed_file),
    )

    assert row["error"] is None
    assert row["injection_direction"] == "anti_YES"
    assert row["signed_delta"] == pytest.approx(-0.25)
    assert row["belief_update_failure"] is True


def test_build_event_result_row_explicit_args_take_precedence_over_seed_metadata(tmp_path):
    seed_dir = tmp_path / "seed-1"
    seed_dir.mkdir()
    (seed_dir / "metadata.json").write_text(
        json.dumps(
            {
                "event_id": "E1",
                "injection_direction": "anti_YES",
                "signed_delta": -0.25,
                "belief_update_failure": True,
            }
        ),
        encoding="utf-8",
    )
    seed_file = seed_dir / "seed.txt"
    seed_file.write_text("seed payload", encoding="utf-8")
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.8, "B": 0.2},
        brier=0.2,
        seed_file=str(seed_file),
        injection_direction="pro_YES",
        signed_delta=0.5,
        belief_update_failure=False,
    )

    assert row["error"] is None
    assert row["injection_direction"] == "pro_YES"
    assert row["signed_delta"] == pytest.approx(0.5)
    assert row["belief_update_failure"] is False


def test_build_event_result_row_ignores_missing_seed_metadata_file(tmp_path):
    seed_dir = tmp_path / "seed-1"
    seed_dir.mkdir()
    seed_file = seed_dir / "seed.txt"
    seed_file.write_text("seed payload", encoding="utf-8")
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.8, "B": 0.2},
        brier=0.2,
        seed_file=str(seed_file),
    )

    assert row["error"] is None
    assert row["full_simulation_completed"] is True
    assert row["injection_direction"] is None
    assert row["signed_delta"] is None
    assert row["belief_update_failure"] is None


@pytest.mark.parametrize(
    ("metadata_field", "metadata_value", "expected_message"),
    [
        ("signed_delta", "bad-value", "metadata.json signed_delta must be a number"),
        (
            "belief_update_failure",
            "not-a-bool",
            "metadata.json belief_update_failure must be a boolean",
        ),
    ],
)
def test_build_event_result_row_rejects_invalid_seed_metadata_types(
    tmp_path, metadata_field, metadata_value, expected_message
):
    seed_dir = tmp_path / "seed-1"
    seed_dir.mkdir()
    (seed_dir / "metadata.json").write_text(
        json.dumps(
            {
                "event_id": "E1",
                "injection_direction": "pro_YES",
                metadata_field: metadata_value,
            }
        ),
        encoding="utf-8",
    )
    seed_file = seed_dir / "seed.txt"
    seed_file.write_text("seed payload", encoding="utf-8")
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}

    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.8, "B": 0.2},
        brier=0.2,
        seed_file=str(seed_file),
    )

    assert row["error"] is not None
    assert expected_message in row["error"]
    assert row["full_simulation_completed"] is False
    assert row["signed_delta"] is None
    assert row["belief_update_failure"] is None


def test_build_simulation_config_carries_benchmark_llm_model(monkeypatch):
    monkeypatch.setattr(protocol_script, "enforce_protocol_constraints", lambda config: None)

    class DummyInjectionLoader:
        def get_payload(self, event_id, condition):
            return {"event_id": event_id, "condition": condition}

    config = protocol_script.build_simulation_config(
        {"event_id": "E1", "question": "Q", "outcome": "A"},
        "A",
        [{"agent_id": 1, "entity_name": "A", "entity_uuid": "u", "entity_type": "person", "activity_level": 0.5, "name": "A", "username": "a", "bio": "", "persona": "", "source_seed_file": "seed.txt"}],
        DummyInjectionLoader(),
        llm_model="openrouter/benchmark-model",
    )

    assert config["llm_model"] == "openrouter/benchmark-model"


def test_build_simulation_config_seeds_initial_post_from_question(monkeypatch):
    monkeypatch.setattr(protocol_script, "enforce_protocol_constraints", lambda config: None)

    class DummyInjectionLoader:
        def get_payload(self, event_id, condition):
            return {"event_id": event_id, "condition": condition}

    config = protocol_script.build_simulation_config(
        {"event_id": "E1", "question": "What happened?", "outcome": "A"},
        "A",
        [{"agent_id": 1, "entity_name": "A", "entity_uuid": "u", "entity_type": "person", "activity_level": 0.5, "name": "A", "username": "a", "bio": "", "persona": "", "source_seed_file": "seed.txt"}],
        DummyInjectionLoader(),
    )

    assert config["event_config"]["initial_posts"] == [
        {"poster_agent_id": 0, "content": "What happened?"}
    ]


def test_write_simulation_config_creates_parent_directory(tmp_path):
    run_dir = tmp_path / "nested" / "unit-dir"
    config_path = protocol_script.write_simulation_config(run_dir, {"event_id": "E1"})
    assert config_path.exists()
    assert config_path.parent == run_dir


def test_write_profiles_creates_parent_directory(tmp_path):
    profile_dir = tmp_path / "nested" / "profiles-dir"
    twitter_path, reddit_path = protocol_script.write_profiles(
        profile_dir,
        [
            {
                "user_id": 1,
                "name": "Agent One",
                "username": "agent1",
                "realname": "Agent One",
                "bio": "bio",
                "persona": "persona",
            }
        ],
    )
    assert twitter_path.exists()
    assert reddit_path.exists()
    assert twitter_path.parent == profile_dir
    assert reddit_path.parent == profile_dir


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


def test_write_summary_includes_calibration_plot_artifact(tmp_path):
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "calibration_predicted_probability": 0.2,
            "calibration_hit": 1,
        },
        {
            "condition": "B",
            "brier": 0.3,
            "simulation_status": "completed",
            "calibration_predicted_probability": 0.7,
            "calibration_hit": 0,
        },
    ]

    summary = protocol_script.write_summary(tmp_path, rows)

    assert summary["calibration"]["plot_path"] == str(tmp_path / "calibration_curve.png")
    assert (tmp_path / "calibration_curve.png").exists()


def test_summarize_event_results_includes_convergence_block():
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "round_jsd": [0.1, 0.2, 0.3, 0.4, 0.5],
            "convergence_monotonic": True,
        },
        {
            "condition": "B",
            "brier": 0.3,
            "simulation_status": "completed",
            "round_jsd": [0.2, 0.2, 0.2, 0.2, 0.2],
            "convergence_monotonic": False,
        },
        {
            "condition": "C",
            "brier": None,
            "simulation_status": "evaluation_failed",
            "round_jsd": [0.9, 0.9, 0.9, 0.9, 0.9],
            "convergence_monotonic": True,
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["convergence"]["mean_round_jsd"] == pytest.approx(0.25)
    assert summary["convergence"]["monotonic_count"] == 1


def test_summarize_event_results_includes_statistical_blocks():
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "rps": 0.1,
            "calibration_bracket": "0-0.25",
            "calibration_predicted_probability": 0.2,
            "calibration_hit": 1,
        },
        {
            "condition": "A",
            "brier": 0.22,
            "simulation_status": "completed",
            "rps": 0.12,
            "calibration_bracket": "0-0.25",
            "calibration_predicted_probability": 0.22,
            "calibration_hit": 0,
        },
        {
            "condition": "B",
            "brier": 0.3,
            "simulation_status": "completed",
            "rps": 0.2,
            "calibration_bracket": "0.25-0.5",
            "calibration_predicted_probability": 0.4,
            "calibration_hit": 1,
        },
        {
            "condition": "B",
            "brier": 0.32,
            "simulation_status": "completed",
            "rps": 0.18,
            "calibration_bracket": "0.5-0.75",
            "calibration_predicted_probability": 0.6,
            "calibration_hit": 0,
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["rps"]["overall"] == pytest.approx(0.15)
    assert summary["rps"]["by_condition"]["A"] == pytest.approx(0.11)
    assert summary["rps"]["by_condition"]["B"] == pytest.approx(0.19)
    assert summary["effect_size"]["cohens_d"] is not None
    assert summary["power_analysis"]["actual_n"] == 2
    assert summary["calibration"]["overall"]["0-0.25"]["count"] == 2
    assert summary["calibration"]["overall"]["0-0.25"]["hits"] == 1


def test_summarize_event_results_handles_undefined_cohens_d():
    rows = [
        {"condition": "A", "brier": 0.2, "simulation_status": "completed"},
        {"condition": "A", "brier": 0.2, "simulation_status": "completed"},
        {"condition": "B", "brier": 0.4, "simulation_status": "completed"},
        {"condition": "B", "brier": 0.4, "simulation_status": "completed"},
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["effect_size"]["cohens_d"] is None
    assert summary["effect_size"]["ci_lower"] is None
    assert summary["effect_size"]["ci_upper"] is None
    assert summary["effect_size"]["error"] is not None
    assert "Cohen's d undefined" in summary["effect_size"]["error"]


def test_summarize_event_results_includes_composite_score_block():
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.1,
                    "polarization_score": 0.2,
                    "herd_effect_score": 0.3,
                    "deliberation_quality_score": 0.4,
                    "susceptibility_score": 0.5,
                    "convergence_score": 0.6,
                    "information_diversity_score": 0.7,
                    "weighted_rubric_score": 0.8,
                }
            },
        },
        {
            "condition": "B",
            "brier": 0.3,
            "simulation_status": "completed",
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.3,
                    "polarization_score": 0.4,
                    "herd_effect_score": 0.5,
                    "deliberation_quality_score": 0.6,
                    "susceptibility_score": 0.7,
                    "convergence_score": 0.8,
                    "information_diversity_score": 0.9,
                    "weighted_rubric_score": 0.9,
                }
            },
        },
    ]

    summary = protocol_script.summarize_event_results(rows)
    composite = summary["composite_score"]

    assert set(composite) == {
        "composite_score",
        "renormalized_weights",
        "excluded_dimensions",
        "included_dimensions",
    }
    assert composite["excluded_dimensions"] == []
    assert composite["included_dimensions"] == [
        "convergence",
        "dqi",
        "herd_effect",
        "info_diversity",
        "polarization",
        "prediction_accuracy",
        "susceptibility",
    ]
    assert set(composite["renormalized_weights"]) == set(composite["included_dimensions"])
    assert composite["composite_score"] == pytest.approx(0.455)


def test_summarize_event_results_uses_kappa_evaluator_reliability_for_composite_score():
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "evaluator_dimension_labels": {
                "convergence": {"run1": "high", "run2": "low"},
                "herd_effect": {"run1": "low", "run2": "high"},
            },
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.9,
                    "polarization_score": 0.5,
                    "herd_effect_score": 0.3,
                    "deliberation_quality_score": 0.4,
                    "susceptibility_score": 0.2,
                    "convergence_score": 0.1,
                    "information_diversity_score": 0.6,
                    "weighted_rubric_score": 0.8,
                }
            },
        },
        {
            "condition": "B",
            "brier": 0.3,
            "simulation_status": "completed",
            "evaluator_dimension_labels": {
                "convergence": {"run1": "low", "run2": "high"},
                "herd_effect": {"run1": "high", "run2": "low"},
            },
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.9,
                    "polarization_score": 0.5,
                    "herd_effect_score": 0.3,
                    "deliberation_quality_score": 0.4,
                    "susceptibility_score": 0.2,
                    "convergence_score": 0.1,
                    "information_diversity_score": 0.6,
                    "weighted_rubric_score": 0.8,
                }
            },
        },
    ]

    summary = protocol_script.summarize_event_results(rows, kappa_cutoff=0.8)
    composite = summary["composite_score"]

    assert summary["evaluator_reliability"] == {
        "kappa_by_dimension": {
            "convergence": pytest.approx(-1.0),
            "herd_effect": pytest.approx(-1.0),
        },
        "evaluator_noisy": ["convergence", "herd_effect"],
        "dropped_dimensions_count": 2,
        "evaluator_unstable": True,
        "kappa_cutoff": 0.8,
    }
    assert composite["excluded_dimensions"] == ["convergence", "herd_effect"]
    assert set(composite["included_dimensions"]) == {
        "prediction_accuracy",
        "susceptibility",
        "dqi",
        "polarization",
        "info_diversity",
    }
    assert composite["composite_score"] == pytest.approx(0.607692, abs=1e-6)


def test_summarize_event_results_ignores_failed_rows_when_aggregating_evaluator_reliability():
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "evaluator_dimension_labels": {
                "convergence": {"run1": "high", "run2": "high"},
            },
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.9,
                    "polarization_score": 0.5,
                    "herd_effect_score": 0.3,
                    "deliberation_quality_score": 0.4,
                    "susceptibility_score": 0.2,
                    "convergence_score": 0.1,
                    "information_diversity_score": 0.6,
                    "weighted_rubric_score": 0.8,
                }
            },
        },
        {
            "condition": "A",
            "brier": 0.21,
            "simulation_status": "completed",
            "evaluator_dimension_labels": {
                "convergence": {"run1": "low", "run2": "low"},
            },
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.91,
                    "polarization_score": 0.51,
                    "herd_effect_score": 0.31,
                    "deliberation_quality_score": 0.41,
                    "susceptibility_score": 0.21,
                    "convergence_score": 0.11,
                    "information_diversity_score": 0.61,
                    "weighted_rubric_score": 0.81,
                }
            },
        },
        {
            "condition": "B",
            "brier": None,
            "simulation_status": "evaluation_failed",
            "evaluator_dimension_labels": {
                "convergence": {"run1": "very_low", "run2": "very_high"},
            },
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.3,
                    "polarization_score": 0.4,
                    "herd_effect_score": 0.5,
                    "deliberation_quality_score": 0.6,
                    "susceptibility_score": 0.7,
                    "convergence_score": 0.8,
                    "information_diversity_score": 0.9,
                    "weighted_rubric_score": 0.9,
                }
            },
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["evaluator_reliability"] == {
        "kappa_by_dimension": {"convergence": pytest.approx(1.0)},
        "evaluator_noisy": [],
        "dropped_dimensions_count": 0,
        "evaluator_unstable": False,
        "kappa_cutoff": 0.8,
    }
    assert summary["composite_score"]["excluded_dimensions"] == []


def test_summarize_event_results_uses_legacy_evaluator_noisy_dimensions_when_kappa_missing():
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "evaluator_noisy_dimensions": ["convergence", 123],
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.9,
                    "polarization_score": 0.5,
                    "herd_effect_score": 0.3,
                    "deliberation_quality_score": 0.4,
                    "susceptibility_score": 0.2,
                    "convergence_score": 0.1,
                    "information_diversity_score": 0.6,
                    "weighted_rubric_score": 0.8,
                }
            },
        }
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["evaluator_reliability"] == {
        "kappa_by_dimension": {},
        "evaluator_noisy": ["convergence"],
        "dropped_dimensions_count": 1,
        "evaluator_unstable": False,
        "kappa_cutoff": 0.8,
    }
    assert summary["composite_score"]["excluded_dimensions"] == ["convergence"]


def test_summarize_event_results_ignores_invalid_legacy_noisy_dimensions_for_unstable_counts():
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "evaluator_noisy_dimensions": ["legacy_noise", "", None, 123],
            "validated_scales": {
                "scores": {
                    "prediction_accuracy_score": 0.9,
                    "polarization_score": 0.5,
                    "herd_effect_score": 0.3,
                    "deliberation_quality_score": 0.4,
                    "susceptibility_score": 0.2,
                    "convergence_score": 0.1,
                    "information_diversity_score": 0.6,
                    "weighted_rubric_score": 0.8,
                }
            },
        }
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["evaluator_reliability"] == {
        "kappa_by_dimension": {},
        "evaluator_noisy": [],
        "dropped_dimensions_count": 0,
        "evaluator_unstable": False,
        "kappa_cutoff": 0.8,
    }
    assert summary["composite_score"]["excluded_dimensions"] == []


def test_evaluate_row_marks_evaluator_reliability_absent_when_second_run_fails(monkeypatch):
    run1_labels = {
        "prediction_accuracy": "high",
        "polarization": "low",
        "herd_effect": "high",
        "deliberation_quality": "high",
        "susceptibility": "low",
        "convergence": "high",
        "information_diversity": "very_high",
    }

    def _build_mcq_dimensions(labels):
        mcq_dimensions = {}
        for dimension, bucket in labels.items():
            mcq_dimensions[dimension] = {"very_low": 0.0, "low": 0.0, "high": 0.0, "very_high": 0.0}
            mcq_dimensions[dimension][bucket] = 1.0
        return mcq_dimensions

    class FakeRouter:
        def model_for(self, role):
            return "openrouter/benchmark-model"

    class FakeEvaluator:
        calls = 0

        def __init__(self, router):
            self.router = router

        def evaluate(self, question, condition, evidence_text):
            del question, condition, evidence_text
            FakeEvaluator.calls += 1
            if FakeEvaluator.calls == 1:
                return {
                    "probabilities": {"A": 0.7, "B": 0.3},
                    "mcq_dimensions": _build_mcq_dimensions(run1_labels),
                    "validated_scales": {
                        "schema_version": "v1",
                        "scores": {
                            "prediction_accuracy_score": 0.9,
                            "polarization_score": 0.5,
                            "herd_effect_score": 0.3,
                            "deliberation_quality_score": 0.4,
                            "susceptibility_score": 0.2,
                            "convergence_score": 0.1,
                            "information_diversity_score": 0.6,
                            "weighted_rubric_score": 0.8,
                        },
                    },
                    "evaluator_noisy_dimensions": ("convergence",),
                }
            raise RuntimeError("run2 evaluator failed")

    monkeypatch.setattr(protocol_script, "ProbabilityEvaluator", FakeEvaluator)

    row = protocol_script._evaluate_row(
        {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        "A",
        "evidence text",
        FakeRouter(),
    )

    assert row["probabilities"] == {"A": pytest.approx(0.7), "B": pytest.approx(0.3)}
    assert row["validated_scales"]["scores"]["prediction_accuracy_score"] == pytest.approx(0.9)
    assert row["evaluator_dimension_labels"] == {}
    assert row["evaluator_reliability_status"] == "absent"


def test_evaluate_row_marks_evaluator_reliability_partial_when_second_run_is_incomplete(monkeypatch):
    run1_labels = {
        "prediction_accuracy": "high",
        "polarization": "low",
        "herd_effect": "high",
    }
    run2_labels = {
        "prediction_accuracy": "high",
    }

    def _build_mcq_dimensions(labels):
        mcq_dimensions = {}
        for dimension, bucket in labels.items():
            mcq_dimensions[dimension] = {"very_low": 0.0, "low": 0.0, "high": 0.0, "very_high": 0.0}
            mcq_dimensions[dimension][bucket] = 1.0
        return mcq_dimensions

    class FakeRouter:
        def model_for(self, role):
            return "openrouter/benchmark-model"

    class FakeEvaluator:
        calls = 0

        def __init__(self, router):
            self.router = router

        def evaluate(self, question, condition, evidence_text):
            del question, condition, evidence_text
            FakeEvaluator.calls += 1
            if FakeEvaluator.calls == 1:
                return {
                    "probabilities": {"A": 0.7, "B": 0.3},
                    "mcq_dimensions": _build_mcq_dimensions(run1_labels),
                    "validated_scales": {
                        "schema_version": "v1",
                        "scores": {
                            "prediction_accuracy_score": 0.9,
                            "polarization_score": 0.5,
                            "herd_effect_score": 0.3,
                            "deliberation_quality_score": 0.4,
                            "susceptibility_score": 0.2,
                            "convergence_score": 0.1,
                            "information_diversity_score": 0.6,
                            "weighted_rubric_score": 0.8,
                        },
                    },
                }
            return {
                "probabilities": {"A": 0.1, "B": 0.9},
                "mcq_dimensions": _build_mcq_dimensions(run2_labels),
                "validated_scales": {
                    "schema_version": "v1",
                    "scores": {
                        "prediction_accuracy_score": 0.1,
                        "polarization_score": 0.1,
                        "herd_effect_score": 0.1,
                        "deliberation_quality_score": 0.1,
                        "susceptibility_score": 0.1,
                        "convergence_score": 0.9,
                        "information_diversity_score": 0.1,
                        "weighted_rubric_score": 0.1,
                    },
                },
            }

    monkeypatch.setattr(protocol_script, "ProbabilityEvaluator", FakeEvaluator)

    row = protocol_script._evaluate_row(
        {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        "A",
        "evidence text",
        FakeRouter(),
    )

    assert row["probabilities"] == {"A": pytest.approx(0.7), "B": pytest.approx(0.3)}
    assert row["evaluator_dimension_labels"] == {"prediction_accuracy": {"run1": "high", "run2": "high"}}
    assert row["evaluator_reliability_status"] == "partial"


def test_evaluate_row_runs_evaluator_twice_and_records_dimension_labels(monkeypatch):
    run1_labels = {
        "prediction_accuracy": "high",
        "polarization": "low",
        "herd_effect": "high",
        "deliberation_quality": "high",
        "susceptibility": "low",
        "convergence": "high",
        "information_diversity": "very_high",
    }
    run2_labels = {
        "prediction_accuracy": "high",
        "polarization": "low",
        "herd_effect": "low",
        "deliberation_quality": "high",
        "susceptibility": "low",
        "convergence": "low",
        "information_diversity": "very_high",
    }

    def _build_mcq_dimensions(labels):
        mcq_dimensions = {}
        for dimension, bucket in labels.items():
            mcq_dimensions[dimension] = {"very_low": 0.0, "low": 0.0, "high": 0.0, "very_high": 0.0}
            mcq_dimensions[dimension][bucket] = 1.0
        return mcq_dimensions

    class FakeRouter:
        def model_for(self, role):
            return "openrouter/benchmark-model"

    class FakeEvaluator:
        calls = []

        def __init__(self, router):
            self.router = router

        def evaluate(self, question, condition, evidence_text):
            FakeEvaluator.calls.append((question, condition, evidence_text))
            if len(FakeEvaluator.calls) == 1:
                return {
                    "probabilities": {"A": 0.7, "B": 0.3},
                    "mcq_dimensions": _build_mcq_dimensions(run1_labels),
                    "validated_scales": {
                        "schema_version": "v1",
                        "scores": {
                            "prediction_accuracy_score": 0.9,
                            "polarization_score": 0.5,
                            "herd_effect_score": 0.3,
                            "deliberation_quality_score": 0.4,
                            "susceptibility_score": 0.2,
                            "convergence_score": 0.1,
                            "information_diversity_score": 0.6,
                            "weighted_rubric_score": 0.8,
                        },
                    },
                    "evaluator_noisy_dimensions": ("convergence", 123),
                }
            return {
                "probabilities": {"A": 0.1, "B": 0.9},
                "mcq_dimensions": _build_mcq_dimensions(run2_labels),
                "validated_scales": {
                    "schema_version": "v1",
                    "scores": {
                        "prediction_accuracy_score": 0.1,
                        "polarization_score": 0.1,
                        "herd_effect_score": 0.1,
                        "deliberation_quality_score": 0.1,
                        "susceptibility_score": 0.1,
                        "convergence_score": 0.9,
                        "information_diversity_score": 0.1,
                        "weighted_rubric_score": 0.1,
                    },
                },
                "evaluator_noisy_dimensions": ("herd_effect",),
            }

    monkeypatch.setattr(protocol_script, "ProbabilityEvaluator", FakeEvaluator)

    row = protocol_script._evaluate_row(
        {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        "A",
        "evidence text",
        FakeRouter(),
    )

    assert len(FakeEvaluator.calls) == 2
    assert row["probabilities"] == {"A": pytest.approx(0.7), "B": pytest.approx(0.3)}
    assert row["evaluator_noisy_dimensions"] == ["convergence", "123"]
    assert row["validated_scales"]["scores"]["prediction_accuracy_score"] == pytest.approx(0.9)
    assert row["evaluator_reliability_status"] == "complete"
    assert row["evaluator_dimension_labels"]["convergence"] == {"run1": "high", "run2": "low"}
    assert row["evaluator_dimension_labels"]["herd_effect"] == {"run1": "high", "run2": "low"}

    row["condition"] = "A"
    row["simulation_status"] = "completed"
    failed_row = dict(row)
    failed_row["condition"] = "B"
    failed_row["simulation_status"] = "evaluation_failed"
    failed_row["evaluator_noisy_dimensions"] = ["herd_effect"]

    summary = protocol_script.summarize_event_results([row, failed_row], kappa_cutoff=0.8)
    composite = summary["composite_score"]

    assert summary["evaluator_reliability"] == {
        "kappa_by_dimension": {
            "convergence": pytest.approx(0.0),
            "deliberation_quality": pytest.approx(1.0),
            "herd_effect": pytest.approx(0.0),
            "information_diversity": pytest.approx(1.0),
            "polarization": pytest.approx(1.0),
            "prediction_accuracy": pytest.approx(1.0),
            "susceptibility": pytest.approx(1.0),
        },
        "evaluator_noisy": ["convergence", "herd_effect"],
        "dropped_dimensions_count": 2,
        "evaluator_unstable": True,
        "kappa_cutoff": 0.8,
    }
    assert composite["excluded_dimensions"] == ["convergence", "herd_effect"]
    assert "convergence" not in composite["included_dimensions"]


def test_summarize_event_results_propagates_unexpected_composite_value_errors(monkeypatch):
    monkeypatch.setattr(
        protocol_script,
        "_summarize_composite_score",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad composite config")),
    )

    with pytest.raises(ValueError, match="bad composite config"):
        protocol_script.summarize_event_results(
            [
                {
                    "condition": "A",
                    "brier": 0.2,
                    "simulation_status": "completed",
                    "validated_scales": {
                        "scores": {
                            "prediction_accuracy_score": 0.1,
                            "polarization_score": 0.2,
                            "herd_effect_score": 0.3,
                            "deliberation_quality_score": 0.4,
                            "susceptibility_score": 0.5,
                            "convergence_score": 0.6,
                            "information_diversity_score": 0.7,
                            "weighted_rubric_score": 0.8,
                        }
                    },
                }
            ]
        )


def _patch_minimal_main_inputs(monkeypatch, tmp_path, *, simulation_result, evaluate_side_effect=None):
    events = [
        {
            "event_id": "E1",
            "question": "Q1",
            "outcome": "A",
            "options": ["A", "B"],
            "polymarket_opening_prior": {"A": 0.5, "B": 0.5},
        }
    ]
    seed_file = tmp_path / "seed.json"
    seed_file.write_text("{}", encoding="utf-8")

    class DummyInjectionLoader:
        def __init__(self, path):
            self.path = path

        def has_event(self, event_id):
            return True

        def get_payload(self, event_id, condition):
            return {"event_id": event_id, "condition": condition}

    class DummyRouter:
        api_key = "router-key"
        base_url = "https://openrouter.ai/api/v1"

        def model_for(self, role):
            mapping = {
                "benchmark": "openrouter/benchmark-model",
                "evaluator": "openrouter/evaluator-model",
            }
            return mapping[role]

    monkeypatch.setattr(protocol_script, "_utc_run_id", lambda: "fixed-run")
    monkeypatch.setattr(protocol_script, "load_events_from_raw", lambda *args, **kwargs: events)
    monkeypatch.setattr(protocol_script, "load_seed_files", lambda *args, **kwargs: [seed_file])
    monkeypatch.setattr(protocol_script, "build_profiles", lambda *args, **kwargs: [{"agent_id": 1, "name": "A"}])
    monkeypatch.setattr(protocol_script, "build_condition_matrix", lambda *args, **kwargs: [{"event_id": "E1", "condition": "A", "repeat": 1}])
    monkeypatch.setattr(protocol_script, "Step30InjectionLoader", DummyInjectionLoader)
    monkeypatch.setattr(protocol_script, "build_simulation_config", lambda *args, **kwargs: {"event_id": "E1"})
    monkeypatch.setattr(protocol_script, "write_simulation_config", lambda run_dir, config: run_dir / "simulation_config.json")
    monkeypatch.setattr(protocol_script, "write_profiles", lambda *args, **kwargs: (tmp_path / "twitter_profiles.csv", tmp_path / "reddit_profiles.json"))
    monkeypatch.setattr(protocol_script, "build_evidence_text", lambda *args, **kwargs: "evidence")
    monkeypatch.setattr(protocol_script, "_run_simulation_subprocess", lambda *args, **kwargs: simulation_result)
    monkeypatch.setattr(protocol_script.BenchmarkRoleRouter, "from_config", classmethod(lambda cls, config=None: DummyRouter()))
    if evaluate_side_effect is not None:
        monkeypatch.setattr(protocol_script, "_evaluate_row", evaluate_side_effect)
    else:
        monkeypatch.setattr(protocol_script, "_evaluate_row", lambda *args, **kwargs: ({"A": 1.0}, 0.0))


def test_main_delegates_run_loop_to_orchestrator_with_leakage_preflight(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    config_builder_calls: list[tuple[dict[str, object], str, list[dict[str, object]], object, str]] = []
    executor_ctor_calls: dict[str, object] = {}
    seed_file = tmp_path / "seed.md"
    seed_file.write_text("Neutral background text only.", encoding="utf-8")

    class DummyInjectionLoader:
        def has_event(self, event_id):
            return True

        def get_payload(self, event_id, condition):
            return {"event_id": event_id, "condition": condition}

    class FakeProtocolExecutor:
        def __init__(self, **kwargs):
            executor_ctor_calls.update(kwargs)

    class FakeOrchestrator:
        def __init__(self, executor):
            self.executor = executor
            captured["executor"] = executor

        def run(self, **kwargs):
            captured.update(kwargs)
            run_dir = Path(kwargs["output_root"]) / kwargs["run_id"]
            captured["run_dir_exists_before_run"] = run_dir.exists()
            captured["manifest_exists_before_run"] = (run_dir / "run_manifest.json").exists()
            built_config = kwargs["config_builder"]({"event_id": "E1", "question": "Q", "outcome": "A"}, "A")
            captured["built_config"] = built_config
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "event_results.json").write_text("[]", encoding="utf-8")
            (run_dir / "summary.json").write_text("{}", encoding="utf-8")
            return run_dir

    monkeypatch.setattr(protocol_script, "BenchmarkRunOrchestrator", FakeOrchestrator, raising=False)
    monkeypatch.setattr(protocol_script, "_utc_run_id", lambda: "fixed-run")
    monkeypatch.setattr(
        protocol_script,
        "load_events_from_raw",
        lambda *args, **kwargs: [
            {
                "event_id": "E1",
                "question": "Q",
                "outcome": "A",
                "options": ["A", "B"],
                "polymarket_opening_prior": {"A": 0.5, "B": 0.5},
                "seed_date": "2024-01-01",
                "resolution_date": "2024-01-10",
                "seed_file": "seed.md",
            }
        ],
    )
    monkeypatch.setattr(protocol_script, "load_seed_files", lambda *args, **kwargs: [seed_file])
    monkeypatch.setattr(protocol_script, "build_profiles", lambda *args, **kwargs: [{"agent_id": 1}])
    monkeypatch.setattr(
        protocol_script.BenchmarkRoleRouter,
        "from_config",
        classmethod(
            lambda cls, config=None: type(
                "R",
                (),
                {"model_for": lambda self, role: "m", "api_key": "k", "base_url": "u"},
            )()
        ),
    )
    monkeypatch.setattr(protocol_script, "Step30InjectionLoader", lambda *_args, **_kwargs: DummyInjectionLoader())
    monkeypatch.setattr(protocol_script, "ProtocolConditionExecutor", FakeProtocolExecutor)
    monkeypatch.setattr(
        protocol_script,
        "build_simulation_config",
        lambda event, condition, profiles, injection_loader, llm_model: (
            config_builder_calls.append((event, condition, profiles, injection_loader, llm_model))
            or {"event_id": event["event_id"], "condition": condition}
        ),
    )
    monkeypatch.setattr(protocol_script, "write_summary", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        protocol_script.sys,
        "argv",
        [
            "run_ecnbench_protocol.py",
            "--seeds-dir",
            str(tmp_path),
            "--events-raw",
            str(tmp_path / "events.json"),
            "--output-dir",
            str(tmp_path / "runs"),
        ],
    )

    protocol_script.main()

    assert captured["run_id"] == "fixed-run"
    assert captured["output_root"] == tmp_path / "runs"
    expected_event = {
        "event_id": "E1",
        "question": "Q",
        "outcome": "A",
        "options": ["A", "B"],
        "polymarket_opening_prior": {"A": 0.5, "B": 0.5},
        "seed_date": "2024-01-01",
        "resolution_date": "2024-01-10",
        "seed_file": "seed.md",
    }
    assert captured["events"] == [expected_event]
    assert captured["repeats"] == 1
    assert callable(captured["build_condition_matrix"])
    assert captured["build_condition_matrix"]([], 99) == protocol_script.build_condition_matrix(captured["events"], captured["repeats"])
    assert captured["event_lookup"] == {"E1": expected_event}
    assert captured["write_summary"] is protocol_script.write_summary
    assert captured["evaluator"] is protocol_script._evaluate_row
    assert captured["manifest"]["run_id"] == "fixed-run"
    assert captured["manifest"]["events_loaded"] == 1
    assert captured["manifest"]["trace_out"].endswith("traces\\execution.jsonl")
    assert captured["manifest"]["phase1_config_version"] == "phase1_v1"
    assert captured["manifest"]["telemetry_checkpoints"] == [12, 24, 36, 48, 60]
    assert captured["manifest"]["jsd_monotonic_tolerance_epsilon"] == pytest.approx(0.002)
    assert captured["manifest"]["baseline_agents"] == ["uniform_random", "market_prior"]
    assert captured["manifest"]["preflight_market_prior_check"] == "pass"
    assert captured["manifest"]["leakage_check"] == "pass"
    assert captured["run_dir_exists_before_run"] is False
    assert captured["manifest_exists_before_run"] is False
    assert captured["built_config"] == {"event_id": "E1", "condition": "A"}
    assert isinstance(captured["executor"], FakeProtocolExecutor)
    assert executor_ctor_calls["python_exe"] == protocol_script.sys.executable
    assert executor_ctor_calls["seed_files"] == [tmp_path / "seed.md"]
    assert len(config_builder_calls) == 1
    event, condition, profiles, injection_loader, llm_model = config_builder_calls[0]
    assert event == {"event_id": "E1", "question": "Q", "outcome": "A"}
    assert condition == "A"
    assert profiles == [{"agent_id": 1}]
    assert isinstance(injection_loader, DummyInjectionLoader)
    assert llm_model == "m"


def test_main_fails_fast_when_phase1_baseline_agents_do_not_match_implementation(monkeypatch, tmp_path):
    def fail_build_condition_matrix(*_args, **_kwargs):
        pytest.fail("build_condition_matrix should not run before baseline agent contract check")

    _patch_minimal_main_inputs(
        monkeypatch,
        tmp_path,
        simulation_result=subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        protocol_script,
        "load_phase1_config",
        lambda *_args, **_kwargs: {
            "version": "phase1_v1",
            "telemetry_checkpoints": [12, 24, 36, 48, 60],
            "jsd_monotonic_tolerance_epsilon": 0.002,
            "prior_sum_tolerance": 1e-6,
            "min_parsed_probability_ratio": 0.25,
            "baseline_agents": ["market_prior", "uniform_random"],
        },
    )
    monkeypatch.setattr(protocol_script, "build_condition_matrix", fail_build_condition_matrix)
    monkeypatch.setattr(
        protocol_script.sys,
        "argv",
        [
            "run_ecnbench_protocol.py",
            "--seeds-dir",
            str(tmp_path),
            "--events-raw",
            str(tmp_path / "events.json"),
            "--output-dir",
            str(tmp_path / "runs"),
        ],
    )

    with pytest.raises(ValueError, match="phase1 baseline_agents must match implemented baseline scoring agents"):
        protocol_script.main()


def test_main_manifest_includes_continuation_metadata(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr="")
    _patch_minimal_main_inputs(monkeypatch, tmp_path, simulation_result=simulation_result)
    monkeypatch.setattr(protocol_script.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(protocol_script.Config, "BENCHMARK_TEMPERATURE", 0.125, raising=False)
    monkeypatch.setattr(protocol_script.Config, "BENCHMARK_SEED", 9876, raising=False)
    custom_events = [
        {
            "event_id": "E1",
            "question": "Q1",
            "outcome": "A",
            "options": ["A", "B"],
            "polymarket_opening_prior": {"A": 0.6, "B": 0.4},
        },
        {
            "event_id": "E2",
            "question": "Q2",
            "outcome": "B",
            "options": ["A", "B"],
            "polymarket_opening_prior": {"A": 0.2, "B": 0.8},
        },
    ]
    custom_matrix = [
        {"event_id": "E1", "condition": "A", "repeat": 1},
        {"event_id": "E1", "condition": "B", "repeat": 1},
        {"event_id": "E2", "condition": "A", "repeat": 1},
        {"event_id": "E2", "condition": "C", "repeat": 1},
        {"event_id": "E2", "condition": "C", "repeat": 2},
    ]
    monkeypatch.setattr(protocol_script, "load_events_from_raw", lambda *args, **kwargs: custom_events)
    monkeypatch.setattr(protocol_script, "build_condition_matrix", lambda *args, **kwargs: list(custom_matrix))

    output_dir = tmp_path / "runs"
    argv = [
        "run_ecnbench_protocol.py",
        "--seeds-dir",
        str(tmp_path / "seeds"),
        "--events-raw",
        str(tmp_path / "events.json"),
        "--output-dir",
        str(output_dir),
        "--events",
        "2",
        "--repeats",
        "2",
    ]
    monkeypatch.setattr(protocol_script.sys, "argv", argv)

    protocol_script.main()

    manifest = json.loads((output_dir / "fixed-run" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["workflow_mode"] == "abc-per-event"
    assert manifest["benchmark_model"] == "openrouter/benchmark-model"
    assert manifest["expected_run_units"] == len(custom_matrix)
    assert manifest["weights_schema_version"] == "v1"
    assert manifest["mcq_prompt_version"] == "v1"
    assert manifest["deterministic_mode"] == {
        "benchmark_mode": False,
        "temperature": 0.125,
        "seed": 9876,
    }


def test_main_records_simulation_failure_and_summary(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=1, stdout="", stderr="boom")
    _patch_minimal_main_inputs(monkeypatch, tmp_path, simulation_result=simulation_result)
    # Patch condition matrix to use B instead of A for simulation failure
    def matrix_with_B(*args, **kwargs):
        return [{"event_id": "E1", "condition": "B", "repeat": 1}]
    monkeypatch.setattr(protocol_script, "build_condition_matrix", matrix_with_B)

    output_dir = tmp_path / "runs"
    argv = [
        "run_ecnbench_protocol.py",
        "--seeds-dir",
        str(tmp_path / "seeds"),
        "--events-raw",
        str(tmp_path / "events.json"),
        "--output-dir",
        str(output_dir),
    ]
    monkeypatch.setattr(protocol_script.sys, "argv", argv)

    protocol_script.main()

    run_dir = output_dir / "fixed-run"
    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert rows[0]["simulation_status"] == "simulation_failed"
    assert rows[0]["unit_id"] == "E1_B_r1"
    assert summary["simulation_failure_count"] == 1


def test_main_records_evaluation_failure_and_summary(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr="")

    def raise_evaluation(*args, **kwargs):
        raise RuntimeError("evaluation broke")

    _patch_minimal_main_inputs(
        monkeypatch,
        tmp_path,
        simulation_result=simulation_result,
        evaluate_side_effect=raise_evaluation,
    )

    output_dir = tmp_path / "runs"
    argv = [
        "run_ecnbench_protocol.py",
        "--seeds-dir",
        str(tmp_path / "seeds"),
        "--events-raw",
        str(tmp_path / "events.json"),
        "--output-dir",
        str(output_dir),
    ]
    monkeypatch.setattr(protocol_script.sys, "argv", argv)

    protocol_script.main()

    run_dir = output_dir / "fixed-run"
    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert rows[0]["simulation_status"] == "evaluation_failed"
    assert rows[0]["unit_id"] == "E1_A_r1"
    assert summary["evaluation_failure_count"] == 1


def test_main_writes_artifacts(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr="")
    _patch_minimal_main_inputs(monkeypatch, tmp_path, simulation_result=simulation_result)

    output_dir = tmp_path / "runs"
    argv = [
        "run_ecnbench_protocol.py",
        "--seeds-dir",
        str(tmp_path / "seeds"),
        "--events-raw",
        str(tmp_path / "events.json"),
        "--output-dir",
        str(output_dir),
    ]
    monkeypatch.setattr(protocol_script.sys, "argv", argv)

    protocol_script.main()

    run_dir = output_dir / "fixed-run"
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "traces" / "execution.jsonl").exists()
    assert (run_dir / "event_results.json").exists()
    assert (run_dir / "summary.json").exists()


def test_main_persists_signed_enrichment_in_event_results(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr="")
    _patch_minimal_main_inputs(monkeypatch, tmp_path, simulation_result=simulation_result)
    monkeypatch.setattr(
        protocol_script,
        "load_events_from_raw",
        lambda *args, **kwargs: [
            {
                "event_id": "E1",
                "question": "Q1",
                "outcome": "YES",
                "options": ["YES", "NO"],
                "polymarket_opening_prior": {"YES": 0.5, "NO": 0.5},
            }
        ],
    )
    monkeypatch.setattr(
        protocol_script,
        "build_condition_matrix",
        lambda *args, **kwargs: [
            {"event_id": "E1", "condition": "B", "repeat": 1},
            {"event_id": "E1", "condition": "C", "repeat": 1},
        ],
    )
    monkeypatch.setattr(
        protocol_script,
        "load_seed_metadata",
        lambda *_args, **_kwargs: {"injection_direction": "pro_YES"},
    )
    monkeypatch.setattr(
        protocol_script,
        "_compute_convergence_telemetry",
        lambda *_args, **_kwargs: ([0.2, 0.15, 0.1, 0.05, 0.01], True),
    )

    def evaluate_row(_event, condition, *_args, **_kwargs):
        if condition == "B":
            return {"YES": 0.8, "NO": 0.2}, 0.1
        return {"YES": 0.3, "NO": 0.7}, 0.2

    monkeypatch.setattr(protocol_script, "_evaluate_row", evaluate_row)

    output_dir = tmp_path / "runs"
    argv = [
        "run_ecnbench_protocol.py",
        "--seeds-dir",
        str(tmp_path / "seeds"),
        "--events-raw",
        str(tmp_path / "events.json"),
        "--output-dir",
        str(output_dir),
    ]
    monkeypatch.setattr(protocol_script.sys, "argv", argv)

    protocol_script.main()

    rows = json.loads((output_dir / "fixed-run" / "event_results.json").read_text(encoding="utf-8"))
    rows_by_condition = {row["condition"]: row for row in rows}
    row_b = rows_by_condition["B"]
    row_c = rows_by_condition["C"]
    assert row_b["signed_delta"] == pytest.approx(0.5)
    assert row_c["signed_delta"] == pytest.approx(0.5)
    assert row_b["belief_update_failure"] is False
    assert row_c["belief_update_failure"] is False


def test_main_writes_traces_to_custom_path(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr="")
    _patch_minimal_main_inputs(monkeypatch, tmp_path, simulation_result=simulation_result)

    output_dir = tmp_path / "runs"
    trace_out = tmp_path / "custom-traces" / "execution.jsonl"
    argv = [
        "run_ecnbench_protocol.py",
        "--seeds-dir",
        str(tmp_path / "seeds"),
        "--events-raw",
        str(tmp_path / "events.json"),
        "--output-dir",
        str(output_dir),
        "--trace-out",
        str(trace_out),
    ]
    monkeypatch.setattr(protocol_script.sys, "argv", argv)

    protocol_script.main()

    run_dir = output_dir / "fixed-run"
    assert trace_out.exists()
    assert not (run_dir / "traces" / "execution.jsonl").exists()
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["trace_out"] == str(trace_out)


def test_main_records_timeout_failure_with_log_tail(monkeypatch, tmp_path):
    _patch_minimal_main_inputs(monkeypatch, tmp_path, simulation_result=None)
    # Patch condition matrix to use B instead of A for timeout failure
    def matrix_with_B(*args, **kwargs):
        return [{"event_id": "E1", "condition": "B", "repeat": 1}]
    monkeypatch.setattr(protocol_script, "build_condition_matrix", matrix_with_B)

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["python"], timeout=protocol_script.SIMULATION_SUBPROCESS_TIMEOUT_SECONDS)

    monkeypatch.setattr(protocol_script, "_run_simulation_subprocess", raise_timeout)

    output_dir = tmp_path / "runs"
    run_dir = output_dir / "fixed-run"
    unit_dir = run_dir / "E1_B_r1"
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "simulation.log").write_text("line 1\nline 2\n", encoding="utf-8")

    argv = [
        "run_ecnbench_protocol.py",
        "--seeds-dir",
        str(tmp_path / "seeds"),
        "--events-raw",
        str(tmp_path / "events.json"),
        "--output-dir",
        str(output_dir),
    ]
    monkeypatch.setattr(protocol_script.sys, "argv", argv)

    protocol_script.main()

    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    assert rows[0]["simulation_status"] == "simulation_failed"
    assert "timed out after" in rows[0]["error"]
    assert "simulation.log tail" in rows[0]["error"]
    assert "line 2" in rows[0]["error"]


def test_run_simulation_subprocess_uses_router_benchmark_env(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    monkeypatch.setenv("LLM_API_KEY", "ambient-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://ambient.example/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "ambient-model")
    monkeypatch.setattr(protocol_script.Config, "BENCHMARK_MODE", True, raising=False)
    monkeypatch.setattr(protocol_script.Config, "BENCHMARK_TEMPERATURE", 0.25, raising=False)
    monkeypatch.setattr(protocol_script.Config, "BENCHMARK_SEED", 31415, raising=False)
    monkeypatch.setattr(protocol_script.subprocess, "run", fake_run)

    router = protocol_script.BenchmarkRoleRouter(
        api_key="router-key",
        base_url="https://openrouter.ai/api/v1",
        graph_model="openrouter/graph-model",
        benchmark_model="openrouter/benchmark-model",
        evaluator_model="openrouter/evaluator-model",
    )

    completed = protocol_script._run_simulation_subprocess("python.exe", Path(tmp_path / "config.json"), router)

    assert completed.returncode == 0
    env = captured["kwargs"]["env"]
    assert env["LLM_API_KEY"] == "router-key"
    assert env["LLM_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert env["LLM_MODEL_NAME"] == "openrouter/benchmark-model"
    assert env["BENCHMARK_MODE"] == "true"
    assert env["BENCHMARK_TEMPERATURE"] == "0.25"
    assert env["BENCHMARK_SEED"] == "31415"
    assert captured["kwargs"]["timeout"] == protocol_script.SIMULATION_SUBPROCESS_TIMEOUT_SECONDS
    assert captured["kwargs"]["stdout"] == subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] == subprocess.DEVNULL


def test_summarize_event_results_includes_directional_accuracy_block():
    rows = [
        {
            "condition": "A",
            "brier": 0.3,
            "full_simulation_completed": True,
            "directional_correct": 0,
            "simulation_status": "completed",
        },
        {
            "condition": "B",
            "brier": 0.2,
            "full_simulation_completed": True,
            "directional_correct": 1,
            "simulation_status": "completed",
        },
        {
            "condition": "C",
            "brier": 0.4,
            "full_simulation_completed": True,
            "directional_correct": 1,
            "simulation_status": "completed",
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert "directional_accuracy" in summary
    assert summary["directional_accuracy"]["overall"] == pytest.approx(2 / 3)
    assert summary["directional_accuracy"]["by_condition"]["A"] == pytest.approx(0.0)
    assert summary["directional_accuracy"]["by_condition"]["B"] == pytest.approx(1.0)
    assert summary["directional_accuracy"]["by_condition"]["C"] == pytest.approx(1.0)
    assert summary["directional_accuracy"]["delta"]["A_to_B"] == pytest.approx(1.0)


def test_summarize_event_results_includes_weighted_rubric_score_block():
    rows = [
        {
            "condition": "A",
            "brier": 0.3,
            "full_simulation_completed": True,
            "simulation_status": "completed",
            "weighted_rubric_score": 0.4,
            "directional_accuracy": 0.0,
        },
        {
            "condition": "B",
            "brier": 0.2,
            "full_simulation_completed": True,
            "simulation_status": "completed",
            "weighted_rubric_score": 0.6,
            "directional_accuracy": 1.0,
        },
        {
            "condition": "C",
            "brier": 0.4,
            "full_simulation_completed": True,
            "simulation_status": "completed",
            "weighted_rubric_score": 0.7,
            "directional_accuracy": 1.0,
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert "weighted_rubric_score" in summary
    assert summary["weighted_rubric_score"]["by_condition"]["A"] == pytest.approx(0.4)
    assert summary["weighted_rubric_score"]["by_condition"]["B"] == pytest.approx(0.6)
    assert summary["weighted_rubric_score"]["by_condition"]["C"] == pytest.approx(0.7)
    assert summary["weighted_rubric_score"]["delta"]["A_to_B"] == pytest.approx(0.2)


def test_summarize_event_results_excludes_non_completed_rows_from_metric_aggregates():
    rows = [
        {
            "condition": "A",
            "brier": 0.2,
            "simulation_status": "completed",
            "full_simulation_completed": True,
            "directional_accuracy": 1.0,
            "weighted_rubric_score": 0.6,
        },
        {
            "condition": "B",
            "brier": 0.1,
            "simulation_status": "evaluation_failed",
            "full_simulation_completed": True,
            "directional_accuracy": 1.0,
            "weighted_rubric_score": 1.0,
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["condition_mean_brier"] == {"A": pytest.approx(0.2)}
    assert summary["directional_accuracy"]["overall"] == pytest.approx(1.0)
    assert summary["weighted_rubric_score"]["overall"] == pytest.approx(0.6)


def test_summarize_event_results_includes_content_susceptibility_and_strict_contract():
    rows = [
        {
            "condition": "A",
            "brier": 0.3,
            "simulation_status": "completed",
            "full_simulation_completed": True,
            "directional_accuracy": 1.0,
            "weighted_rubric_score": 0.4,
            "yes_probability": 0.4,
            "strict_contract": True,
        },
        {
            "condition": "B",
            "brier": 0.2,
            "simulation_status": "completed",
            "full_simulation_completed": True,
            "directional_accuracy": 1.0,
            "weighted_rubric_score": 0.6,
            "yes_probability": 0.7,
            "strict_contract": False,
        },
        {
            "condition": "C",
            "brier": 0.4,
            "simulation_status": "completed",
            "full_simulation_completed": True,
            "directional_accuracy": 0.0,
            "weighted_rubric_score": 0.5,
            "yes_probability": 0.2,
            "strict_contract": True,
        },
        {
            "condition": "B",
            "brier": 0.1,
            "simulation_status": "evaluation_failed",
            "full_simulation_completed": False,
            "directional_accuracy": 1.0,
            "weighted_rubric_score": 0.9,
            "yes_probability": 1.0,
            "strict_contract": False,
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["content_susceptibility"]["mean_yes_probability"]["by_condition"]["A"] == pytest.approx(0.4)
    assert summary["content_susceptibility"]["mean_yes_probability"]["by_condition"]["B"] == pytest.approx(0.7)
    assert summary["content_susceptibility"]["mean_yes_probability"]["by_condition"]["C"] == pytest.approx(0.2)
    assert summary["content_susceptibility"]["delta"]["B_minus_C"] == pytest.approx(0.5)
    assert summary["strict_contract"]["strict_contract_completed_count"] == 2
    assert summary["strict_contract"]["legacy_contract_completed_count"] == 1


def test_signed_susceptibility_pro_yes_positive_delta_has_no_belief_update_failure():
    rows = [
        {
            "event_id": "E1",
            "repeat": 1,
            "condition": "B",
            "brier": 0.2,
            "yes_probability": 0.8,
            "injection_direction": "pro_YES",
            "simulation_status": "completed",
        },
        {
            "event_id": "E1",
            "repeat": 1,
            "condition": "C",
            "brier": 0.3,
            "yes_probability": 0.3,
            "injection_direction": "pro_YES",
            "simulation_status": "completed",
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["signed_susceptibility"]["mean_signed_delta"] == pytest.approx(0.5)
    assert summary["signed_susceptibility"]["directional_accuracy"] == pytest.approx(1.0)
    assert summary["signed_susceptibility"]["belief_update_failure_count"] == 0
    assert summary["signed_susceptibility"]["belief_update_failure_rate"] == pytest.approx(0.0)
    assert summary["signed_susceptibility"]["analyzed_pair_count"] == 1
    assert rows[0]["signed_delta"] == pytest.approx(0.5)
    assert rows[0]["belief_update_failure"] is False
    assert rows[1]["signed_delta"] == pytest.approx(0.5)
    assert rows[1]["belief_update_failure"] is False


def test_belief_update_failure_anti_yes_positive_raw_delta_is_failure():
    rows = [
        {
            "event_id": "E2",
            "repeat": 2,
            "condition": "B",
            "brier": 0.2,
            "yes_probability": 0.7,
            "injection_direction": "anti_YES",
            "simulation_status": "completed",
        },
        {
            "event_id": "E2",
            "repeat": 2,
            "condition": "C",
            "brier": 0.2,
            "yes_probability": 0.2,
            "injection_direction": "anti_YES",
            "simulation_status": "completed",
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["signed_susceptibility"]["mean_signed_delta"] == pytest.approx(-0.5)
    assert summary["signed_susceptibility"]["directional_accuracy"] == pytest.approx(0.0)
    assert summary["signed_susceptibility"]["belief_update_failure_count"] == 1
    assert summary["signed_susceptibility"]["belief_update_failure_rate"] == pytest.approx(1.0)
    assert summary["signed_susceptibility"]["analyzed_pair_count"] == 1
    assert rows[0]["belief_update_failure"] is True
    assert rows[1]["belief_update_failure"] is True


def test_signed_susceptibility_missing_bc_pair_excluded_from_analyzed_count():
    rows = [
        {
            "event_id": "E1",
            "repeat": 1,
            "condition": "B",
            "brier": 0.2,
            "yes_probability": 0.6,
            "injection_direction": "pro_YES",
            "simulation_status": "completed",
        },
        {
            "event_id": "E1",
            "repeat": 1,
            "condition": "C",
            "brier": 0.2,
            "yes_probability": 0.3,
            "injection_direction": "pro_YES",
            "simulation_status": "completed",
        },
        {
            "event_id": "E3",
            "repeat": 1,
            "condition": "B",
            "brier": 0.2,
            "yes_probability": 0.9,
            "injection_direction": "pro_YES",
            "simulation_status": "completed",
        },
        {
            "event_id": "E4",
            "repeat": 1,
            "condition": "B",
            "brier": 0.2,
            "yes_probability": 0.9,
            "injection_direction": "pro_YES",
            "simulation_status": "completed",
        },
        {
            "event_id": "E4",
            "repeat": 1,
            "condition": "C",
            "brier": 0.2,
            "yes_probability": 0.1,
            "injection_direction": "pro_YES",
            "simulation_status": "evaluation_failed",
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["signed_susceptibility"]["analyzed_pair_count"] == 1
    assert summary["signed_susceptibility"]["mean_signed_delta"] == pytest.approx(0.3)


def test_signed_susceptibility_excludes_mismatched_injection_directions():
    rows = [
        {
            "event_id": "E5",
            "repeat": 1,
            "condition": "B",
            "brier": 0.2,
            "yes_probability": 0.8,
            "injection_direction": "pro_YES",
            "simulation_status": "completed",
            "signed_delta": None,
            "belief_update_failure": None,
        },
        {
            "event_id": "E5",
            "repeat": 1,
            "condition": "C",
            "brier": 0.2,
            "yes_probability": 0.3,
            "injection_direction": "anti_YES",
            "simulation_status": "completed",
            "signed_delta": None,
            "belief_update_failure": None,
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["signed_susceptibility"]["analyzed_pair_count"] == 0
    assert summary["signed_susceptibility"]["direction_mismatch_count"] == 1
    assert summary["signed_susceptibility"]["mean_signed_delta"] == pytest.approx(0.0)
    assert rows[0]["signed_delta"] is None
    assert rows[1]["signed_delta"] is None
    assert rows[0]["belief_update_failure"] is None
    assert rows[1]["belief_update_failure"] is None
    assert rows[0]["signed_delta_error"] == "injection_direction_mismatch"
    assert rows[1]["signed_delta_error"] == "injection_direction_mismatch"


def test_compute_delta_conformity_from_actions_logs(tmp_path):
    unit_dir = tmp_path / "E1_C_r1"
    actions_path = unit_dir / "twitter" / "actions.jsonl"
    actions_path.parent.mkdir(parents=True, exist_ok=True)
    actions_path.write_text(
        "\n".join(
            [
                json.dumps({"round": 1, "agent_id": "a1", "action_args": {"probabilities": {"YES": 0.2, "NO": 0.8}}}),
                json.dumps({"round": 1, "agent_id": "a2", "action_args": {"probabilities": {"YES": 0.9, "NO": 0.1}}}),
                json.dumps({"round": 1, "agent_id": "a3", "action_args": {"probabilities": {"YES": 0.3, "NO": 0.7}}}),
                json.dumps({"round": 3, "agent_id": "a1", "action_args": {"probabilities": {"YES": 0.7, "NO": 0.3}}}),
                json.dumps({"round": 3, "agent_id": "a2", "action_args": {"probabilities": {"YES": 0.8, "NO": 0.2}}}),
                json.dumps({"round": 3, "agent_id": "a3", "action_args": {"probabilities": {"YES": 0.1, "NO": 0.9}}}),
            ]
        ),
        encoding="utf-8",
    )

    delta_conformity = protocol_script.compute_delta_conformity(unit_dir, resolved_label="YES")

    assert delta_conformity == pytest.approx(1 / 3)


def test_compute_delta_conformity_returns_none_when_insufficient_data(tmp_path):
    unit_dir = tmp_path / "E1_C_r1"
    actions_path = unit_dir / "twitter" / "actions.jsonl"
    actions_path.parent.mkdir(parents=True, exist_ok=True)
    actions_path.write_text(
        "\n".join(
            [
                json.dumps({"round": 1, "agent_id": "a1", "action_args": {"probabilities": {"YES": 0.2, "NO": 0.8}}}),
                json.dumps({"round": 3, "agent_id": "a2", "action_args": {"probabilities": {"YES": 0.7, "NO": 0.3}}}),
            ]
        ),
        encoding="utf-8",
    )

    delta_conformity = protocol_script.compute_delta_conformity(unit_dir, resolved_label="YES")

    assert delta_conformity is None


def test_summarize_event_results_includes_delta_conformity_aggregate():
    rows = [
        {
            "condition": "C",
            "brier": 0.3,
            "simulation_status": "completed",
            "delta_conformity": 0.25,
        },
        {
            "condition": "C",
            "brier": 0.2,
            "simulation_status": "completed",
            "delta_conformity": 0.75,
        },
        {
            "condition": "B",
            "brier": 0.4,
            "simulation_status": "completed",
            "delta_conformity": None,
        },
        {
            "condition": "C",
            "brier": 0.1,
            "simulation_status": "evaluation_failed",
            "delta_conformity": 1.0,
        },
    ]

    summary = protocol_script.summarize_event_results(rows)

    assert summary["delta_conformity"]["overall"] == pytest.approx(0.5)
    assert summary["delta_conformity"]["by_condition"]["C"] == pytest.approx(0.5)
    assert summary["delta_conformity"]["count"] == 2


def test_main_manifest_includes_topology_metadata(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr="")
    _patch_minimal_main_inputs(monkeypatch, tmp_path, simulation_result=simulation_result)

    output_dir = tmp_path / "runs"
    monkeypatch.setattr(
        protocol_script.sys,
        "argv",
        [
            "run_ecnbench_protocol.py",
            "--seeds-dir",
            str(tmp_path / "seeds"),
            "--events-raw",
            str(tmp_path / "events.json"),
            "--output-dir",
            str(output_dir),
        ],
    )

    protocol_script.main()

    manifest = json.loads((output_dir / "fixed-run" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["topology"]["degree_distribution_descriptor"]
    assert "clustering_coefficient" in manifest["topology"]
