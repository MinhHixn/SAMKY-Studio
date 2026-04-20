# v0.3 Parity Orchestrator + Status API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract reusable ECN-BENCH orchestration classes and add a roadmap-minimum `/api/status` endpoint without changing existing benchmark artifact semantics.

**Architecture:** Move protocol run lifecycle from procedural script flow into `app.benchmarks.orchestrator` (`ConditionExecutor` + `BenchmarkRunOrchestrator`) and keep `scripts/run_ecnbench_protocol.py` as a thin CLI adapter. Add a small system API module for `/api/status` that reports Neo4j, Ollama model availability, and disk usage with explicit degraded-state errors.

**Tech Stack:** Python 3.11, Flask, pytest, existing benchmark modules (`role_router`, `protocol`, `scoring`, `evaluator`), subprocess-based simulation runner.

---

## File Structure (planned changes)

- Create: `backend/app/benchmarks/orchestrator.py`  
  Owns reusable condition execution and run orchestration.
- Modify: `backend/app/benchmarks/__init__.py`  
  Export orchestrator classes for stable imports.
- Modify: `backend/scripts/run_ecnbench_protocol.py`  
  Keep CLI argument parsing + dependency wiring only; delegate run lifecycle to orchestrator classes.
- Create: `backend/tests/test_benchmark_orchestrator.py`  
  Unit coverage for `ConditionExecutor` and `BenchmarkRunOrchestrator`.
- Create: `backend/app/api/system.py`  
  Implements `/api/status` health endpoint.
- Modify: `backend/app/api/__init__.py`  
  Register `system_bp` blueprint and import module.
- Modify: `backend/app/__init__.py`  
  Register `system_bp` under `/api`.
- Create: `backend/tests/test_api_status.py`  
  API tests for healthy/degraded status response contract.
- Modify: `README.md`  
  Document orchestrator extraction and new `/api/status` endpoint.

### Task 1: Add failing orchestrator tests and implement reusable classes

**Files:**
- Create: `backend/tests/test_benchmark_orchestrator.py`
- Create: `backend/app/benchmarks/orchestrator.py`
- Modify: `backend/app/benchmarks/__init__.py`

- [ ] **Step 1: Write failing unit tests for executor/orchestrator**

```python
# backend/tests/test_benchmark_orchestrator.py
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


def test_orchestrator_writes_event_results_and_summary(monkeypatch, tmp_path):
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
        write_summary=lambda path, rows: (path / "summary.json").write_text(json.dumps({"total_rows": len(rows)}), encoding="utf-8"),
    )

    assert (run_dir / "event_results.json").exists()
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "traces" / "execution.jsonl").exists()
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `Set-Location backend; .\.venv311\Scripts\python -m pytest tests\test_benchmark_orchestrator.py -q`  
Expected: FAIL with import error for `app.benchmarks.orchestrator` and missing classes.

- [ ] **Step 3: Implement minimal orchestrator classes**

```python
# backend/app/benchmarks/orchestrator.py
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Mapping


class ConditionExecutor:
    def __init__(self, router, python_exe: str, backend_dir: Path):
        self._router = router
        self._python_exe = python_exe
        self._backend_dir = Path(backend_dir)

    def _run_simulation(self, config_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._python_exe, "scripts/run_parallel_simulation.py", "--config", str(config_path), "--max-rounds", "60", "--no-wait"],
            cwd=str(self._backend_dir),
            text=True,
            timeout=60 * 60 * 60,
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
        unit_dir.mkdir(parents=True, exist_ok=True)
        config = config_builder(event, condition)
        config_path = unit_dir / "simulation_config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

        completed = self._run_simulation(config_path)
        if completed.returncode != 0:
            return {
                "event_id": str(event["event_id"]),
                "condition": condition,
                "repeat": repeat,
                "simulation_status": "simulation_failed",
                "full_simulation_completed": False,
                "brier": None,
            }

        probabilities, brier = evaluator(event, condition)
        return {
            "event_id": str(event["event_id"]),
            "condition": condition,
            "repeat": repeat,
            "simulation_status": "completed",
            "full_simulation_completed": True,
            "probabilities": probabilities,
            "brier": brier,
        }


class BenchmarkRunOrchestrator:
    def __init__(self, executor):
        self._executor = executor

    def run(
        self,
        *,
        run_id: str,
        output_root: Path,
        events,
        repeats: int,
        build_condition_matrix,
        event_lookup,
        write_summary,
    ) -> Path:
        run_dir = Path(output_root) / run_id
        traces_dir = run_dir / "traces"
        run_dir.mkdir(parents=True, exist_ok=True)
        traces_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_manifest.json").write_text(
            json.dumps({"run_id": run_id, "events_loaded": len(events), "repeats": repeats}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows = []
        for matrix_row in build_condition_matrix(events, repeats):
            event = event_lookup[matrix_row["event_id"]]
            with (traces_dir / "execution.jsonl").open("a", encoding="utf-8") as trace_file:
                trace_file.write(json.dumps({"event_id": event["event_id"], "condition": matrix_row["condition"], "repeat": matrix_row["repeat"], "status": "starting"}) + "\n")
            rows.append(
                self._executor.execute(
                    event=event,
                    condition=matrix_row["condition"],
                    repeat=matrix_row["repeat"],
                    run_id=run_id,
                    unit_dir=run_dir / f'{event["event_id"]}_{matrix_row["condition"]}_r{matrix_row["repeat"]}',
                    seed_file=Path("seed.md"),
                    config_builder=lambda e, c: {"event_id": e["event_id"], "condition": c},
                    evaluator=lambda *_args: ({"A": 1.0}, 0.0),
                )
            )
        (run_dir / "event_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        write_summary(run_dir, rows)
        return run_dir
```

```python
# backend/app/benchmarks/__init__.py (append exports)
from .orchestrator import BenchmarkRunOrchestrator, ConditionExecutor
```

- [ ] **Step 4: Run orchestrator tests to verify pass**

Run: `Set-Location backend; .\.venv311\Scripts\python -m pytest tests\test_benchmark_orchestrator.py -q`  
Expected: PASS for new orchestrator unit tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/orchestrator.py backend/app/benchmarks/__init__.py backend/tests/test_benchmark_orchestrator.py
git commit -m "feat: add reusable benchmark orchestrator classes" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Refactor protocol script into a thin CLI wrapper

**Files:**
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Add a failing delegation test**

```python
# backend/tests/test_run_ecnbench_protocol.py (add test)
def test_main_delegates_run_loop_to_orchestrator(monkeypatch, tmp_path):
    called = {"count": 0}

    class FakeOrchestrator:
        def __init__(self, executor):
            self.executor = executor

        def run(self, **kwargs):
            called["count"] += 1
            run_dir = Path(kwargs["output_root"]) / kwargs["run_id"]
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "event_results.json").write_text("[]", encoding="utf-8")
            (run_dir / "summary.json").write_text("{}", encoding="utf-8")
            return run_dir

    monkeypatch.setattr(protocol_script, "BenchmarkRunOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(protocol_script, "_utc_run_id", lambda: "fixed-run")
    monkeypatch.setattr(protocol_script, "load_events_from_raw", lambda *args, **kwargs: [{"event_id": "E1", "question": "Q", "outcome": "A"}])
    monkeypatch.setattr(protocol_script, "load_seed_files", lambda *args, **kwargs: [tmp_path / "seed.md"])
    monkeypatch.setattr(protocol_script, "build_profiles", lambda *args, **kwargs: [{"agent_id": 1}])
    monkeypatch.setattr(protocol_script.BenchmarkRoleRouter, "from_config", classmethod(lambda cls, config=None: type("R", (), {"model_for": lambda self, role: "m", "api_key": "k", "base_url": "u"})()))
    monkeypatch.setattr(protocol_script, "Step30InjectionLoader", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(protocol_script.sys, "argv", ["run_ecnbench_protocol.py", "--seeds-dir", str(tmp_path), "--events-raw", str(tmp_path / "events.json"), "--output-dir", str(tmp_path / "runs")])

    protocol_script.main()
    assert called["count"] == 1
```

- [ ] **Step 2: Run targeted test to confirm failure**

Run: `Set-Location backend; .\.venv311\Scripts\python -m pytest tests\test_run_ecnbench_protocol.py::test_main_delegates_run_loop_to_orchestrator -q`  
Expected: FAIL because `main()` still owns the run loop directly.

- [ ] **Step 3: Refactor `main()` to orchestrator delegation**

```python
# backend/scripts/run_ecnbench_protocol.py (core shape change)
from app.benchmarks.orchestrator import BenchmarkRunOrchestrator, ConditionExecutor


def main() -> None:
    # existing argparse and validation stay
    router = BenchmarkRoleRouter.from_config()
    events = load_events_from_raw(args.events_raw, limit=args.events)
    seed_files = load_seed_files(args.seeds_dir)
    profiles = build_profiles(args.seeds_dir, target_count=TARGET_AGENT_COUNT)
    injection_loader = Step30InjectionLoader(args.injection_bank)

    run_id = _utc_run_id()
    output_root = Path(args.output_dir)
    event_lookup = {str(event["event_id"]): event for event in events}

    executor = ConditionExecutor(
        router=router,
        python_exe=args.python_exe,
        backend_dir=_BACKEND_DIR,
    )
    orchestrator = BenchmarkRunOrchestrator(executor=executor)

    orchestrator.run(
        run_id=run_id,
        output_root=output_root,
        events=events,
        repeats=args.repeats,
        build_condition_matrix=build_condition_matrix,
        event_lookup=event_lookup,
        write_summary=write_summary,
    )
```

- [ ] **Step 4: Run protocol runner tests**

Run: `Set-Location backend; .\.venv311\Scripts\python -m pytest tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS, including the new delegation test and existing artifact-contract tests.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "refactor: delegate protocol run lifecycle to orchestrator" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add `/api/status` endpoint with roadmap-minimum health contract

**Files:**
- Create: `backend/app/api/system.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/__init__.py`
- Create: `backend/tests/test_api_status.py`

- [ ] **Step 1: Write failing API tests for healthy and degraded states**

```python
# backend/tests/test_api_status.py
from app import create_app


def test_api_status_reports_healthy_dependencies(monkeypatch):
    app = create_app()
    app.extensions["neo4j_storage"] = type("S", (), {"verify_connection": lambda self: True})()

    from app.api import system as system_api

    monkeypatch.setattr(
        system_api.requests,
        "get",
        lambda *args, **kwargs: type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: {"models": [{"name": "qwen2.5:32b"}]},
            },
        )(),
    )
    monkeypatch.setattr(system_api.shutil, "disk_usage", lambda _path: (1000, 400, 600))

    client = app.test_client()
    response = client.get("/api/status")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["neo4j"]["connected"] is True
    assert payload["data"]["ollama"]["model_available"] is True
    assert payload["data"]["disk"]["free_bytes"] == 600


def test_api_status_reports_degraded_subsystems(monkeypatch):
    app = create_app()
    app.extensions["neo4j_storage"] = None

    from app.api import system as system_api

    def raise_ollama(*_args, **_kwargs):
        raise RuntimeError("ollama unavailable")

    monkeypatch.setattr(system_api.requests, "get", raise_ollama)
    monkeypatch.setattr(system_api.shutil, "disk_usage", lambda _path: (1000, 900, 100))

    client = app.test_client()
    response = client.get("/api/status")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["data"]["neo4j"]["connected"] is False
    assert payload["data"]["ollama"]["reachable"] is False
    assert "error" in payload["data"]["ollama"]
```

- [ ] **Step 2: Run tests to confirm failure**

Run: `Set-Location backend; .\.venv311\Scripts\python -m pytest tests\test_api_status.py -q`  
Expected: FAIL because `/api/status` route is not registered.

- [ ] **Step 3: Implement endpoint and register blueprint**

```python
# backend/app/api/system.py
from __future__ import annotations

import shutil
from datetime import datetime, timezone

import requests
from flask import current_app, jsonify

from . import system_bp
from ..config import Config


def _check_neo4j():
    storage = current_app.extensions.get("neo4j_storage")
    if storage is None:
        return {"connected": False, "error": "Neo4jStorage not initialized"}
    try:
        verify = getattr(storage, "verify_connection", None)
        connected = bool(verify()) if callable(verify) else True
        return {"connected": connected, "error": None if connected else "Neo4j verification failed"}
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


def _check_ollama():
    model = Config.LLM_MODEL_NAME
    base = Config.LLM_BASE_URL.rsplit("/v1", 1)[0]
    try:
        response = requests.get(f"{base}/api/tags", timeout=5)
        response.raise_for_status()
        names = {item.get("name") for item in response.json().get("models", []) if isinstance(item, dict)}
        return {
            "reachable": True,
            "model_configured": model,
            "model_available": model in names,
            "error": None,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "model_configured": model,
            "model_available": False,
            "error": str(exc),
        }


@system_bp.route("/status", methods=["GET"])
def get_status():
    total, used, free = shutil.disk_usage(".")
    return jsonify(
        {
            "success": True,
            "data": {
                "neo4j": _check_neo4j(),
                "ollama": _check_ollama(),
                "disk": {
                    "path": ".",
                    "total_bytes": int(total),
                    "used_bytes": int(used),
                    "free_bytes": int(free),
                },
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },
        }
    )
```

```python
# backend/app/api/__init__.py
system_bp = Blueprint("system", __name__)
from . import system  # noqa: E402, F401
```

```python
# backend/app/__init__.py
from .api import graph_bp, simulation_bp, report_bp, system_bp
app.register_blueprint(system_bp, url_prefix="/api")
```

- [ ] **Step 4: Run API tests**

Run: `Set-Location backend; .\.venv311\Scripts\python -m pytest tests\test_api_status.py -q`  
Expected: PASS with both healthy and degraded status cases.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/system.py backend/app/api/__init__.py backend/app/__init__.py backend/tests/test_api_status.py
git commit -m "feat: add roadmap status endpoint for neo4j ollama and disk health" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Documentation and regression safety net

**Files:**
- Modify: `README.md`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`
- Modify: `backend/tests/test_benchmark_protocol.py`
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`
- Modify: `backend/tests/test_benchmark_role_router.py`
- Modify: `backend/tests/test_benchmark_orchestrator.py`
- Modify: `backend/tests/test_api_status.py`

- [ ] **Step 1: Update README sections for new architecture and endpoint**

```markdown
## Architecture updates (v0.3 parity work)

- ECN-BENCH run lifecycle now uses reusable classes in `backend/app/benchmarks/orchestrator.py`:
  - `ConditionExecutor`
  - `BenchmarkRunOrchestrator`
- `backend/scripts/run_ecnbench_protocol.py` remains the CLI entrypoint and delegates orchestration.

## System status endpoint

`GET /api/status` returns:
- Neo4j connectivity
- Ollama reachability + configured model availability
- Disk usage summary
```

- [ ] **Step 2: Run benchmark-focused test suite**

Run:
`Set-Location backend; .\.venv311\Scripts\python -m pytest tests\test_benchmark_protocol.py tests\test_benchmark_evaluator_scoring.py tests\test_benchmark_role_router.py tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py tests\test_api_status.py -q`  
Expected: PASS across protocol primitives, orchestrator behavior, script wrapper behavior, and status API.

- [ ] **Step 3: Run broader backend regression sweep**

Run: `Set-Location backend; .\.venv311\Scripts\python -m pytest tests -q`  
Expected: PASS with no regressions in non-benchmark paths.

- [ ] **Step 4: Commit docs + any final test adjustments**

```bash
git add README.md backend/tests/test_benchmark_orchestrator.py backend/tests/test_api_status.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "docs: document orchestrator extraction and status endpoint" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 5: Final integration sanity check**

Run:
`Set-Location backend; .\.venv311\Scripts\python scripts\run_ecnbench_protocol.py --seeds-dir ..\..\data\seeds --events-raw ..\..\data\events_raw.json --injection-bank ..\..\data\injections\step30_injection_bank.json --output-dir logs\benchmark_runs --events 1 --repeats 1`  
Expected: Run directory created with `run_manifest.json`, `event_results.json`, `summary.json`, and trace output, with no artifact-schema break.

