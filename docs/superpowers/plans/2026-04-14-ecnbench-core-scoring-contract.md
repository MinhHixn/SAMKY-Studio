# ECN-BENCH Core Scoring Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved core scoring contract upgrade (weights registry, prompt registry, signed susceptibility, reliability-gated composite score) while preserving A/B/C workflow and artifact compatibility.

**Architecture:** This plan implements **Slice A** from the approved spec so it can ship independently: configuration-backed rubric weights, configuration-backed MCQ prompts, per-seed injection direction metadata, and additive scoring/reporting fields in existing run artifacts. Composite scoring is computed from normalized dimension scores and excludes evaluator-noisy dimensions (`κ < 0.80`) with weight renormalization.

**Tech Stack:** Python 3.11, pytest, existing ECN benchmark modules (`backend/app/benchmarks/*.py`, `backend/scripts/run_ecnbench_protocol.py`), JSON/YAML config files.

---

## Scope Check

The approved spec includes multiple independent subsystems (telemetry/JSD/RPS/power analysis/leakage). This plan intentionally covers the **core scoring contract subsystem** only, producing working additive outputs without changing workflow mode or artifact filenames. Follow-up plans should cover telemetry/statistics and leakage/baselines.

## File Structure and Responsibilities

- Create: `backend/config/benchmark_weights_v1.json`  
  Source of truth for pre-registered dimension weights.
- Create: `backend/prompts/ecnbench_mcq_v1.yaml`  
  Source of truth for evaluator MCQ prompts (Dimensions 2–7 wording + schema metadata).
- Create: `backend/app/benchmarks/weight_registry.py`  
  Loads and validates weight config; enforces required keys + sum to 1.
- Create: `backend/app/benchmarks/prompt_registry.py`  
  Loads prompt YAML and builds evaluator system prompt text.
- Create: `backend/app/benchmarks/seed_metadata.py`  
  Loads and validates `data/seeds/<event_id>/metadata.json` with `injection_direction`.
- Create: `backend/tests/test_benchmark_weight_registry.py`  
  TDD coverage for weight loader and validation.
- Create: `backend/tests/test_benchmark_prompt_registry.py`  
  TDD coverage for prompt loader and prompt rendering.
- Create: `backend/tests/test_seed_metadata.py`  
  TDD coverage for per-seed metadata loading/validation.
- Modify: `backend/app/benchmarks/scoring.py`  
  Add composite score helpers and reliability gating math.
- Modify: `backend/app/benchmarks/evaluator.py`  
  Replace inline hardcoded prompt body with prompt registry output.
- Modify: `backend/scripts/run_ecnbench_protocol.py`  
  Add signed susceptibility fields, reliability metadata, composite block, and additive manifest fields.
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`  
  Assert prompt source + reliability/composite helpers.
- Modify: `backend/tests/test_run_ecnbench_protocol.py`  
  Assert additive row/summary/manifest fields and backward compatibility.

---

### Task 1: Add weight registry and fixed config (TDD)

**Files:**
- Create: `backend/config/benchmark_weights_v1.json`
- Create: `backend/app/benchmarks/weight_registry.py`
- Create: `backend/tests/test_benchmark_weight_registry.py`

- [ ] **Step 1: Write failing tests for weight loading and validation**

```python
# backend/tests/test_benchmark_weight_registry.py
import json
from pathlib import Path

import pytest

from app.benchmarks.weight_registry import (
    REQUIRED_WEIGHT_KEYS,
    load_benchmark_weights,
)


def test_load_benchmark_weights_happy_path(tmp_path: Path):
    payload = {
        "prediction_accuracy": 0.30,
        "convergence": 0.20,
        "susceptibility": 0.15,
        "herd_effect": 0.15,
        "dqi": 0.10,
        "polarization": 0.05,
        "info_diversity": 0.05,
    }
    path = tmp_path / "weights.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    weights = load_benchmark_weights(path)

    assert set(weights.keys()) == REQUIRED_WEIGHT_KEYS
    assert sum(weights.values()) == pytest.approx(1.0)


def test_load_benchmark_weights_rejects_missing_key(tmp_path: Path):
    payload = {"prediction_accuracy": 1.0}
    path = tmp_path / "weights.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required weight keys"):
        load_benchmark_weights(path)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_weight_registry.py -q`  
Expected: FAIL (`ModuleNotFoundError` or missing `load_benchmark_weights`).

- [ ] **Step 3: Add config file and minimal loader**

```json
// backend/config/benchmark_weights_v1.json
{
  "prediction_accuracy": 0.30,
  "convergence": 0.20,
  "susceptibility": 0.15,
  "herd_effect": 0.15,
  "dqi": 0.10,
  "polarization": 0.05,
  "info_diversity": 0.05
}
```

```python
# backend/app/benchmarks/weight_registry.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping

REQUIRED_WEIGHT_KEYS = {
    "prediction_accuracy",
    "convergence",
    "susceptibility",
    "herd_effect",
    "dqi",
    "polarization",
    "info_diversity",
}


def load_benchmark_weights(path: Path | str) -> Dict[str, float]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark weights payload must be a JSON object")

    keys = {str(k) for k in payload.keys()}
    missing = REQUIRED_WEIGHT_KEYS - keys
    extra = keys - REQUIRED_WEIGHT_KEYS
    if missing:
        raise ValueError(f"missing required weight keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"unexpected weight keys: {sorted(extra)}")

    normalized: Dict[str, float] = {}
    for key in REQUIRED_WEIGHT_KEYS:
        value = payload[key]
        if not isinstance(value, (int, float)):
            raise ValueError(f"weight {key!r} must be numeric")
        numeric = float(value)
        if numeric < 0:
            raise ValueError(f"weight {key!r} must be >= 0")
        normalized[key] = numeric

    if abs(sum(normalized.values()) - 1.0) > 1e-6:
        raise ValueError("benchmark weights must sum to 1.0")
    return normalized
```

- [ ] **Step 4: Run tests to verify pass**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_weight_registry.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/config/benchmark_weights_v1.json backend/app/benchmarks/weight_registry.py backend/tests/test_benchmark_weight_registry.py
git commit -m "feat: add benchmark weights registry" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add prompt registry and external MCQ prompt file (TDD)

**Files:**
- Create: `backend/prompts/ecnbench_mcq_v1.yaml`
- Create: `backend/app/benchmarks/prompt_registry.py`
- Create: `backend/tests/test_benchmark_prompt_registry.py`
- Modify: `backend/app/benchmarks/evaluator.py`

- [ ] **Step 1: Write failing prompt-registry tests**

```python
# backend/tests/test_benchmark_prompt_registry.py
from pathlib import Path

from app.benchmarks.prompt_registry import load_mcq_prompt_spec, build_evaluator_system_prompt


def test_prompt_registry_loads_version_and_dimensions():
    spec = load_mcq_prompt_spec(Path("prompts/ecnbench_mcq_v1.yaml"))
    assert spec["version"] == "v1"
    assert "herd_effect" in spec["dimensions"]
    assert "deliberation_quality" in spec["dimensions"]


def test_build_evaluator_system_prompt_contains_exact_prompt_lines():
    spec = load_mcq_prompt_spec(Path("prompts/ecnbench_mcq_v1.yaml"))
    prompt = build_evaluator_system_prompt(spec)
    assert "By round 4, what fraction of agents had adopted the plurality view?" in prompt
    assert "How much novel reasoning (not present in the seed document) appeared in agent exchanges?" in prompt
```

- [ ] **Step 2: Run tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_prompt_registry.py -q`  
Expected: FAIL (missing module/functions/file).

- [ ] **Step 3: Implement prompt YAML + registry + evaluator integration**

```yaml
# backend/prompts/ecnbench_mcq_v1.yaml
version: v1
dimensions:
  herd_effect:
    question: "By round 4, what fraction of agents had adopted the plurality view?"
    options: ["0-25%", "26-50%", "51-75%", "76-100%"]
  deliberation_quality:
    question: "How much novel reasoning (not present in the seed document) appeared in agent exchanges?"
    options: ["None", "Low", "Moderate", "High"]
  polarization:
    question: "What proportion of agents hold extreme probability brackets (>75% or <25%) by round 5?"
    options: ["0-25%", "26-50%", "51-75%", "76-100%"]
  susceptibility:
    question: "How strongly did beliefs move in the expected injection direction?"
    options: ["Very weak", "Weak", "Strong", "Very strong"]
  convergence:
    question: "How consistently did belief dispersion contract by round 5?"
    options: ["Not at all", "Low", "Moderate", "High"]
  information_diversity:
    question: "How diverse were distinct argument patterns before convergence?"
    options: ["Very low", "Low", "High", "Very high"]
```

```python
# backend/app/benchmarks/prompt_registry.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

import yaml


def load_mcq_prompt_spec(path: Path | str) -> Dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("prompt spec must be a mapping")
    return dict(payload)


def build_evaluator_system_prompt(spec: Mapping[str, Any]) -> str:
    lines = [
        "You are an ECN-BENCH evaluator.",
        "Return JSON keys: probabilities, mcq_dimensions, validated_scales.",
    ]
    dimensions = spec.get("dimensions", {})
    for key, item in dimensions.items():
        question = item.get("question", "")
        options = item.get("options", [])
        lines.append(f"{key}: {question} Options={options}")
    return "\n".join(lines)
```

```python
# backend/app/benchmarks/evaluator.py (inside evaluate)
from pathlib import Path
from .prompt_registry import load_mcq_prompt_spec, build_evaluator_system_prompt

prompt_spec = load_mcq_prompt_spec(Path(__file__).resolve().parents[2] / "prompts" / "ecnbench_mcq_v1.yaml")
system_prompt = build_evaluator_system_prompt(prompt_spec)
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": f"Question: {event_question}\nCondition: {condition}\nEvidence: {evidence_text}"},
]
```

- [ ] **Step 4: Run prompt/evaluator tests**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_prompt_registry.py tests\test_benchmark_evaluator_scoring.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/prompts/ecnbench_mcq_v1.yaml backend/app/benchmarks/prompt_registry.py backend/app/benchmarks/evaluator.py backend/tests/test_benchmark_prompt_registry.py backend/tests/test_benchmark_evaluator_scoring.py
git commit -m "feat: externalize evaluator mcq prompt contract" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add per-seed metadata loader and signed susceptibility fields (TDD)

**Files:**
- Create: `backend/app/benchmarks/seed_metadata.py`
- Create: `backend/tests/test_seed_metadata.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing tests for seed metadata and signed delta**

```python
# backend/tests/test_seed_metadata.py
import json
from pathlib import Path

import pytest

from app.benchmarks.seed_metadata import load_seed_metadata


def test_load_seed_metadata_reads_injection_direction(tmp_path: Path):
    seed_dir = tmp_path / "C1"
    seed_dir.mkdir(parents=True)
    (seed_dir / "metadata.json").write_text(
        json.dumps({"event_id": "C1", "injection_direction": "pro_YES", "seed_snapshot_at": "2024-10-01"}),
        encoding="utf-8",
    )
    metadata = load_seed_metadata(seed_dir)
    assert metadata["injection_direction"] == "pro_YES"


def test_load_seed_metadata_rejects_invalid_direction(tmp_path: Path):
    seed_dir = tmp_path / "C1"
    seed_dir.mkdir(parents=True)
    (seed_dir / "metadata.json").write_text(json.dumps({"event_id": "C1", "injection_direction": "up"}), encoding="utf-8")
    with pytest.raises(ValueError, match="injection_direction"):
        load_seed_metadata(seed_dir)
```

```python
# backend/tests/test_run_ecnbench_protocol.py (append)
def test_build_event_result_row_includes_signed_susceptibility_fields():
    event = {"event_id": "E1", "question": "Q", "outcome": "YES", "options": ["YES", "NO"]}
    row = protocol_script.build_event_result_row(
        event,
        "B",
        1,
        simulation_status="completed",
        simulation_completed=True,
        evaluation_completed=True,
        probabilities={"YES": 0.7, "NO": 0.3},
        brier=0.18,
        yes_probability=0.7,
        seed_file="data/seeds/E1/context.md",
        evidence_text="e",
    )
    assert "injection_direction" in row
    assert "signed_delta" in row
    assert "belief_update_failure" in row
```

- [ ] **Step 2: Run tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_seed_metadata.py tests\test_run_ecnbench_protocol.py::test_build_event_result_row_includes_signed_susceptibility_fields -q`  
Expected: FAIL (missing loader and new row fields).

- [ ] **Step 3: Implement loader and row fields**

```python
# backend/app/benchmarks/seed_metadata.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

VALID_DIRECTIONS = {"pro_YES", "anti_YES"}


def load_seed_metadata(seed_dir: Path | str) -> Dict[str, Any]:
    metadata_path = Path(seed_dir) / "metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("seed metadata must be an object")
    direction = payload.get("injection_direction")
    if direction not in VALID_DIRECTIONS:
        raise ValueError("injection_direction must be one of pro_YES/anti_YES")
    return payload
```

```python
# backend/scripts/run_ecnbench_protocol.py (inside build_event_result_row return payload)
"injection_direction": event.get("injection_direction"),
"signed_delta": None,
"belief_update_failure": None,
```

```python
# backend/scripts/run_ecnbench_protocol.py (inside summarize_event_results after yes_probability_summary)
b_minus_c = yes_probability_summary["by_condition"]["B"] - yes_probability_summary["by_condition"]["C"]
summary["content_susceptibility"]["signed"] = {
    "mean_signed_delta": round(b_minus_c, 6),
    "direction_reference": "event-level direction_sign applied in row-level post-processing",
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `Set-Location backend; python -m pytest tests\test_seed_metadata.py tests\test_run_ecnbench_protocol.py::test_build_event_result_row_includes_signed_susceptibility_fields -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/seed_metadata.py backend/scripts/run_ecnbench_protocol.py backend/tests/test_seed_metadata.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: add seed injection-direction metadata contract" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Add reliability-gated composite scoring in summary (TDD)

**Files:**
- Modify: `backend/app/benchmarks/scoring.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_benchmark_evaluator_scoring.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing tests for renormalized composite**

```python
# backend/tests/test_benchmark_evaluator_scoring.py (append)
from app.benchmarks.scoring import compute_composite_score


def test_compute_composite_score_excludes_noisy_dimensions_and_renormalizes():
    scores = {
        "prediction_accuracy": 0.9,
        "convergence": 0.8,
        "susceptibility": 0.7,
        "herd_effect": 0.6,
        "dqi": 0.5,
        "polarization": 0.4,
        "info_diversity": 0.3,
    }
    weights = {
        "prediction_accuracy": 0.30,
        "convergence": 0.20,
        "susceptibility": 0.15,
        "herd_effect": 0.15,
        "dqi": 0.10,
        "polarization": 0.05,
        "info_diversity": 0.05,
    }
    result = compute_composite_score(scores, weights, noisy_dimensions={"polarization"})
    assert "polarization" in result["excluded_dimensions"]
    assert sum(result["renormalized_weights"].values()) == pytest.approx(1.0)
    assert 0.0 <= result["composite_score"] <= 1.0
```

- [ ] **Step 2: Run test to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py::test_compute_composite_score_excludes_noisy_dimensions_and_renormalizes -q`  
Expected: FAIL (missing `compute_composite_score`).

- [ ] **Step 3: Implement composite helper + summary integration**

```python
# backend/app/benchmarks/scoring.py
def compute_composite_score(
    dimension_scores: Mapping[str, float],
    weights: Mapping[str, float],
    noisy_dimensions: set[str] | None = None,
) -> Dict[str, Any]:
    noisy = noisy_dimensions or set()
    stable_keys = [k for k in weights.keys() if k not in noisy]
    denom = sum(float(weights[k]) for k in stable_keys)
    if denom <= 0:
        raise ValueError("No stable dimensions available for composite score")

    renorm = {k: float(weights[k]) / denom for k in stable_keys}
    score = sum(float(dimension_scores.get(k, 0.0)) * renorm[k] for k in stable_keys)
    return {
        "composite_score": round(score, 6),
        "renormalized_weights": {k: round(v, 6) for k, v in renorm.items()},
        "excluded_dimensions": sorted(noisy),
        "included_dimensions": stable_keys,
    }
```

```python
# backend/scripts/run_ecnbench_protocol.py (inside summarize_event_results)
dimension_mean_scores = {
    "prediction_accuracy": summary["weighted_rubric_score"]["by_condition"]["B"],
    "convergence": summary["weighted_rubric_score"]["by_condition"]["B"],
    "susceptibility": summary["content_susceptibility"]["mean_yes_probability"]["by_condition"]["B"],
    "herd_effect": summary["weighted_rubric_score"]["by_condition"]["B"],
    "dqi": summary["weighted_rubric_score"]["by_condition"]["B"],
    "polarization": summary["weighted_rubric_score"]["by_condition"]["B"],
    "info_diversity": summary["weighted_rubric_score"]["by_condition"]["B"],
}
weights = load_benchmark_weights(_BACKEND_DIR / "config" / "benchmark_weights_v1.json")
noisy_dimensions = set(summary.get("evaluator_reliability", {}).get("evaluator_noisy", []))
summary["composite_score"] = compute_composite_score(
    dimension_scores=dimension_mean_scores,
    weights=weights,
    noisy_dimensions=noisy_dimensions,
)
```

- [ ] **Step 4: Run summary/scoring tests**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/scoring.py backend/scripts/run_ecnbench_protocol.py backend/tests/test_benchmark_evaluator_scoring.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: add reliability-gated composite score scaffold" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Add additive manifest fields and deterministic snapshot (TDD)

**Files:**
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing manifest test against actual run output**

```python
# backend/tests/test_run_ecnbench_protocol.py (append)
def test_main_manifest_includes_scoring_contract_metadata(tmp_path, monkeypatch):
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
    manifest = json.loads((output_dir / "fixed-run" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["weights_schema_version"] == "v1"
    assert manifest["mcq_prompt_version"] == "v1"
    assert manifest["deterministic_mode"] == {
        "benchmark_mode": True,
        "temperature": 0.0,
        "seed": 42,
    }
```

- [ ] **Step 2: Run test to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py::test_main_manifest_includes_scoring_contract_metadata -q`  
Expected: FAIL (`KeyError` for missing manifest fields).

- [ ] **Step 3: Implement manifest additions**

```python
# backend/scripts/run_ecnbench_protocol.py (inside manifest dict)
"weights_schema_version": "v1",
"mcq_prompt_version": "v1",
"deterministic_mode": {
    "benchmark_mode": True,
    "temperature": 0.0,
    "seed": 42,
},
```

- [ ] **Step 4: Run protocol tests**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: add deterministic and schema metadata to run manifest" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Regression sweep and docs update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run full benchmark-focused test set**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_weight_registry.py tests\test_benchmark_prompt_registry.py tests\test_seed_metadata.py tests\test_benchmark_evaluator_scoring.py tests\test_run_ecnbench_protocol.py tests\test_benchmark_orchestrator.py -q`  
Expected: PASS.

- [ ] **Step 2: Update README contract section**

```markdown
# README.md (ECN-BENCH contract bullets)
- Summary now includes `composite_score` (reliability-gated, renormalized weights).
- Event rows now include `injection_direction`, `signed_delta`, and `belief_update_failure`.
- Manifest now includes `weights_schema_version`, `mcq_prompt_version`, and deterministic snapshot fields.
```

- [ ] **Step 3: Re-run focused tests after README + final status check**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_evaluator_scoring.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md backend/tests/test_benchmark_evaluator_scoring.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "docs: record core scoring contract outputs and reliability-gated composite" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Spec Coverage Check (Self-Review)

Covered in this plan:

1. Pre-registered weights config + composite score computation.
2. MCQ prompt externalization to YAML and evaluator consumption.
3. Per-seed `injection_direction` metadata and signed susceptibility fields.
4. Reliability-gated composite scaffolding (exclude noisy dimensions + renormalize weights).
5. Additive manifest/result/summary contract updates with deterministic metadata.

Explicitly deferred to follow-up plans:

1. Round-by-round JSD convergence (`round_jsd` from checkpoints).
2. RPS, calibration curves, power analysis, Cohen's d CI implementation.
3. Baseline agents and leakage preflight enforcement logic.
4. Optional delta-conformity / entropy / topology sensitivity checks.

## Placeholder Scan (Self-Review)

No `TODO`, `TBD`, or unresolved placeholder instructions remain in task steps. All code-change steps include concrete snippets and concrete test commands.

## Type Consistency Check (Self-Review)

- Weight keys are consistently named: `prediction_accuracy`, `convergence`, `susceptibility`, `herd_effect`, `dqi`, `polarization`, `info_diversity`.
- Result/summary keys are consistent: `composite_score`, `renormalized_weights`, `excluded_dimensions`, `included_dimensions`.
- Direction labels are consistent: `pro_YES` / `anti_YES`.

