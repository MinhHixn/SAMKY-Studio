# Rubric Evaluator Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict 7-dimension ECN-BENCH rubric contract and validated-scale persistence without breaking the current probability→Brier/lift pipeline.

**Architecture:** Keep the current MVP scoring surface as-is, and add a parallel rubric surface in evaluator output (`mcq_dimensions`, `validated_scales`). Propagate rubric artifacts to per-unit result rows and add parity/contract checks that fail units as `evaluation_failed` when rubric schema is invalid. Weighted multi-dimension aggregation is intentionally deferred.

**Tech Stack:** Python 3.11, Flask backend, pytest, ECN benchmark modules (`evaluator.py`, `scoring.py`, `run_ecnbench_protocol.py`).

---

## File Structure (planned changes)

- Modify: `backend/app/benchmarks/evaluator.py`  
  Add strict rubric schema constants and normalization/validation for `mcq_dimensions` and `validated_scales`.
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`  
  Extend evaluator tests for strict rubric and validated scales contract.
- Modify: `backend/scripts/run_ecnbench_protocol.py`  
  Persist rubric artifacts in event rows and enforce evaluation contract handling.
- Modify: `backend/app/benchmarks/orchestrator.py`  
  Support evaluator return payload carrying rubric artifacts (while preserving backward compatibility).
- Modify: `backend/app/benchmarks/scoring.py`  
  Add additive rubric summary helper (no weighted aggregate scoring).
- Modify: `backend/tests/test_run_ecnbench_protocol.py`  
  Assert per-row rubric fields and compatibility behavior.
- Modify: `README.md`  
  Document additive rubric contract and deferred weighted aggregation.

### Task 1: Implement strict evaluator rubric contract (TDD)

**Files:**
- Modify: `backend/app/benchmarks/evaluator.py`
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`

- [ ] **Step 1: Add failing evaluator tests for rubric and validated scales**

```python
# backend/tests/test_benchmark_evaluator_scoring.py (append tests)
def test_probability_evaluator_returns_normalized_rubric_and_validated_scales():
    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096):
            return {
                "probabilities": {"A": 2, "B": 3, "C": 5},
                "mcq_dimensions": {
                    "prediction_accuracy": {"very_low": 1, "low": 1, "high": 1, "very_high": 1},
                    "polarization": {"very_low": 1, "low": 1, "high": 1, "very_high": 1},
                    "herd_effect": {"very_low": 1, "low": 1, "high": 1, "very_high": 1},
                    "deliberation_quality": {"very_low": 1, "low": 1, "high": 1, "very_high": 1},
                    "susceptibility": {"very_low": 1, "low": 1, "high": 1, "very_high": 1},
                    "convergence": {"very_low": 1, "low": 1, "high": 1, "very_high": 1},
                    "information_diversity": {"very_low": 1, "low": 1, "high": 1, "very_high": 1},
                },
                "validated_scales": {
                    "schema_version": "v1",
                    "scores": {"calibration_consistency": 0.7, "evidence_alignment": 0.8},
                },
            }

    class FakeRouter:
        def client_for(self, role):
            assert role == "evaluator"
            return FakeClient()

    result = ProbabilityEvaluator(FakeRouter()).evaluate("Q", "A", "E")
    assert set(result["mcq_dimensions"].keys()) == {
        "prediction_accuracy",
        "polarization",
        "herd_effect",
        "deliberation_quality",
        "susceptibility",
        "convergence",
        "information_diversity",
    }
    for buckets in result["mcq_dimensions"].values():
        assert set(buckets.keys()) == {"very_low", "low", "high", "very_high"}
        assert sum(buckets.values()) == pytest.approx(1.0)
    assert result["validated_scales"]["schema_version"] == "v1"
    assert result["validated_scales"]["scores"]["evidence_alignment"] == pytest.approx(0.8)


def test_probability_evaluator_rejects_missing_rubric_dimension():
    class FakeClient:
        def chat_json(self, messages, temperature=0.3, max_tokens=4096):
            return {
                "probabilities": {"A": 1, "B": 1},
                "mcq_dimensions": {
                    "prediction_accuracy": {"very_low": 1, "low": 1, "high": 1, "very_high": 1},
                },
                "validated_scales": {"schema_version": "v1", "scores": {"x": 1.0}},
            }

    class FakeRouter:
        def client_for(self, role):
            return FakeClient()

    with pytest.raises(ValueError, match=r"mcq_dimensions"):
        ProbabilityEvaluator(FakeRouter()).evaluate("Q", "A", "E")
```

- [ ] **Step 2: Run targeted test file and verify it fails**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py -q`  
Expected: FAIL with missing `mcq_dimensions` / `validated_scales` handling.

- [ ] **Step 3: Implement strict rubric schema in evaluator**

```python
# backend/app/benchmarks/evaluator.py (add near top)
MCQ_DIMENSION_KEYS = (
    "prediction_accuracy",
    "polarization",
    "herd_effect",
    "deliberation_quality",
    "susceptibility",
    "convergence",
    "information_diversity",
)
MCQ_BUCKET_KEYS = ("very_low", "low", "high", "very_high")
VALIDATED_SCALES_SCHEMA_VERSION = "v1"


def _normalize_probability_mapping(mapping: Any, *, context: str) -> Dict[str, float]:
    if not isinstance(mapping, Mapping) or not mapping:
        raise ValueError(f"{context} must be a non-empty mapping")
    normalized: Dict[str, float] = {}
    total = 0.0
    for label, value in mapping.items():
        if not isinstance(label, str) or not label:
            raise ValueError(f"{context} keys must be non-empty strings")
        if not isinstance(value, (int, float)):
            raise ValueError(f"Invalid numeric value in {context} for {label!r}: {value!r}")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0.0:
            raise ValueError(f"Invalid numeric value in {context} for {label!r}: {value!r}")
        normalized[label] = numeric
        total += numeric
    if total <= 0.0:
        raise ValueError(f"{context} must have positive total mass")
    return {k: v / total for k, v in normalized.items()}


def _validate_numeric_scores_mapping(mapping: Any, *, context: str) -> Dict[str, float]:
    if not isinstance(mapping, Mapping) or not mapping:
        raise ValueError(f"{context} must be a non-empty mapping")
    validated: Dict[str, float] = {}
    for label, value in mapping.items():
        if not isinstance(label, str) or not label:
            raise ValueError(f"{context} keys must be non-empty strings")
        if not isinstance(value, (int, float)):
            raise ValueError(f"Invalid numeric value in {context} for {label!r}: {value!r}")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"Invalid numeric value in {context} for {label!r}: {value!r}")
        validated[label] = numeric
    return validated
```

```python
# backend/app/benchmarks/evaluator.py (inside ProbabilityEvaluator)
def _normalize_mcq_dimensions(self, dimensions: Any) -> Dict[str, Dict[str, float]]:
    if not isinstance(dimensions, Mapping):
        raise ValueError("Evaluator response must include mcq_dimensions mapping")
    if set(dimensions.keys()) != set(MCQ_DIMENSION_KEYS):
        raise ValueError("mcq_dimensions must include exactly 7 canonical dimensions")
    normalized: Dict[str, Dict[str, float]] = {}
    for dimension in MCQ_DIMENSION_KEYS:
        buckets = dimensions.get(dimension)
        if not isinstance(buckets, Mapping):
            raise ValueError(f"mcq_dimensions[{dimension!r}] must be a mapping")
        if set(buckets.keys()) != set(MCQ_BUCKET_KEYS):
            raise ValueError(f"mcq_dimensions[{dimension!r}] must include exactly {MCQ_BUCKET_KEYS}")
        normalized[dimension] = _normalize_probability_mapping(buckets, context=f"mcq_dimensions[{dimension}]")
    return normalized


def _normalize_validated_scales(self, validated_scales: Any) -> Dict[str, Any]:
    if not isinstance(validated_scales, Mapping):
        raise ValueError("Evaluator response must include validated_scales object")
    schema_version = validated_scales.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise ValueError("validated_scales.schema_version must be a non-empty string")
    if schema_version != VALIDATED_SCALES_SCHEMA_VERSION:
        raise ValueError(f"validated_scales.schema_version must be {VALIDATED_SCALES_SCHEMA_VERSION!r}")
    scores = validated_scales.get("scores")
    validated_scores = _validate_numeric_scores_mapping(scores, context="validated_scales.scores")
    return {"schema_version": schema_version, "scores": validated_scores}
```

```python
# backend/app/benchmarks/evaluator.py (inside evaluate)
probabilities = response.get("probabilities") if isinstance(response, dict) else None
mcq_dimensions = response.get("mcq_dimensions") if isinstance(response, dict) else None
validated_scales = response.get("validated_scales") if isinstance(response, dict) else None
normalized_probabilities = self._normalize_probabilities(probabilities)
normalized_dimensions = self._normalize_mcq_dimensions(mcq_dimensions)
normalized_scales = self._normalize_validated_scales(validated_scales)

result = dict(response) if isinstance(response, dict) else {}
result["probabilities"] = normalized_probabilities
result["normalized_probabilities"] = normalized_probabilities
result["mcq_dimensions"] = normalized_dimensions
result["validated_scales"] = normalized_scales
return result
```

- [ ] **Step 4: Run evaluator tests**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/evaluator.py backend/tests/test_benchmark_evaluator_scoring.py
git commit -m "feat: add strict rubric and validated scales evaluator contract" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Persist rubric artifacts in protocol rows and preserve compatibility (TDD)

**Files:**
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/app/benchmarks/orchestrator.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`
- Modify: `backend/tests/test_benchmark_orchestrator.py`

- [ ] **Step 1: Add failing protocol tests for rubric fields in rows**

```python
# backend/tests/test_run_ecnbench_protocol.py (append)
def test_build_event_result_row_includes_rubric_artifacts():
    event = {"event_id": "E1", "question": "Q", "outcome": "A", "options": ["A", "B"]}
    row = protocol_script.build_event_result_row(
        event,
        "A",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"A": 0.7, "B": 0.3},
        brier=0.18,
        mcq_dimensions={"prediction_accuracy": {"very_low": 0.1, "low": 0.2, "high": 0.3, "very_high": 0.4}},
        validated_scales={"schema_version": "v1", "scores": {"calibration_consistency": 0.8}},
    )
    assert "mcq_dimensions" in row
    assert "validated_scales" in row
```

```python
# backend/tests/test_benchmark_orchestrator.py (append)
def test_orchestrator_fallback_row_contains_rubric_keys(tmp_path):
    class ExplodingExecutor:
        def execute(self, **kwargs):
            raise RuntimeError("boom")

    orchestrator = BenchmarkRunOrchestrator(executor=ExplodingExecutor())
    run_dir = orchestrator.run(
        run_id="r1",
        output_root=tmp_path,
        events=[{"event_id": "E1"}],
        repeats=1,
        build_condition_matrix=lambda *_args, **_kwargs: [{"event_id": "E1", "condition": "A", "repeat": 1}],
        event_lookup={"E1": {"event_id": "E1"}},
        write_summary=lambda path, rows: (path / "summary.json").write_text("{}", encoding="utf-8"),
    )
    rows = json.loads((run_dir / "event_results.json").read_text(encoding="utf-8"))
    assert rows[0]["simulation_status"] == "simulation_failed"
    assert rows[0]["mcq_dimensions"] is None
    assert rows[0]["validated_scales"] is None
```

- [ ] **Step 2: Run targeted tests to verify they fail**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py::test_build_event_result_row_includes_rubric_artifacts tests\test_benchmark_orchestrator.py::test_orchestrator_fallback_row_contains_rubric_keys -q`  
Expected: FAIL due missing `mcq_dimensions` / `validated_scales` keys.

- [ ] **Step 3: Implement additive row fields and evaluator payload handling**

```python
# backend/scripts/run_ecnbench_protocol.py (extend build_event_result_row signature)
def build_event_result_row(
    ...,
    probabilities: Mapping[str, float] | None,
    brier: float | None,
    mcq_dimensions: Mapping[str, Mapping[str, float]] | None = None,
    validated_scales: Mapping[str, Any] | None = None,
    ...
) -> Dict[str, Any]:
    ...
    return {
        ...
        "probabilities": dict(probabilities) if isinstance(probabilities, Mapping) else None,
        "brier": brier,
        "mcq_dimensions": dict(mcq_dimensions) if isinstance(mcq_dimensions, Mapping) else None,
        "validated_scales": dict(validated_scales) if isinstance(validated_scales, Mapping) else None,
        ...
    }
```

```python
# backend/scripts/run_ecnbench_protocol.py (replace _evaluate_row return shape)
def _evaluate_row(... ) -> Dict[str, Any]:
    evaluator = ProbabilityEvaluator(router)
    evaluation = evaluator.evaluate(event.get("question", ""), condition, evidence_text)
    probabilities = evaluation.get("normalized_probabilities") or evaluation.get("probabilities")
    if not isinstance(probabilities, Mapping):
        raise ValueError("Evaluator did not return probabilities")
    mcq_dimensions = evaluation.get("mcq_dimensions")
    validated_scales = evaluation.get("validated_scales")
    if not isinstance(mcq_dimensions, Mapping):
        raise ValueError("Evaluator did not return mcq_dimensions")
    if not isinstance(validated_scales, Mapping):
        raise ValueError("Evaluator did not return validated_scales")
    ground_truth = event.get("outcome") or event.get("answer", "")
    if not isinstance(ground_truth, str) or not ground_truth.strip():
        raise ValueError("Event is missing a ground-truth outcome")
    normalized_probabilities = {str(label): float(value) for label, value in probabilities.items()}
    return {
        "probabilities": normalized_probabilities,
        "brier": brier_score(normalized_probabilities, ground_truth),
        "mcq_dimensions": dict(mcq_dimensions),
        "validated_scales": dict(validated_scales),
    }
```

```python
# backend/app/benchmarks/orchestrator.py (inside ProtocolConditionExecutor.execute)
evaluation_payload = evaluator(event, condition, evidence_text, self._router)
if isinstance(evaluation_payload, tuple):
    probabilities, brier = evaluation_payload
    mcq_dimensions = None
    validated_scales = None
elif isinstance(evaluation_payload, Mapping):
    probabilities = evaluation_payload.get("probabilities")
    brier = evaluation_payload.get("brier")
    mcq_dimensions = evaluation_payload.get("mcq_dimensions")
    validated_scales = evaluation_payload.get("validated_scales")
else:
    raise ValueError("Evaluator returned unsupported payload type")
```

```python
# backend/app/benchmarks/orchestrator.py (fallback rows)
"mcq_dimensions": None,
"validated_scales": None,
```

- [ ] **Step 4: Run protocol + orchestrator tests**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py tests\test_benchmark_orchestrator.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/app/benchmarks/orchestrator.py backend/tests/test_run_ecnbench_protocol.py backend/tests/test_benchmark_orchestrator.py
git commit -m "feat: persist rubric artifacts in protocol result rows" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add additive rubric summary helper (no weighted aggregate)

**Files:**
- Modify: `backend/app/benchmarks/scoring.py`
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`

- [ ] **Step 1: Add failing tests for rubric summary helper**

```python
# backend/tests/test_benchmark_evaluator_scoring.py (append)
from app.benchmarks.scoring import summarize_rubric_artifacts


def test_summarize_rubric_artifacts_counts_presence_and_scale_keys():
    rows = [
        {
            "full_simulation_completed": True,
            "mcq_dimensions": {"prediction_accuracy": {"very_low": 0.25, "low": 0.25, "high": 0.25, "very_high": 0.25}},
            "validated_scales": {"schema_version": "v1", "scores": {"calibration_consistency": 0.8, "evidence_alignment": 0.7}},
        },
        {"full_simulation_completed": True, "mcq_dimensions": None, "validated_scales": None},
    ]
    summary = summarize_rubric_artifacts(rows)
    assert summary["rubric_completed_count"] == 1
    assert summary["rubric_missing_count"] == 1
    assert summary["validated_scale_keys"] == ["calibration_consistency", "evidence_alignment"]
```

- [ ] **Step 2: Run targeted scoring tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py::test_summarize_rubric_artifacts_counts_presence_and_scale_keys -q`  
Expected: FAIL because helper does not exist yet.

- [ ] **Step 3: Implement helper and wire into summary output**

```python
# backend/app/benchmarks/scoring.py
def summarize_rubric_artifacts(rows: List[Dict]) -> Dict:
    completed = [row for row in rows if row.get("full_simulation_completed")]
    rubric_ready = [row for row in completed if isinstance(row.get("mcq_dimensions"), dict) and isinstance(row.get("validated_scales"), dict)]
    scale_keys = sorted(
        {
            key
            for row in rubric_ready
            for key in (
                row.get("validated_scales", {}).get("scores", {}).keys()
                if isinstance(row.get("validated_scales", {}).get("scores"), dict)
                else []
            )
        }
    )
    return {
        "rubric_completed_count": len(rubric_ready),
        "rubric_missing_count": len(completed) - len(rubric_ready),
        "validated_scale_keys": scale_keys,
    }
```

```python
# backend/scripts/run_ecnbench_protocol.py (imports)
from app.benchmarks.scoring import brier_score, summarize_condition_scores, summarize_rubric_artifacts

# inside summarize_event_results(...)
summary = summarize_condition_scores([row for row in completed_rows if row.get("brier") is not None])
summary["rubric"] = summarize_rubric_artifacts(rows)
```

- [ ] **Step 4: Run scoring and protocol tests**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/scoring.py backend/tests/test_benchmark_evaluator_scoring.py backend/scripts/run_ecnbench_protocol.py
git commit -m "feat: add additive rubric summary metadata" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Documentation and full benchmark regression gate

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document additive rubric contract and deferred weighted scoring**

```markdown
## ECN-BENCH rubric contract (additive)

- Evaluator now returns:
  - `probabilities` (legacy)
  - `mcq_dimensions` (7 required dimensions × 4 buckets: `very_low`, `low`, `high`, `very_high`)
  - `validated_scales` (`schema_version` + `scores`)
- Current numeric aggregation remains:
  - multiclass Brier
  - condition lift (`A_to_B`, `A_to_C`, `B_to_C`)
- Weighted 7-dimension aggregate scoring is intentionally deferred to a later pass.
```

- [ ] **Step 2: Run benchmark-focused regression suite**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_protocol.py tests\test_benchmark_evaluator_scoring.py tests\test_benchmark_role_router.py tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py tests\test_api_status.py -q`  
Expected: PASS.

- [ ] **Step 3: Run protocol sanity command (A/B/C intact)**

Run:  
`Set-Location backend; python scripts\run_ecnbench_protocol.py --seeds-dir C:\Users\TPGHien\Desktop\Claw-4-FUN\data\seeds --events-raw C:\Users\TPGHien\Desktop\Claw-4-FUN\data\events_raw.json --injection-bank C:\Users\TPGHien\Desktop\Claw-4-FUN\data\injections\step30_injection_bank.json --output-dir logs\benchmark_runs --events 1 --repeats 1`

Expected: exit code 0, with `run_manifest.json`, `event_results.json`, `summary.json`, and traces in the new run directory.

- [ ] **Step 4: Commit docs**

```bash
git add README.md
git commit -m "docs: document additive rubric evaluator contract" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 5: Optional broader suite (if environment supports all dependencies)**

Run: `Set-Location backend; python -m pytest tests -q`  
Expected: PASS, or documented dependency blocker if unavailable.

