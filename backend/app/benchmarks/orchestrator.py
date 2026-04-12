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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

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

        config = config_builder(event, condition)
        config_path = unit_dir / "simulation_config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

        completed = self._run_simulation(config_path)
        base_row = {
            "event_id": str(event["event_id"]),
            "condition": condition,
            "repeat": repeat,
            "run_id": run_id,
            "seed_file": str(seed_file),
        }
        if completed.returncode != 0:
            return {
                **base_row,
                "simulation_status": "simulation_failed",
                "evaluation_status": "not_run",
                "full_simulation_completed": False,
                "probabilities": None,
                "brier": None,
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
    ) -> Path:
        run_dir = Path(output_root) / run_id
        traces_dir = run_dir / "traces"
        run_dir.mkdir(parents=True, exist_ok=True)
        traces_dir.mkdir(parents=True, exist_ok=True)

        (run_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "events_loaded": len(events),
                    "repeats": repeats,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        rows: list[Dict[str, Any]] = []
        trace_path = traces_dir / "execution.jsonl"
        unit_seed_file = seed_file or Path("seed.md")
        row_config_builder = config_builder or (lambda event, condition: {"event_id": event["event_id"], "condition": condition})
        row_evaluator = evaluator or (lambda *_args, **_kwargs: ({"A": 1.0}, 0.0))

        for matrix_row in build_condition_matrix(events, repeats):
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

        (run_dir / "event_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        write_summary(run_dir, rows)
        return run_dir
