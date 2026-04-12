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
        lambda *args, **kwargs: subprocess.CompletedProcess(args=["python"], returncode=1),
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
    assert row["full_simulation_completed"] is False


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
