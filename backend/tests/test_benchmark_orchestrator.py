import json
import subprocess
from pathlib import Path

from app.benchmarks.orchestrator import BenchmarkRunOrchestrator, ConditionExecutor


def test_condition_executor_returns_simulation_failed_row(monkeypatch, tmp_path):
    class FakeRouter:
        def model_for(self, role):
            return "openrouter/benchmark-model"

    executor = ConditionExecutor(
        router=FakeRouter(),
        python_exe="python",
        backend_dir=Path(tmp_path),
    )

    monkeypatch.setattr(
        executor,
        "_run_simulation",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout="simulation stdout",
            stderr="simulation stderr",
        ),
    )

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: ({"A": 1.0}, 0.0),
    )

    assert row["simulation_status"] == "simulation_failed"
    assert row["evaluation_status"] == "not_run"
    assert row["full_simulation_completed"] is False
    assert row["run_id"] == "r1"
    assert row["unit_id"] == "E1_A_r1"
    assert row["seed_file"] == str(tmp_path / "seed.md")
    assert row["probabilities"] is None
    assert row["brier"] is None
    assert "simulation stderr" in row["error"]
    assert (tmp_path / "E1_A_r1" / "simulation.log").read_text(encoding="utf-8") == "simulation stdout\nsimulation stderr"


def test_condition_executor_returns_evaluation_failed_row(monkeypatch, tmp_path):
    class FakeRouter:
        def model_for(self, role):
            return "openrouter/benchmark-model"

    executor = ConditionExecutor(
        router=FakeRouter(),
        python_exe="python",
        backend_dir=Path(tmp_path),
    )

    monkeypatch.setattr(
        executor,
        "_run_simulation",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout="simulation ok",
            stderr="",
        ),
    )

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad evaluation")),
    )

    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluation_status"] == "failed"
    assert row["run_id"] == "r1"
    assert row["unit_id"] == "E1_A_r1"
    assert row["seed_file"] == str(tmp_path / "seed.md")
    assert row["probabilities"] is None
    assert row["brier"] is None
    assert "ValueError: bad evaluation" == row["error"]
    assert (tmp_path / "E1_A_r1" / "simulation.log").read_text(encoding="utf-8") == "simulation ok"


def test_orchestrator_writes_event_results_and_summary(tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "simulation_status": "completed",
                "full_simulation_completed": True,
                "brier": 0.2,
            }

    orchestrator = BenchmarkRunOrchestrator(executor=FakeExecutor())

    run_dir = orchestrator.run(
        run_id="fixed-run",
        output_root=tmp_path,
        events=[{"event_id": "E1"}],
        repeats=1,
        build_condition_matrix=lambda events, repeats: [{"event_id": "E1", "condition": "A", "repeat": 1}],
        event_lookup={"E1": {"event_id": "E1"}},
        write_summary=lambda path, rows: (path / "summary.json").write_text(
            json.dumps({"total_rows": len(rows)}), encoding="utf-8"
        ),
    )

    assert (run_dir / "event_results.json").exists()
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "traces" / "execution.jsonl").exists()
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "run_id": "fixed-run",
        "events_loaded": 1,
        "repeats": 1,
    }


def test_orchestrator_writes_provided_manifest_payload(tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "simulation_status": "completed",
                "full_simulation_completed": True,
                "brier": 0.2,
            }

    orchestrator = BenchmarkRunOrchestrator(executor=FakeExecutor())
    manifest_payload = {
        "run_id": "fixed-run",
        "events_loaded": 1,
        "repeats": 1,
        "trace_out": "custom/trace.jsonl",
        "seed_files": ["seed-a.md"],
    }

    run_dir = orchestrator.run(
        run_id="fixed-run",
        output_root=tmp_path,
        events=[{"event_id": "E1"}],
        repeats=1,
        build_condition_matrix=lambda events, repeats: [{"event_id": "E1", "condition": "A", "repeat": 1}],
        event_lookup={"E1": {"event_id": "E1"}},
        write_summary=lambda path, rows: (path / "summary.json").write_text(
            json.dumps({"total_rows": len(rows)}), encoding="utf-8"
        ),
        manifest=manifest_payload,
    )

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest == manifest_payload


def test_orchestrator_keeps_processing_after_unit_failure(tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            if kwargs["event"]["event_id"] == "E1":
                raise RuntimeError("unit boom")
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "run_id": kwargs["run_id"],
                "seed_file": str(kwargs["seed_file"]),
                "simulation_status": "completed",
                "evaluation_status": "completed",
                "full_simulation_completed": True,
                "probabilities": {"A": 1.0},
                "brier": 0.0,
            }

    orchestrator = BenchmarkRunOrchestrator(executor=FakeExecutor())
    seed_path = tmp_path / "seed.md"
    seed_path.write_text("seed", encoding="utf-8")

    run_dir = orchestrator.run(
        run_id="isolated-run",
        output_root=tmp_path,
        events=[{"event_id": "E1"}, {"event_id": "E2"}],
        repeats=1,
        build_condition_matrix=lambda events, repeats: [
            {"event_id": "E1", "condition": "A", "repeat": 1},
            {"event_id": "E2", "condition": "B", "repeat": 1},
        ],
        event_lookup={"E1": {"event_id": "E1"}, "E2": {"event_id": "E2"}},
        write_summary=lambda path, rows: (path / "summary.json").write_text(
            json.dumps({"total_rows": len(rows)}), encoding="utf-8"
        ),
        seed_file=seed_path,
    )

    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    assert len(rows) == 2
    first_row, second_row = rows
    assert first_row["event_id"] == "E1"
    assert first_row["unit_id"] == "E1_A_r1"
    assert first_row["simulation_status"] == "simulation_failed"
    assert first_row["evaluation_status"] == "not_run"
    assert first_row["run_id"] == "isolated-run"
    assert first_row["seed_file"] == str(seed_path)
    assert first_row["probabilities"] is None
    assert first_row["brier"] is None
    assert "RuntimeError: unit boom" == first_row["error"]
    assert second_row["event_id"] == "E2"
    assert second_row["unit_id"] == "E2_B_r1"
    assert second_row["simulation_status"] == "completed"


def test_orchestrator_isolates_malformed_rows_and_missing_event_lookup(tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "run_id": kwargs["run_id"],
                "seed_file": str(kwargs["seed_file"]),
                "simulation_status": "completed",
                "evaluation_status": "completed",
                "full_simulation_completed": True,
                "probabilities": {"A": 1.0},
                "brier": 0.0,
            }

    orchestrator = BenchmarkRunOrchestrator(executor=FakeExecutor())
    seed_path = tmp_path / "seed.md"
    seed_path.write_text("seed", encoding="utf-8")

    run_dir = orchestrator.run(
        run_id="malformed-run",
        output_root=tmp_path,
        events=[{"event_id": "E1"}, {"event_id": "E2"}],
        repeats=1,
        build_condition_matrix=lambda events, repeats: [
            {"event_id": "E1", "condition": "A", "repeat": 1},
            {"event_id": "E2", "repeat": 1},
            {"event_id": "MISSING", "condition": "C", "repeat": 1},
            {"event_id": "E2", "condition": "B", "repeat": 1},
        ],
        event_lookup={"E1": {"event_id": "E1"}, "E2": {"event_id": "E2"}},
        write_summary=lambda path, rows: (path / "summary.json").write_text(
            json.dumps({"total_rows": len(rows)}), encoding="utf-8"
        ),
        seed_file=seed_path,
    )

    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    assert len(rows) == 4

    assert rows[0]["event_id"] == "E1"
    assert rows[0]["simulation_status"] == "completed"

    assert rows[1]["event_id"] == "E2"
    assert rows[1]["condition"] == "unknown_condition"
    assert rows[1]["unit_id"] == "E2_unknown_condition_r1"
    assert rows[1]["simulation_status"] == "simulation_failed"
    assert rows[1]["evaluation_status"] == "not_run"
    assert "'condition'" in rows[1]["error"]

    assert rows[2]["event_id"] == "MISSING"
    assert rows[2]["condition"] == "C"
    assert rows[2]["unit_id"] == "MISSING_C_r1"
    assert rows[2]["simulation_status"] == "simulation_failed"
    assert rows[2]["evaluation_status"] == "not_run"
    assert "'MISSING'" in rows[2]["error"]

    assert rows[3]["event_id"] == "E2"
    assert rows[3]["condition"] == "B"
    assert rows[3]["simulation_status"] == "completed"
