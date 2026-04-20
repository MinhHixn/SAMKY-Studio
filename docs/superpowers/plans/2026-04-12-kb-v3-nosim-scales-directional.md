# KB v3 No-Sim + Canonical Scales + Directional Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align ECN-BENCH runtime and scoring with KB v3 requirements by making Condition A truly no-simulation, making validated scales deterministic/canonical, and surfacing directional accuracy in run summaries.

**Architecture:** Keep the current orchestrator/protocol pipeline and add focused hardening in-place. Condition A takes a dedicated no-subprocess branch but still uses the same evaluator call path as B/C. Canonical validated scales are computed from normalized MCQ dimensions with fixed weights and validated consistently across evaluator, orchestrator, and scoring.

**Tech Stack:** Python 3.11, Flask backend modules, pytest, ECN benchmark runner (`run_ecnbench_protocol.py`), benchmark evaluator/scoring/orchestrator modules.

---

## File Structure (planned changes)

- Modify: `backend/app/benchmarks/orchestrator.py`  
  Add true no-sim execution path for Condition A and keep strict lifecycle semantics with additive `simulation_executed` metadata.
- Modify: `backend/scripts/run_ecnbench_protocol.py`  
  Persist `simulation_executed` and directional row signal; wire directional summary output.
- Modify: `backend/app/benchmarks/evaluator.py`  
  Add deterministic canonical validated scales computation (fixed key set + fixed formulas + fixed weights).
- Modify: `backend/app/benchmarks/scoring.py`  
  Add directional summary helper and tighten rubric/scale validity checks for summary inclusion.
- Modify: `backend/tests/test_benchmark_orchestrator.py`  
  Add no-sim A behavior tests and strict payload validation tests.
- Modify: `backend/tests/test_run_ecnbench_protocol.py`  
  Add row/summary tests for `simulation_executed` and directional accuracy.
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`  
  Add deterministic canonical scale formula/key/range tests and directional-summary tests.
- Modify: `README.md`  
  Document no-sim A runtime, canonical validated scales, and directional summary outputs.

### Task 1: Make Condition A a true No-Sim baseline (TDD)

**Files:**
- Modify: `backend/app/benchmarks/orchestrator.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_benchmark_orchestrator.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing tests for no-sim A behavior**

```python
# backend/tests/test_benchmark_orchestrator.py (append)
def test_protocol_executor_condition_a_skips_simulation_subprocess(tmp_path):
    simulation_calls = {"count": 0}

    def fake_runner(*_args, **_kwargs):
        simulation_calls["count"] += 1
        raise AssertionError("Condition A must not invoke simulation runner")

    executor, _trace_entries = _build_protocol_executor(tmp_path)
    executor._simulation_runner = fake_runner

    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "YES", "answer": "YES"},
        condition="A",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "unit",
        seed_file=tmp_path / "seed.txt",
        config_builder=lambda *_: {"event_id": "E1", "event_config": {"initial_posts": []}, "agent_configs": []},
        evaluator=lambda *_: {
            "probabilities": {"YES": 0.8, "NO": 0.2},
            "brier": 0.12,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": _valid_validated_scales(),
        },
    )

    assert simulation_calls["count"] == 0
    assert row["simulation_executed"] is False
    assert row["simulation_status"] == "completed"
    assert row["full_simulation_completed"] is True
```

```python
# backend/tests/test_run_ecnbench_protocol.py (append)
def test_build_event_result_row_includes_simulation_executed_flag():
    row = protocol_script.build_event_result_row(
        {"event_id": "E1", "question": "Q", "outcome": "YES", "options": ["YES", "NO"]},
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"YES": 0.8, "NO": 0.2},
        brier=0.12,
        mcq_dimensions={"prediction_accuracy": {"very_low": 0.0, "low": 0.0, "high": 0.2, "very_high": 0.8}},
        validated_scales={"schema_version": "v1", "scores": {"prediction_accuracy_score": 0.9}},
        simulation_executed=False,
    )
    assert row["simulation_executed"] is False
```

- [ ] **Step 2: Run targeted tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_orchestrator.py::test_protocol_executor_condition_a_skips_simulation_subprocess tests\test_run_ecnbench_protocol.py::test_build_event_result_row_includes_simulation_executed_flag -q`  
Expected: FAIL (A still invokes subprocess and/or row missing `simulation_executed`).

- [ ] **Step 3: Implement no-sim A execution branch and additive row field**

```python
# backend/app/benchmarks/orchestrator.py (inside ProtocolConditionExecutor.execute)
simulation_executed = condition != "A"
simulation_log_path = unit_dir / "simulation.log"

if simulation_executed:
    completed = self._simulation_runner(
        self._python_exe,
        config_path,
        self._router,
        log_path=simulation_log_path,
    )
    # existing returncode/timeout handling stays here
    simulation_completed = completed.returncode == 0
else:
    simulation_status = "completed"
    simulation_completed = True

if simulation_completed:
    evidence_text = self._evidence_builder(simulation_log_path, seed_path)
    # existing evaluator try/except continues unchanged
```

```python
# backend/scripts/run_ecnbench_protocol.py (build_event_result_row signature and payload)
def build_event_result_row(
    ...,
    simulation_executed: bool | None = None,
    ...
) -> Dict[str, Any]:
    ...
    return {
        ...
        "simulation_executed": bool(simulation_executed) if simulation_executed is not None else None,
        ...
    }
```

```python
# backend/app/benchmarks/orchestrator.py (row_builder call)
return self._row_builder(
    ...,
    simulation_executed=simulation_executed,
    ...
)
```

- [ ] **Step 4: Run focused suites**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/orchestrator.py backend/scripts/run_ecnbench_protocol.py backend/tests/test_benchmark_orchestrator.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: make condition A a true no-simulation baseline" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Make validated scales canonical and deterministic (TDD)

**Files:**
- Modify: `backend/app/benchmarks/evaluator.py`
- Modify: `backend/app/benchmarks/orchestrator.py`
- Modify: `backend/app/benchmarks/scoring.py`
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`
- Modify: `backend/tests/test_benchmark_orchestrator.py`

- [ ] **Step 1: Add failing tests for canonical scales and weighted rubric**

```python
# backend/tests/test_benchmark_evaluator_scoring.py (append)
def test_probability_evaluator_computes_canonical_validated_scales():
    class FakeClient:
        def chat_json(self, *_args, **_kwargs):
            return {
                "probabilities": {"YES": 0.7, "NO": 0.3},
                "mcq_dimensions": {
                    "prediction_accuracy": {"very_low": 0, "low": 0, "high": 0, "very_high": 1},
                    "polarization": {"very_low": 1, "low": 0, "high": 0, "very_high": 0},
                    "herd_effect": {"very_low": 0, "low": 1, "high": 0, "very_high": 0},
                    "deliberation_quality": {"very_low": 0, "low": 0, "high": 1, "very_high": 0},
                    "susceptibility": {"very_low": 0, "low": 0, "high": 0, "very_high": 1},
                    "convergence": {"very_low": 0.5, "low": 0.5, "high": 0, "very_high": 0},
                    "information_diversity": {"very_low": 0, "low": 0, "high": 0.5, "very_high": 0.5},
                },
                "validated_scales": {"schema_version": "v1", "scores": {"free_form": 123}},
            }

    class FakeRouter:
        def client_for(self, _role):
            return FakeClient()

    result = ProbabilityEvaluator(FakeRouter()).evaluate("Q", "A", "seed-only")
    scores = result["validated_scales"]["scores"]
    assert set(scores.keys()) == set(CANONICAL_VALIDATED_SCALE_KEYS)
    assert scores["prediction_accuracy_score"] == pytest.approx(1.0)
    assert 0.0 <= scores["weighted_rubric_score"] <= 1.0
```

```python
# backend/tests/test_benchmark_orchestrator.py (append)
def test_protocol_executor_rejects_non_canonical_validated_scale_keys(tmp_path):
    executor, _trace_entries = _build_protocol_executor(tmp_path)
    row = executor.execute(
        event={"event_id": "E1", "question": "Q", "outcome": "YES", "answer": "YES"},
        condition="B",
        repeat=1,
        run_id="r1",
        unit_dir=tmp_path / "unit",
        seed_file=tmp_path / "seed.txt",
        config_builder=lambda *_args, **_kwargs: {"event_id": "E1"},
        evaluator=lambda *_: {
            "probabilities": {"YES": 0.7, "NO": 0.3},
            "brier": 0.2,
            "mcq_dimensions": _valid_mcq_dimensions(),
            "validated_scales": {"schema_version": "v1", "scores": {"wrong_key": 0.5}},
        },
    )
    assert row["simulation_status"] == "evaluation_failed"
```

- [ ] **Step 2: Run targeted tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py::test_probability_evaluator_computes_canonical_validated_scales tests\test_benchmark_orchestrator.py::test_protocol_executor_rejects_non_canonical_validated_scale_keys -q`  
Expected: FAIL.

- [ ] **Step 3: Implement canonical scales + strict cross-layer validation**

```python
# backend/app/benchmarks/evaluator.py (add constants)
MCQ_BUCKET_SCORE_ANCHORS = {"very_low": 0.0, "low": 1.0 / 3.0, "high": 2.0 / 3.0, "very_high": 1.0}
MCQ_DIMENSION_WEIGHTS = {
    "prediction_accuracy": 0.25,
    "polarization": 0.125,
    "herd_effect": 0.125,
    "deliberation_quality": 0.125,
    "susceptibility": 0.125,
    "convergence": 0.125,
    "information_diversity": 0.125,
}
CANONICAL_VALIDATED_SCALE_KEYS = (
    "prediction_accuracy_score",
    "polarization_score",
    "herd_effect_score",
    "deliberation_quality_score",
    "susceptibility_score",
    "convergence_score",
    "information_diversity_score",
    "weighted_rubric_score",
)
```

```python
# backend/app/benchmarks/evaluator.py (new helper)
def _compute_canonical_validated_scales(mcq_dimensions: Mapping[str, Mapping[str, float]]) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for dimension in MCQ_DIMENSION_KEYS:
        buckets = mcq_dimensions[dimension]
        value = sum(float(buckets[bucket]) * MCQ_BUCKET_SCORE_ANCHORS[bucket] for bucket in MCQ_BUCKET_KEYS)
        scores[f"{dimension}_score"] = round(value, 6)
    weighted = sum(scores[f"{dimension}_score"] * MCQ_DIMENSION_WEIGHTS[dimension] for dimension in MCQ_DIMENSION_KEYS)
    scores["weighted_rubric_score"] = round(weighted, 6)
    return scores
```

```python
# backend/app/benchmarks/evaluator.py (normalize validated scales)
def _normalize_validated_scales(self, validated_scales: Any, mcq_dimensions: Mapping[str, Mapping[str, float]]) -> Dict[str, Any]:
    if not isinstance(validated_scales, Mapping):
        raise ValueError("Evaluator response must include validated_scales mapping")
    schema_version = validated_scales.get("schema_version")
    if schema_version != VALIDATED_SCALES_SCHEMA_VERSION:
        raise ValueError(f"validated_scales.schema_version must be {VALIDATED_SCALES_SCHEMA_VERSION!r}")
    scores = _compute_canonical_validated_scales(mcq_dimensions)
    return {"schema_version": VALIDATED_SCALES_SCHEMA_VERSION, "scores": scores}
```

```python
# backend/app/benchmarks/orchestrator.py and backend/app/benchmarks/scoring.py
# tighten validated scales checks:
# - exact key set == CANONICAL_VALIDATED_SCALE_KEYS
# - all scores finite numeric in [0, 1]
```

- [ ] **Step 4: Run relevant suites**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py tests\test_benchmark_orchestrator.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/evaluator.py backend/app/benchmarks/orchestrator.py backend/app/benchmarks/scoring.py backend/tests/test_benchmark_evaluator_scoring.py backend/tests/test_benchmark_orchestrator.py
git commit -m "feat: compute canonical validated scales from rubric dimensions" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add directional accuracy headline metric (TDD)

**Files:**
- Modify: `backend/app/benchmarks/scoring.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Add failing tests for directional summary**

```python
# backend/tests/test_benchmark_evaluator_scoring.py (append)
def test_summarize_directional_accuracy_by_condition_and_delta():
    rows = [
        {"full_simulation_completed": True, "condition": "A", "directional_correct": 1},
        {"full_simulation_completed": True, "condition": "A", "directional_correct": 0},
        {"full_simulation_completed": True, "condition": "B", "directional_correct": 1},
        {"full_simulation_completed": True, "condition": "C", "directional_correct": 1},
    ]
    summary = summarize_directional_accuracy(rows)
    assert summary["overall"] == pytest.approx(0.75)
    assert summary["by_condition"]["A"] == pytest.approx(0.5)
    assert summary["by_condition"]["B"] == pytest.approx(1.0)
    assert summary["delta"]["A_to_B"] == pytest.approx(0.5)
```

```python
# backend/tests/test_run_ecnbench_protocol.py (append)
def test_summarize_event_results_includes_directional_accuracy_block():
    rows = [
        {"condition": "A", "brier": 0.3, "full_simulation_completed": True, "directional_correct": 0, "simulation_status": "completed"},
        {"condition": "B", "brier": 0.2, "full_simulation_completed": True, "directional_correct": 1, "simulation_status": "completed"},
        {"condition": "C", "brier": 0.4, "full_simulation_completed": True, "directional_correct": 1, "simulation_status": "completed"},
    ]
    summary = protocol_script.summarize_event_results(rows)
    assert "directional_accuracy" in summary
    assert summary["directional_accuracy"]["delta"]["A_to_B"] == pytest.approx(1.0)
```

- [ ] **Step 2: Run targeted tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py::test_summarize_directional_accuracy_by_condition_and_delta tests\test_run_ecnbench_protocol.py::test_summarize_event_results_includes_directional_accuracy_block -q`  
Expected: FAIL.

- [ ] **Step 3: Implement row-level directional signal + summary helper**

```python
# backend/scripts/run_ecnbench_protocol.py (inside build_event_result_row)
ground_truth = event.get("outcome") or event.get("answer", "")
directional_correct: int | None = None
if isinstance(probabilities, Mapping) and isinstance(ground_truth, str) and ground_truth:
    predicted_label = max(
        ((str(label), float(value)) for label, value in probabilities.items()),
        key=lambda item: (item[1], item[0]),
    )[0]
    directional_correct = int(predicted_label == ground_truth)

return {
    ...,
    "directional_correct": directional_correct,
}
```

```python
# backend/app/benchmarks/scoring.py
def summarize_directional_accuracy(rows: List[Dict]) -> Dict:
    completed = [row for row in rows if row.get("full_simulation_completed") and row.get("directional_correct") in (0, 1)]
    by_condition: Dict[str, float] = {}
    for condition in ("A", "B", "C"):
        values = [int(row["directional_correct"]) for row in completed if row.get("condition") == condition]
        by_condition[condition] = round(sum(values) / len(values), 6) if values else 0.0
    overall_values = [int(row["directional_correct"]) for row in completed]
    overall = round(sum(overall_values) / len(overall_values), 6) if overall_values else 0.0
    return {
        "overall": overall,
        "by_condition": by_condition,
        "delta": {
            "A_to_B": round(by_condition["B"] - by_condition["A"], 6),
            "A_to_C": round(by_condition["C"] - by_condition["A"], 6),
            "B_to_C": round(by_condition["C"] - by_condition["B"], 6),
        },
    }
```

```python
# backend/scripts/run_ecnbench_protocol.py (imports + summary wiring)
from app.benchmarks.scoring import (
    brier_score,
    summarize_condition_scores,
    summarize_directional_accuracy,
    summarize_rubric_artifacts,
)

summary["directional_accuracy"] = summarize_directional_accuracy(rows)
```

- [ ] **Step 4: Run relevant suites**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/scoring.py backend/scripts/run_ecnbench_protocol.py backend/tests/test_benchmark_evaluator_scoring.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: add directional accuracy headline metric to benchmark summary" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Documentation + benchmark regression gate

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README benchmark contract section**

```markdown
## ECN-BENCH evaluation contract (KB v3 alignment)

- Condition A is now a true No-Sim baseline (no simulation subprocess).
- Evaluator rubric output remains strict (7 dimensions × 4 buckets).
- `validated_scales` is deterministic and canonical (fixed key set, fixed formulas, fixed weights).
- Summary outputs include:
  - existing Brier condition means + lift deltas
  - additive `directional_accuracy` (overall, by_condition, delta)
```

- [ ] **Step 2: Run benchmark-focused regression**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_protocol.py tests\test_benchmark_evaluator_scoring.py tests\test_benchmark_role_router.py tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py tests\test_api_status.py -q`  
Expected: PASS.

- [ ] **Step 3: Run protocol sanity command**

Run: `Set-Location backend; python scripts\run_ecnbench_protocol.py --seeds-dir C:\Users\TPGHien\Desktop\Claw-4-FUN\data\seeds --events-raw C:\Users\TPGHien\Desktop\Claw-4-FUN\data\events_raw.json --injection-bank C:\Users\TPGHien\Desktop\Claw-4-FUN\data\injections\step30_injection_bank.json --output-dir logs\benchmark_runs --events 1 --repeats 1`  
Expected: run directory produced with `run_manifest.json`, `event_results.json`, `summary.json` (or explicit env blocker for missing router credentials).

- [ ] **Step 4: Commit docs**

```bash
git add README.md
git commit -m "docs: document no-sim baseline and directional summary outputs" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 5: Optional full suite**

Run: `Set-Location backend; python -m pytest tests -q`  
Expected: PASS, or explicit dependency blocker captured if environment lacks optional packages.

