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

    class DummyInjectionLoader:
        pass

    class FakeOrchestrator:
        def __init__(self, executor):
            self.executor = executor

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
    assert captured["build_condition_matrix"] is protocol_script.build_condition_matrix
    assert captured["event_lookup"] == {"E1": {"event_id": "E1", "question": "Q", "outcome": "A"}}
    assert captured["write_summary"] is protocol_script.write_summary
    assert captured["evaluator"] is protocol_script._evaluate_row
    assert captured["run_dir_exists_before_run"] is False
    assert captured["manifest_exists_before_run"] is False
    assert captured["built_config"] == {"event_id": "E1", "condition": "A"}
    assert len(config_builder_calls) == 1
    event, condition, profiles, injection_loader, llm_model = config_builder_calls[0]
    assert event == {"event_id": "E1", "question": "Q", "outcome": "A"}
    assert condition == "A"
    assert profiles == [{"agent_id": 1}]
    assert isinstance(injection_loader, DummyInjectionLoader)
    assert llm_model == "m"


def test_main_records_simulation_failure_and_summary(monkeypatch, tmp_path):
    simulation_result = subprocess.CompletedProcess(args=["python"], returncode=1, stdout="", stderr="boom")
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
    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert rows[0]["simulation_status"] == "simulation_failed"
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

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["python"], timeout=protocol_script.SIMULATION_SUBPROCESS_TIMEOUT_SECONDS)

    monkeypatch.setattr(protocol_script, "_run_simulation_subprocess", raise_timeout)

    output_dir = tmp_path / "runs"
    run_dir = output_dir / "fixed-run"
    unit_dir = run_dir / "E1_A_r1"
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
