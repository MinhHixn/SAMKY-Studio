import json
import subprocess
from pathlib import Path

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


def test_build_event_result_row_surfaces_missing_seed_metadata_error(tmp_path):
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

    assert row["error"] is not None
    assert "FileNotFoundError" in row["error"]
    assert row["injection_direction"] is None
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


def _patch_minimal_main_inputs(monkeypatch, tmp_path, *, simulation_result, evaluate_side_effect=None):
    events = [{"event_id": "E1", "question": "Q1", "outcome": "A", "options": ["A", "B"]}]
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


def test_main_delegates_run_loop_to_orchestrator(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    config_builder_calls: list[tuple[dict[str, object], str, list[dict[str, object]], object, str]] = []
    executor_ctor_calls: dict[str, object] = {}

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
        lambda *args, **kwargs: [{"event_id": "E1", "question": "Q", "outcome": "A"}],
    )
    monkeypatch.setattr(protocol_script, "load_seed_files", lambda *args, **kwargs: [tmp_path / "seed.md"])
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
    assert captured["events"] == [{"event_id": "E1", "question": "Q", "outcome": "A"}]
    assert captured["repeats"] == 1
    assert callable(captured["build_condition_matrix"])
    assert captured["build_condition_matrix"]([], 99) == protocol_script.build_condition_matrix(captured["events"], captured["repeats"])
    assert captured["event_lookup"] == {"E1": {"event_id": "E1", "question": "Q", "outcome": "A"}}
    assert captured["write_summary"] is protocol_script.write_summary
    assert captured["evaluator"] is protocol_script._evaluate_row
    assert captured["manifest"]["run_id"] == "fixed-run"
    assert captured["manifest"]["events_loaded"] == 1
    assert captured["manifest"]["trace_out"].endswith("traces\\execution.jsonl")
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


def test_main_manifest_includes_continuation_metadata(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=0, stdout="", stderr="")
    _patch_minimal_main_inputs(monkeypatch, tmp_path, simulation_result=simulation_result)
    custom_events = [
        {"event_id": "E1", "question": "Q1", "outcome": "A", "options": ["A", "B"]},
        {"event_id": "E2", "question": "Q2", "outcome": "B", "options": ["A", "B"]},
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
