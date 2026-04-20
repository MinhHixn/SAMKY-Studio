# A/B/C Workflow Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Continue the benchmark implementation with the current A/B/C-per-event workflow, while adding traceability guardrails that prove one benchmark model per run and separated per-unit execution for event-condition pairs.

**Architecture:** Keep `run_ecnbench_protocol.py` as the CLI entrypoint and keep orchestration in `app.benchmarks.orchestrator`. Add small, backward-compatible metadata to manifest/result rows and tighten tests so the workflow contract is explicit and regression-resistant.

**Tech Stack:** Python 3.11, Flask backend, pytest, existing benchmark modules (`role_router`, `protocol`, `orchestrator`, scoring).

---

## File Structure (planned changes)

- Modify: `backend/scripts/run_ecnbench_protocol.py`  
  Add manifest-level continuation metadata proving single benchmark model and expected A/B/C unit count.
- Modify: `backend/app/benchmarks/orchestrator.py`  
  Add explicit `unit_id` to per-unit result rows for clearer per-event-condition separation.
- Modify: `backend/tests/test_run_ecnbench_protocol.py`  
  Add/adjust tests for new manifest metadata and A/B/C expected-unit count.
- Modify: `backend/tests/test_benchmark_orchestrator.py`  
  Add tests verifying `unit_id` in result rows and fallback rows.
- Modify: `README.md`  
  Document new metadata fields and reaffirm A/B/C-per-event continuation behavior.

### Task 1: Manifest invariants for A/B/C continuation

**Files:**
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing test for manifest continuation metadata**

```python
def test_main_manifest_includes_continuation_metadata(monkeypatch, tmp_path):
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

    manifest = json.loads((output_dir / "fixed-run" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["workflow_mode"] == "abc-per-event"
    assert manifest["benchmark_model"] == "openrouter/benchmark-model"
    assert manifest["expected_run_units"] == 3  # 1 event x 3 conditions x repeats=1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py::test_main_manifest_includes_continuation_metadata -q`  
Expected: FAIL with missing keys (`workflow_mode`, `benchmark_model`, `expected_run_units`).

- [ ] **Step 3: Implement minimal manifest metadata**

```python
# backend/scripts/run_ecnbench_protocol.py (inside main(), when building manifest)
benchmark_model = router.model_for("benchmark")
expected_run_units = len(events) * len(CONDITIONS) * args.repeats

manifest = {
    # existing keys...
    "workflow_mode": "abc-per-event",
    "benchmark_model": benchmark_model,
    "expected_run_units": expected_run_units,
}
```

- [ ] **Step 4: Run focused protocol tests**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: add A/B/C continuation metadata to benchmark manifest" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Explicit per-unit row identity (`unit_id`)

**Files:**
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/app/benchmarks/orchestrator.py`
- Modify: `backend/tests/test_benchmark_orchestrator.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Add failing tests for `unit_id` in result rows**

```python
def test_condition_executor_includes_unit_id(monkeypatch, tmp_path):
    class FakeRouter:
        def model_for(self, role):
            return "openrouter/benchmark-model"

    executor = ConditionExecutor(router=FakeRouter(), python_exe="python", backend_dir=tmp_path)
    monkeypatch.setattr(
        executor,
        "_run_simulation",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(args=["python"], returncode=0, stdout="ok", stderr=""),
    )

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]},
        condition="B",
        repeat=2,
        run_id="run-1",
        unit_dir=tmp_path / "E1_B_r2",
        seed_file=tmp_path / "seed.md",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_args, **_kwargs: ({"A": 1.0}, 0.0),
    )

    assert row["unit_id"] == "E1_B_r2"
```

```python
def test_main_event_results_include_unit_id(monkeypatch, tmp_path):
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

    rows = json.loads((output_dir / "fixed-run" / "event_results.json").read_text(encoding="utf-8"))
    assert rows[0]["unit_id"] == "E1_A_r1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_orchestrator.py::test_condition_executor_includes_unit_id tests\test_run_ecnbench_protocol.py::test_main_event_results_include_unit_id -q`  
Expected: FAIL due missing `unit_id`.

- [ ] **Step 3: Implement `unit_id` in row builders/executors**

```python
# backend/scripts/run_ecnbench_protocol.py
def build_event_result_row(...):
    unit_id = f"{event['event_id']}_{condition}_r{repeat}"
    return {
        "unit_id": unit_id,
        # existing keys...
    }
```

```python
# backend/app/benchmarks/orchestrator.py (ConditionExecutor.execute)
unit_id = f"{event['event_id']}_{condition}_r{repeat}"
base_row = {
    "unit_id": unit_id,
    # existing keys...
}
```

```python
# backend/app/benchmarks/orchestrator.py (fallback row in BenchmarkRunOrchestrator.run)
"unit_id": f"{fallback_event_id}_{fallback_condition}_r{fallback_repeat}",
```

- [ ] **Step 4: Run benchmark protocol + orchestrator tests**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/app/benchmarks/orchestrator.py backend/tests/test_benchmark_orchestrator.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: add explicit unit_id to benchmark result rows" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Documentation + regression gate update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add docs for continuation metadata and per-unit identity**

```markdown
## ECN-BENCH continuation invariants

- Workflow mode remains A/B/C per event (`workflow_mode: "abc-per-event"`).
- `run_manifest.json` records:
  - `benchmark_model`
  - `expected_run_units` (`events_loaded * 3 * repeats`)
- `event_results.json` includes `unit_id` (`<event_id>_<condition>_r<repeat>`), making each unit explicit and traceable.
```

- [ ] **Step 2: Run benchmark-focused regression gate**

Run:  
`Set-Location backend; python -m pytest tests\test_benchmark_protocol.py tests\test_benchmark_evaluator_scoring.py tests\test_benchmark_role_router.py tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py tests\test_api_status.py -q`  
Expected: PASS.

- [ ] **Step 3: Run end-to-end sanity command (1 event, A/B/C workflow intact)**

Run:  
`Set-Location backend; python scripts\run_ecnbench_protocol.py --seeds-dir ..\..\data\seeds --events-raw ..\..\data\events_raw.json --injection-bank ..\..\data\injections\step30_injection_bank.json --output-dir logs\benchmark_runs --events 1 --repeats 1`  
Expected: exit code 0 and output artifacts present under `logs\benchmark_runs\<run_id>\`.

- [ ] **Step 4: Commit docs update**

```bash
git add README.md
git commit -m "docs: document A/B/C continuation invariants and unit identity" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 5: Optional broader suite (environment permitting)**

Run: `Set-Location backend; python -m pytest tests -q`  
Expected: PASS when optional external dependencies are installed; if blocked, record blocker in PR notes.

