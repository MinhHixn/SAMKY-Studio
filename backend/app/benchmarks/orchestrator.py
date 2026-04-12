from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Mapping


class ConditionExecutor:
    def __init__(self, router: Any, python_exe: str, backend_dir: Path):
        self._router = router
        self._python_exe = python_exe
        self._backend_dir = Path(backend_dir)

    def _subprocess_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        api_key = getattr(self._router, "api_key", None)
        base_url = getattr(self._router, "base_url", None)
        if api_key:
            env["LLM_API_KEY"] = str(api_key)
        if base_url:
            env["LLM_BASE_URL"] = str(base_url)
        try:
            env["LLM_MODEL_NAME"] = str(self._router.model_for("benchmark"))
        except Exception:
            pass
        return env

    def _run_simulation(self, config_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self._python_exe,
                "scripts/run_parallel_simulation.py",
                "--config",
                str(config_path),
                "--max-rounds",
                "60",
                "--no-wait",
            ],
            cwd=str(self._backend_dir),
            text=True,
            timeout=60 * 60 * 60,
            env=self._subprocess_env(),
            capture_output=True,
        )

    @staticmethod
    def _write_simulation_log(unit_dir: Path, stdout: str | None, stderr: str | None) -> None:
        lines: list[str] = []
        if stdout:
            lines.append(stdout.rstrip("\n"))
        if stderr:
            lines.append(stderr.rstrip("\n"))
        (Path(unit_dir) / "simulation.log").write_text("\n".join(lines), encoding="utf-8")

    def execute(
        self,
        *,
        event: Mapping[str, Any],
        condition: str,
        repeat: int,
        run_id: str,
        unit_dir: Path,
        seed_file: Path,
        config_builder: Callable[..., Dict[str, Any]],
        evaluator: Callable[..., tuple[Dict[str, float], float]],
    ) -> Dict[str, Any]:
        unit_dir = Path(unit_dir)
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_id = f"{event['event_id']}_{condition}_r{repeat}"

        config = config_builder(event, condition)
        config_path = unit_dir / "simulation_config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

        base_row = {
            "event_id": str(event["event_id"]),
            "condition": condition,
            "repeat": repeat,
            "unit_id": unit_id,
            "run_id": run_id,
            "seed_file": str(seed_file),
        }

        try:
            completed = self._run_simulation(config_path)
            self._write_simulation_log(unit_dir, completed.stdout, completed.stderr)
        except Exception as exc:
            self._write_simulation_log(unit_dir, "", f"{type(exc).__name__}: {exc}")
            return {
                **base_row,
                "simulation_status": "simulation_failed",
                "evaluation_status": "not_run",
                "full_simulation_completed": False,
                "probabilities": None,
                "brier": None,
                "error": f"{type(exc).__name__}: {exc}",
            }

        if completed.returncode != 0:
            error_output = (completed.stderr or completed.stdout or "").strip() or "Simulation process exited with non-zero status"
            return {
                **base_row,
                "simulation_status": "simulation_failed",
                "evaluation_status": "not_run",
                "full_simulation_completed": False,
                "probabilities": None,
                "brier": None,
                "error": error_output,
            }

        try:
            probabilities, brier = evaluator(event, condition)
        except Exception as exc:
            return {
                **base_row,
                "simulation_status": "evaluation_failed",
                "evaluation_status": "failed",
                "full_simulation_completed": False,
                "probabilities": None,
                "brier": None,
                "error": f"{type(exc).__name__}: {exc}",
            }

        return {
            **base_row,
            "simulation_status": "completed",
            "evaluation_status": "completed",
            "full_simulation_completed": True,
            "probabilities": probabilities,
            "brier": brier,
        }


class ProtocolConditionExecutor:
    def __init__(
        self,
        *,
        router: Any,
        python_exe: str,
        profiles: list[Dict[str, Any]],
        seed_files: list[Path],
        event_index_lookup: Mapping[str, int],
        trace_writer: Any,
        simulation_timeout_seconds: int,
        simulation_runner: Callable[..., subprocess.CompletedProcess[str]],
        simulation_failure_error_builder: Callable[..., str],
        config_writer: Callable[[Path, Dict[str, Any]], Path],
        profile_writer: Callable[[Path, list[Dict[str, Any]]], Any],
        evidence_builder: Callable[[Path, Path], str],
        row_builder: Callable[..., Dict[str, Any]],
        exception_formatter: Callable[[BaseException], str],
    ):
        self._router = router
        self._python_exe = python_exe
        self._profiles = profiles
        self._seed_files = seed_files
        self._event_index_lookup = event_index_lookup
        self._trace_writer = trace_writer
        self._simulation_timeout_seconds = simulation_timeout_seconds
        self._simulation_runner = simulation_runner
        self._simulation_failure_error_builder = simulation_failure_error_builder
        self._config_writer = config_writer
        self._profile_writer = profile_writer
        self._evidence_builder = evidence_builder
        self._row_builder = row_builder
        self._exception_formatter = exception_formatter

    def _seed_path_for_event(self, event_id: str) -> Path:
        index = self._event_index_lookup[event_id]
        return self._seed_files[index % len(self._seed_files)]

    def execute(
        self,
        *,
        event: Mapping[str, Any],
        condition: str,
        repeat: int,
        run_id: str,
        unit_dir: Path,
        seed_file: Path,
        config_builder: Callable[..., Dict[str, Any]],
        evaluator: Callable[..., tuple[Dict[str, float], float]],
    ) -> Dict[str, Any]:
        del seed_file
        event_id = str(event["event_id"])
        unit_id = f"{event_id}_{condition}_r{repeat}"
        seed_path = self._seed_path_for_event(event_id)

        self._trace_writer.write(
            {
                "event_id": event_id,
                "condition": condition,
                "repeat": repeat,
                "unit_id": unit_id,
                "status": "starting",
            }
        )

        row_error: str | None = None
        probabilities: Dict[str, float] | None = None
        brier: float | None = None
        simulation_status = "simulation_failed"
        simulation_completed = False
        evaluation_completed = False
        evidence_text = ""

        try:
            config = config_builder(event, condition)
            config["run_unit"] = {
                "run_id": run_id,
                "unit_id": unit_id,
                "seed_file": str(seed_path),
            }
            config_path = self._config_writer(unit_dir, config)
            self._profile_writer(unit_dir, self._profiles)

            simulation_log_path = unit_dir / "simulation.log"
            try:
                completed = self._simulation_runner(
                    self._python_exe,
                    config_path,
                    self._router,
                    log_path=simulation_log_path,
                )
            except subprocess.TimeoutExpired:
                simulation_status = "simulation_failed"
                row_error = self._simulation_failure_error_builder(
                    unit_dir,
                    timeout_seconds=self._simulation_timeout_seconds,
                )
                self._trace_writer.write(
                    {
                        "event_id": event_id,
                        "condition": condition,
                        "repeat": repeat,
                        "unit_id": unit_id,
                        "status": simulation_status,
                        "timeout_seconds": self._simulation_timeout_seconds,
                        "error": row_error,
                    }
                )
            else:
                simulation_completed = completed.returncode == 0
                if not simulation_completed:
                    row_error = self._simulation_failure_error_builder(
                        unit_dir,
                        returncode=completed.returncode,
                    )
                    simulation_status = "simulation_failed"
                    self._trace_writer.write(
                        {
                            "event_id": event_id,
                            "condition": condition,
                            "repeat": repeat,
                            "unit_id": unit_id,
                            "status": simulation_status,
                            "returncode": completed.returncode,
                            "error": row_error,
                        }
                    )
                else:
                    simulation_status = "completed"
                    evidence_text = self._evidence_builder(simulation_log_path, seed_path)
                    try:
                        probabilities, brier = evaluator(event, condition, evidence_text, self._router)
                        evaluation_completed = True
                        self._trace_writer.write(
                            {
                                "event_id": event_id,
                                "condition": condition,
                                "repeat": repeat,
                                "unit_id": unit_id,
                                "status": "completed",
                                "probabilities": probabilities,
                                "brier": brier,
                            }
                        )
                    except Exception as exc:
                        simulation_status = "evaluation_failed"
                        row_error = self._exception_formatter(exc)
                        self._trace_writer.write(
                            {
                                "event_id": event_id,
                                "condition": condition,
                                "repeat": repeat,
                                "unit_id": unit_id,
                                "status": simulation_status,
                                "error": row_error,
                            }
                        )
        except Exception as exc:
            row_error = self._exception_formatter(exc)
            self._trace_writer.write(
                {
                    "event_id": event_id,
                    "condition": condition,
                    "repeat": repeat,
                    "unit_id": unit_id,
                    "status": "failed",
                    "error": row_error,
                }
            )

        return self._row_builder(
            event,
            condition,
            repeat,
            simulation_status=simulation_status,
            simulation_completed=simulation_completed,
            evaluation_completed=evaluation_completed,
            probabilities=probabilities,
            brier=brier,
            error=row_error,
            seed_file=str(seed_path),
            evidence_text=evidence_text or None,
        )


class BenchmarkRunOrchestrator:
    def __init__(self, executor: Any):
        self._executor = executor

    def run(
        self,
        *,
        run_id: str,
        output_root: Path,
        events: list[Mapping[str, Any]],
        repeats: int,
        build_condition_matrix: Callable[[list[Mapping[str, Any]], int], list[Mapping[str, Any]]],
        event_lookup: Mapping[str, Mapping[str, Any]],
        write_summary: Callable[[Path, list[Dict[str, Any]]], Any],
        seed_file: Path | None = None,
        config_builder: Callable[..., Dict[str, Any]] | None = None,
        evaluator: Callable[..., tuple[Dict[str, float], float]] | None = None,
        manifest: Mapping[str, Any] | None = None,
    ) -> Path:
        run_dir = Path(output_root) / run_id
        traces_dir = run_dir / "traces"
        run_dir.mkdir(parents=True, exist_ok=True)
        traces_dir.mkdir(parents=True, exist_ok=True)

        manifest_payload = dict(manifest) if manifest is not None else {"run_id": run_id, "events_loaded": len(events), "repeats": repeats}
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        rows: list[Dict[str, Any]] = []
        trace_path = traces_dir / "execution.jsonl"
        unit_seed_file = seed_file or Path("seed.md")
        row_config_builder = config_builder or (lambda event, condition: {"event_id": event["event_id"], "condition": condition})
        row_evaluator = evaluator or (lambda *_args, **_kwargs: ({"A": 1.0}, 0.0))

        for matrix_row in build_condition_matrix(events, repeats):
            fallback_event_id = str(matrix_row.get("event_id", "unknown_event"))
            fallback_condition = str(matrix_row.get("condition", "unknown_condition"))
            fallback_repeat_raw = matrix_row.get("repeat", 0)
            try:
                fallback_repeat = int(fallback_repeat_raw)
            except Exception:
                fallback_repeat = 0
            fallback_unit_id = f"{fallback_event_id}_{fallback_condition}_r{fallback_repeat}"

            try:
                event = event_lookup[str(matrix_row["event_id"])]
                condition = str(matrix_row["condition"])
                repeat = int(matrix_row["repeat"])
                with trace_path.open("a", encoding="utf-8") as trace_file:
                    trace_file.write(
                        json.dumps(
                            {
                                "event_id": str(event["event_id"]),
                                "condition": condition,
                                "repeat": repeat,
                                "status": "starting",
                            }
                        )
                        + "\n"
                    )
                rows.append(
                    self._executor.execute(
                        event=event,
                        condition=condition,
                        repeat=repeat,
                        run_id=run_id,
                        unit_dir=run_dir / f"{event['event_id']}_{condition}_r{repeat}",
                        seed_file=unit_seed_file,
                        config_builder=row_config_builder,
                        evaluator=row_evaluator,
                    )
                )
                if "unit_id" not in rows[-1]:
                    rows[-1]["unit_id"] = f"{event['event_id']}_{condition}_r{repeat}"
            except Exception as exc:
                rows.append(
                    {
                        "event_id": fallback_event_id,
                        "condition": fallback_condition,
                        "repeat": fallback_repeat,
                        "unit_id": fallback_unit_id,
                        "run_id": run_id,
                        "seed_file": str(unit_seed_file),
                        "simulation_status": "simulation_failed",
                        "evaluation_status": "not_run",
                        "full_simulation_completed": False,
                        "probabilities": None,
                        "brier": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        (run_dir / "event_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        write_summary(run_dir, rows)
        return run_dir
