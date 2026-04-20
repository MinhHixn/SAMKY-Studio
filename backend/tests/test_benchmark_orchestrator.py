import json
import subprocess
from pathlib import Path

import pytest

from app.benchmarks.orchestrator import (
    BenchmarkRunOrchestrator,
    ConditionExecutor,
    ProtocolConditionExecutor,
)
from app.benchmarks.schemas import validate_event_result_row


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


def test_protocol_condition_executor_clears_noisy_dimensions_when_completion_trace_write_fails(tmp_path):
    class FakeRouter:
        def model_for(self, role):
            return "openrouter/benchmark-model"

    class TraceWriter:
        def __init__(self):
            self.calls = []

        def write(self, payload):
            self.calls.append(payload)
            if payload.get("status") == "completed":
                raise RuntimeError("trace write failed")

    trace_writer = TraceWriter()

    def simulation_runner(python_exe, config_path, router, *, log_path):
        del python_exe, config_path, router, log_path
        return subprocess.CompletedProcess(args=["python"], returncode=0)

    def config_writer(unit_dir, config):
        path = Path(unit_dir) / "simulation_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def profile_writer(unit_dir, profiles):
        del profiles
        Path(unit_dir).mkdir(parents=True, exist_ok=True)

    def row_builder(event, condition, repeat, **kwargs):
        return {
            "event_id": str(event["event_id"]),
            "condition": condition,
            "repeat": repeat,
            **kwargs,
        }

    executor = ProtocolConditionExecutor(
        router=FakeRouter(),
        python_exe="python",
        profiles=[],
        seed_files=[tmp_path / "seed.md"],
        event_index_lookup={"E1": 0},
        trace_writer=trace_writer,
        simulation_timeout_seconds=30,
        simulation_runner=simulation_runner,
        simulation_failure_error_builder=lambda *_args, **_kwargs: "simulation failed",
        config_writer=config_writer,
        profile_writer=profile_writer,
        evidence_builder=lambda *_args, **_kwargs: "evidence text",
        row_builder=row_builder,
        exception_formatter=lambda exc: f"{type(exc).__name__}: {exc}",
    )

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="B",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_B_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
            "evaluator_noisy_dimensions": ["convergence"],
        },
    )

    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluator_noisy_dimensions"] is None
    assert row["error"] == "RuntimeError: trace write failed"


def _build_protocol_executor(tmp_path, *, telemetry_builder=None, baseline_scores_builder=None):
    trace_entries: list[dict[str, object]] = []

    class FakeRouter:
        def model_for(self, role):
            return "openrouter/benchmark-model"

    class FakeTraceWriter:
        def write(self, payload):
            trace_entries.append(payload)

    def simulation_runner(python_exe, config_path, router, *, log_path):
        del router
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("simulation ok", encoding="utf-8")
        return subprocess.CompletedProcess(args=[python_exe, str(config_path)], returncode=0)

    def config_writer(unit_dir, config):
        config_path = Path(unit_dir) / "simulation_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return config_path

    def profile_writer(unit_dir, profiles):
        (Path(unit_dir) / "profiles.json").write_text(json.dumps(profiles), encoding="utf-8")

    def row_builder(event, condition, repeat, **kwargs):
        return {
            "event_id": str(event["event_id"]),
            "condition": condition,
            "repeat": repeat,
            "unit_id": f"{event['event_id']}_{condition}_r{repeat}",
            **kwargs,
        }

    executor = ProtocolConditionExecutor(
        router=FakeRouter(),
        python_exe="python",
        profiles=[],
        seed_files=[tmp_path / "seed.md"],
        event_index_lookup={"E1": 0},
        trace_writer=FakeTraceWriter(),
        simulation_timeout_seconds=30,
        simulation_runner=simulation_runner,
        simulation_failure_error_builder=lambda *_args, **_kwargs: "simulation failed",
        config_writer=config_writer,
        profile_writer=profile_writer,
        evidence_builder=lambda *_args, **_kwargs: "evidence text",
        row_builder=row_builder,
        telemetry_builder=telemetry_builder,
        baseline_scores_builder=baseline_scores_builder,
        exception_formatter=lambda exc: f"{type(exc).__name__}: {exc}",
    )

    return executor, trace_entries


def test_protocol_condition_executor_populates_telemetry_fields(tmp_path):
    def telemetry_builder(unit_dir, event):
        del unit_dir, event
        return [0.1, 0.2, 0.3, 0.4, 0.5], True

    def baseline_scores_builder(event):
        del event
        return {
            "uniform_random": {"probabilities": {"YES": 0.5, "NO": 0.5}, "brier": 0.5},
            "market_prior": {"probabilities": {"YES": 0.6, "NO": 0.4}, "brier": 0.4},
        }

    executor, _trace_entries = _build_protocol_executor(
        tmp_path,
        telemetry_builder=telemetry_builder,
        baseline_scores_builder=baseline_scores_builder,
    )

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "YES", "options": ["YES", "NO"]},
        condition="B",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_B_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: {
            "probabilities": {"YES": 0.7, "NO": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
    )

    assert row["round_jsd"] == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert row["convergence_monotonic"] is True
    assert set(row["baseline_scores"]) == {"uniform_random", "market_prior"}


def test_protocol_condition_executor_telemetry_failure_appends_error(tmp_path):
    def telemetry_builder(unit_dir, event):
        del unit_dir, event
        raise ValueError("telemetry failed")

    executor, _trace_entries = _build_protocol_executor(tmp_path, telemetry_builder=telemetry_builder)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "YES", "options": ["YES", "NO"]},
        condition="B",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_B_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: {
            "probabilities": {"YES": 0.7, "NO": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
    )

    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluation_completed"] is False
    assert row["probabilities"] == {"YES": 0.7, "NO": 0.3}
    assert row["brier"] == 0.09
    assert row["round_jsd"] is None
    assert row["convergence_monotonic"] is None
    assert row["error"] == "Telemetry error: ValueError: telemetry failed"


def test_protocol_condition_executor_baseline_failure_appends_error_and_keeps_keys(tmp_path):
    def telemetry_builder(unit_dir, event):
        del unit_dir, event
        return [0.1, 0.2, 0.3, 0.4, 0.5], True

    def baseline_scores_builder(event):
        del event
        raise ValueError("baseline failed")

    def evaluator(*_args, **_kwargs):
        raise ValueError("evaluation failed")

    executor, _trace_entries = _build_protocol_executor(
        tmp_path,
        telemetry_builder=telemetry_builder,
        baseline_scores_builder=baseline_scores_builder,
    )

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "YES", "options": ["YES", "NO"]},
        condition="B",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_B_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=evaluator,
    )

    assert row["unit_id"] == "E1_B_r1"
    assert row["simulation_status"] == "evaluation_failed"
    assert row["round_jsd"] == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert row["convergence_monotonic"] is True
    assert row["baseline_scores"] is None
    assert "ValueError: evaluation failed" in row["error"]
    assert "Baseline error: ValueError: baseline failed" in row["error"]


def _valid_mcq_dimensions():
    dimension_keys = (
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    )
    return {
        key: {"very_low": 1.0, "low": 1.0, "high": 1.0, "very_high": 1.0}
        for key in dimension_keys
    }


def _valid_validated_scales():
    return {"schema_version": "v1", "scores": {"evidence_alignment": 0.7}}


def test_protocol_condition_executor_execute_supports_mapping_payload(tmp_path):
    executor, trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
    )

    assert row["simulation_status"] == "completed"
    assert row["evaluation_completed"] is True
    assert row["probabilities"] == {"A": 0.7, "B": 0.3}
    assert row["brier"] == 0.09
    assert row["strict_contract"] is True
    assert set(row["mcq_dimensions"]) == {
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    }
    assert row["validated_scales"] == _valid_validated_scales()
    assert trace_entries[-1]["status"] == "completed"


def test_protocol_condition_executor_execute_forwards_evaluator_noisy_dimensions(tmp_path):
    executor, _trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
            "evaluator_noisy_dimensions": ["convergence"],
        },
    )

    assert row["evaluator_noisy_dimensions"] == ["convergence"]


def test_protocol_condition_executor_execute_keeps_missing_evaluator_noisy_dimensions_backward_compatible(
    tmp_path,
):
    executor, _trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
    )

    assert row["evaluator_noisy_dimensions"] is None


def test_protocol_condition_executor_execute_supports_legacy_tuple_payload(tmp_path):
    executor, _trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: ({"A": 1.0}, 0.0),
    )

    # Tuple payload support is intentional for legacy evaluator compatibility.
    assert row["simulation_status"] == "completed"
    assert row["evaluation_completed"] is True
    assert row["probabilities"] == {"A": 1.0}
    assert row["brier"] == 0.0
    assert row["strict_contract"] is False
    assert row["mcq_dimensions"] is None
    assert row["validated_scales"] is None


def test_protocol_condition_executor_execute_unsupported_payload_falls_back_to_evaluation_failed(tmp_path):
    executor, trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: "bad payload",
    )

    # Unsupported evaluator payloads should produce the evaluation_failed fallback row.
    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluation_completed"] is False
    assert row["probabilities"] is None
    assert row["brier"] is None
    assert row["error"] == "ValueError: Evaluator result must be a tuple or mapping"
    assert trace_entries[-1]["status"] == "evaluation_failed"


@pytest.mark.parametrize(
    "payload",
    [
        {"brier": 0.09, "mcq_dimensions": _valid_mcq_dimensions(), "validated_scales": _valid_validated_scales()},
        {
            "probabilities": ["A", 0.7],
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": "NaN?"},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 0.7},
            "brier": "not-a-number",
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 0.7},
            "brier": 0.09,
            "mcq_dimensions": [],
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 0.7},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": [],
        },
    ],
)
def test_protocol_condition_executor_execute_malformed_mapping_payload_falls_back_to_evaluation_failed(
    tmp_path, payload
):
    executor, trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: payload,
    )

    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluation_completed"] is False
    assert row["probabilities"] is None
    assert row["brier"] is None
    assert trace_entries[-1]["status"] == "evaluation_failed"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "probabilities": {"A": float("nan"), "B": 1.0},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": float("inf"), "B": 1.0},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 1.0, "B": 0.0},
            "brier": float("nan"),
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 1.0, "B": 0.0},
            "brier": float("inf"),
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
    ],
)
def test_protocol_condition_executor_execute_non_finite_mapping_payload_falls_back_to_evaluation_failed(
    tmp_path, payload
):
    executor, trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: payload,
    )

    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluation_completed"] is False
    assert row["probabilities"] is None
    assert row["brier"] is None
    assert trace_entries[-1]["status"] == "evaluation_failed"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "probabilities": {"A": -0.1, "B": 1.1},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 0.0, "B": 0.0},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": -1.0, "B": 1.0},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
    ],
)
def test_protocol_condition_executor_execute_invalid_probability_mass_falls_back_to_evaluation_failed(
    tmp_path, payload
):
    executor, trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: payload,
    )

    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluation_completed"] is False
    assert row["probabilities"] is None
    assert row["brier"] is None
    assert trace_entries[-1]["status"] == "evaluation_failed"


def test_protocol_executor_condition_a_skips_simulation_subprocess(tmp_path):
    # Fake simulation runner increments call counter and raises
    call_counter = {"count": 0}
    def fake_runner(*args, **kwargs):
        call_counter["count"] += 1
        raise RuntimeError("Simulation should not be called for condition A")

    executor, trace_entries = _build_protocol_executor(tmp_path)
    executor._simulation_runner = fake_runner
    payload = {
        "probabilities": {"A": 1.0, "B": 0.0},
        "brier": 0.0,
        "mcq_dimensions": _valid_mcq_dimensions(),
        "validated_scales": _valid_validated_scales(),
    }
    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: payload,
    )
    assert call_counter["count"] == 0
    assert row["simulation_executed"] is False
    assert row["simulation_status"] == "completed"
    assert row["simulation_completed"] is True
    assert row["evaluation_completed"] is True
    assert row["evidence_text"] == "evidence text"

@pytest.mark.parametrize(
    "payload",
    [
        ({"A": float("nan"), "B": 1.0}, 0.09),
        ({"A": float("inf"), "B": 1.0}, 0.09),
        ({"A": -1.0, "B": 1.0}, 0.09),
        ({"A": 0.0, "B": 0.0}, 0.09),
        ({"A": 1.0, "B": 0.0}, float("nan")),
        ({"A": 1.0, "B": 0.0}, float("inf")),
        ({"A": 1.0, "B": 0.0}, "bad"),
    ],
)
def test_protocol_condition_executor_execute_invalid_tuple_payload_falls_back_to_evaluation_failed(
    tmp_path, payload
):
    executor, trace_entries = _build_protocol_executor(tmp_path)
    probabilities, brier = payload

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: (probabilities, brier),
    )

    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluation_completed"] is False
    assert row["probabilities"] is None
    assert row["brier"] is None
    assert trace_entries[-1]["status"] == "evaluation_failed"


@pytest.mark.parametrize(
    "payload",
    [
        {"probabilities": {"A": 0.7, "B": 0.3}, "brier": 0.09, "mcq_dimensions": {}, "validated_scales": _valid_validated_scales()},
        {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": {
                **_valid_mcq_dimensions(),
                "extra_dimension": {"very_low": 1.0, "low": 1.0, "high": 1.0, "very_high": 1.0},
            },
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": {
                **_valid_mcq_dimensions(),
                "prediction_accuracy": {"very_low": 1.0, "low": 1.0, "high": 1.0},
            },
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": {
                **_valid_mcq_dimensions(),
                "prediction_accuracy": {"very_low": 1.0, "low": -1.0, "high": 1.0, "very_high": 1.0},
            },
            "validated_scales": _valid_validated_scales(),
        },
        {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": {"schema_version": "v2", "scores": {"evidence_alignment": 0.7}},
        },
        {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": {"schema_version": "v1", "scores": {}},
        },
        {
            "probabilities": {"A": 0.7, "B": 0.3},
            "brier": 0.09,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": {"schema_version": "v1", "scores": {"evidence_alignment": float("nan")}},
        },
    ],
)
def test_protocol_condition_executor_execute_invalid_mapping_rubric_falls_back_to_evaluation_failed(
    tmp_path, payload
):
    executor, trace_entries = _build_protocol_executor(tmp_path)

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "E1_A_r1",
        seed_file=tmp_path / "ignored-seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: payload,
    )

    assert row["simulation_status"] == "evaluation_failed"
    assert row["evaluation_completed"] is False
    assert row["probabilities"] is None
    assert row["brier"] is None
    assert trace_entries[-1]["status"] == "evaluation_failed"


def test_orchestrator_writes_event_results_and_summary(tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "simulation_status": "completed",
                "full_simulation_completed": True,
                "probabilities": {"A": 0.7, "B": 0.3},
                "brier": 0.2,
                "baseline_scores": {
                    "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
                    "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
                },
                "round_jsd": [0.1, 0.2, 0.3, 0.4, 0.5],
                "convergence_monotonic": True,
                "rps": 0.19,
                "calibration_bracket": "0.5-0.75",
                "delta_conformity": None,
                "signed_delta": None,
                "belief_update_failure": None,
                "yes_probability": None,
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
    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    assert set(rows[0]["baseline_scores"]) == {"uniform_random", "market_prior"}
    assert rows[0]["round_jsd"] == [0.1, 0.2, 0.3, 0.4, 0.5]


def test_orchestrator_cleanup_removes_summary_artifacts_after_summary_enrichment_validation_failure(tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "simulation_status": "completed",
                "full_simulation_completed": True,
                "probabilities": {"A": 0.7, "B": 0.3},
                "brier": 0.2,
                "baseline_scores": {
                    "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
                    "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
                },
                "round_jsd": [0.1, 0.2, 0.3, 0.4, 0.5],
                "convergence_monotonic": True,
                "rps": 0.19,
                "calibration_bracket": "0.5-0.75",
                "delta_conformity": None,
                "signed_delta": None,
                "belief_update_failure": None,
                "yes_probability": None,
            }

    orchestrator = BenchmarkRunOrchestrator(executor=FakeExecutor())

    def invalidating_write_summary(path, rows):
        rows[0]["brier"] = "invalid-after-enrichment"
        (path / "calibration_curve.png").write_text("stub-plot", encoding="utf-8")
        (path / "summary.json").write_text(
            json.dumps({"total_rows": len(rows), "calibration": {"plot_path": str(path / "calibration_curve.png")}}),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match=r"rows\[0\].*'brier' must be finite"):
        orchestrator.run(
            run_id="fixed-run",
            output_root=tmp_path,
            events=[{"event_id": "E1"}],
            repeats=1,
            build_condition_matrix=lambda events, repeats: [{"event_id": "E1", "condition": "A", "repeat": 1}],
            event_lookup={"E1": {"event_id": "E1"}},
            write_summary=invalidating_write_summary,
        )

    assert not (tmp_path / "fixed-run" / "event_results.json").exists()
    assert not (tmp_path / "fixed-run" / "summary.json").exists()
    assert not (tmp_path / "fixed-run" / "calibration_curve.png").exists()


def test_orchestrator_clears_stale_artifacts_on_rerun_when_validation_fails_before_write(tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "simulation_status": "completed",
                "full_simulation_completed": True,
                "probabilities": {"A": 0.7, "B": 0.3},
                "brier": "invalid-before-write",
                "baseline_scores": {
                    "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
                    "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
                },
                "round_jsd": [0.1, 0.2, 0.3, 0.4, 0.5],
                "convergence_monotonic": True,
                "rps": 0.19,
                "calibration_bracket": "0.5-0.75",
                "delta_conformity": None,
                "signed_delta": None,
                "belief_update_failure": None,
                "yes_probability": None,
            }

    orchestrator = BenchmarkRunOrchestrator(executor=FakeExecutor())
    run_dir = tmp_path / "fixed-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "event_results.json").write_text(json.dumps([{"event_id": "stale"}]), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps({"total_rows": 999}), encoding="utf-8")

    with pytest.raises(ValueError, match=r"rows\[0\].*'brier' must be finite"):
        orchestrator.run(
            run_id="fixed-run",
            output_root=tmp_path,
            events=[{"event_id": "E1"}],
            repeats=1,
            build_condition_matrix=lambda events, repeats: [{"event_id": "E1", "condition": "A", "repeat": 1}],
            event_lookup={"E1": {"event_id": "E1"}},
            write_summary=lambda *_args, **_kwargs: None,
        )

    assert not (run_dir / "event_results.json").exists()
    assert not (run_dir / "summary.json").exists()


def test_orchestrator_writes_provided_manifest_payload(tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "simulation_status": "completed",
                "full_simulation_completed": True,
                "probabilities": {"A": 0.7, "B": 0.3},
                "brier": 0.2,
                "round_jsd": None,
                "convergence_monotonic": None,
                "baseline_scores": {
                    "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
                    "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
                },
                "rps": 0.19,
                "calibration_bracket": "0.5-0.75",
                "delta_conformity": None,
                "signed_delta": None,
                "belief_update_failure": None,
                "yes_probability": None,
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


def test_orchestrator_enforces_deterministic_manifest_fields_in_benchmark_mode(monkeypatch, tmp_path):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "event_id": kwargs["event"]["event_id"],
                "condition": kwargs["condition"],
                "repeat": kwargs["repeat"],
                "simulation_status": "completed",
                "full_simulation_completed": True,
                "probabilities": {"A": 0.7, "B": 0.3},
                "brier": 0.2,
                "baseline_scores": {
                    "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
                    "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
                },
                "round_jsd": [0.1, 0.2, 0.3, 0.4, 0.5],
                "convergence_monotonic": True,
                "rps": 0.19,
                "calibration_bracket": "0.5-0.75",
                "delta_conformity": None,
                "signed_delta": None,
                "belief_update_failure": None,
                "yes_probability": None,
            }

    monkeypatch.setenv("BENCHMARK_MODE", "true")
    monkeypatch.setenv("HEADLESS_MODE", "false")
    orchestrator = BenchmarkRunOrchestrator(executor=FakeExecutor())
    manifest_payload = {
        "run_id": "fixed-run",
        "events_loaded": 1,
        "repeats": 1,
        "deterministic_mode": False,
        "enforced_temperature": 0.8,
        "enforced_seed": 999,
        "headless_mode": False,
        "custom_note": "keep-me",
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
    assert manifest["custom_note"] == "keep-me"
    assert manifest["deterministic_mode"] is True
    assert manifest["enforced_temperature"] == 0.0
    assert manifest["enforced_seed"] == 42
    assert manifest["headless_mode"] is True


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
                "round_jsd": [0.2, 0.15, 0.1, 0.05, 0.01],
                "convergence_monotonic": True,
                "baseline_scores": {
                    "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
                    "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
                },
                "rps": 0.0,
                "calibration_bracket": "0.75-1.0",
                "delta_conformity": None,
                "signed_delta": None,
                "belief_update_failure": None,
                "yes_probability": None,
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
                "round_jsd": [0.2, 0.15, 0.1, 0.05, 0.01],
                "convergence_monotonic": True,
                "baseline_scores": {
                    "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
                    "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
                },
                "rps": 0.0,
                "calibration_bracket": "0.75-1.0",
                "delta_conformity": None,
                "signed_delta": None,
                "belief_update_failure": None,
                "yes_probability": None,
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


def test_orchestrator_fallback_row_contains_rubric_keys(tmp_path):
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
                "round_jsd": None,
                "convergence_monotonic": None,
                "baseline_scores": {
                    "uniform_random": {"probabilities": {"A": 0.5, "B": 0.5}, "brier": 0.5},
                    "market_prior": {"probabilities": {"A": 0.6, "B": 0.4}, "brier": 0.4},
                },
                "rps": 0.0,
                "calibration_bracket": "0.75-1.0",
                "delta_conformity": None,
                "signed_delta": None,
                "belief_update_failure": None,
                "yes_probability": None,
            }

    orchestrator = BenchmarkRunOrchestrator(executor=FakeExecutor())
    seed_path = tmp_path / "seed.md"
    seed_path.write_text("seed", encoding="utf-8")

    run_dir = orchestrator.run(
        run_id="fallback-rubric-run",
        output_root=tmp_path,
        events=[{"event_id": "E1"}],
        repeats=1,
        build_condition_matrix=lambda events, repeats: [
            {"event_id": "E1", "repeat": 1},
        ],
        event_lookup={"E1": {"event_id": "E1"}},
        write_summary=lambda path, rows: (path / "summary.json").write_text(
            json.dumps({"total_rows": len(rows)}), encoding="utf-8"
        ),
        seed_file=seed_path,
    )

    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    assert len(rows) == 1
    row = rows[0]
    assert row["simulation_status"] == "simulation_failed"
    assert row["probabilities"] is None
    assert row["round_jsd"] is None
    assert row["convergence_monotonic"] is None
    assert row["mcq_dimensions"] is None
    assert row["validated_scales"] is None
    assert row["baseline_scores"] is None
    assert row["rps"] is None
    assert row["calibration_bracket"] is None
    assert row["delta_conformity"] is None
    validate_event_result_row(row)
