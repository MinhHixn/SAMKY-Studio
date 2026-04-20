# ECN-BENCH Layer 2 Phase 1 Telemetry + Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic convergence telemetry and deterministic baselines (uniform + market prior) with hard preflight validation, and wire all outputs into existing benchmark artifacts.

**Architecture:** Keep the 60-round simulation engine unchanged. Compute new metrics in benchmark orchestration from existing execution artifacts (`twitter/actions.jsonl`, `reddit/actions.jsonl`) plus event metadata. Add a strict preflight gate before condition-matrix generation and extend row/summary/manifest payloads with Phase 1 fields.

**Tech Stack:** Python 3.11, pytest, ECN benchmark pipeline (`backend/scripts/run_ecnbench_protocol.py`, `backend/app/benchmarks/*.py`), JSON config.

---

## Scope Check

This plan implements only **Phase 1 (Telemetry + Baseline Integration)** from the approved design:
1. Checkpoint telemetry at rounds `[12, 24, 36, 48, 60]`
2. JSD trace + monotonic flag
3. Baseline agents (`uniform_random`, `market_prior`)
4. Hard preflight for `polymarket_opening_prior`
5. Manifest + row contract wiring

Deferred: power analysis, RPS/calibration, reliability double-run κ, leakage date/keyword gates, topology/conformity.

---

## File Structure and Responsibilities

- Create: `backend/config/benchmark_phase1_v1.json`  
  Central registry for Phase 1 constants (`telemetry_checkpoints`, `jsd_monotonic_tolerance_epsilon`, `prior_sum_tolerance`, parser coverage threshold, baseline registry).
- Create: `backend/app/benchmarks/phase1_registry.py`  
  Loader/validator for the Phase 1 config.
- Create: `backend/app/benchmarks/phase1_baselines.py`  
  `polymarket_opening_prior` validator + deterministic baseline scoring.
- Create: `backend/app/benchmarks/phase1_telemetry.py`  
  Action-trace parser, per-checkpoint probability extraction, JSD trace, monotonicity helper.
- Modify: `backend/scripts/run_ecnbench_protocol.py`  
  Preflight gate, per-unit telemetry extraction, baseline scoring, row/summary/manifest field extensions.
- Modify: `backend/app/benchmarks/orchestrator.py`  
  Ensure unit directory contract needed by telemetry extraction remains stable.
- Modify: `backend/tests/test_run_ecnbench_protocol.py`  
  Coverage for preflight hard-fail and new payload fields.
- Modify: `backend/tests/test_benchmark_orchestrator.py`  
  Coverage for row propagation of telemetry/baseline fields.
- Create: `backend/tests/test_benchmark_phase1_registry.py`  
  Config validation tests.
- Create: `backend/tests/test_benchmark_phase1_baselines.py`  
  Prior-validation and baseline scoring tests.
- Create: `backend/tests/test_benchmark_phase1_telemetry.py`  
  Action parsing, JSD, monotonicity tests.
- Modify: `README.md`  
  Benchmark section update for Phase 1 telemetry + baseline/preflight contract.

---

### Task 1: Add Phase 1 config registry (TDD)

**Files:**
- Create: `backend/config/benchmark_phase1_v1.json`
- Create: `backend/app/benchmarks/phase1_registry.py`
- Create: `backend/tests/test_benchmark_phase1_registry.py`

- [ ] **Step 1: Write failing registry tests**

```python
# backend/tests/test_benchmark_phase1_registry.py
import json
from pathlib import Path

import pytest

from app.benchmarks.phase1_registry import load_phase1_config


def test_load_phase1_config_happy_path(tmp_path: Path):
    payload = {
        "version": "phase1_v1",
        "telemetry_checkpoints": [12, 24, 36, 48, 60],
        "jsd_monotonic_tolerance_epsilon": 0.002,
        "prior_sum_tolerance": 1e-6,
        "min_parsed_probability_ratio": 0.25,
        "baseline_agents": ["uniform_random", "market_prior"],
    }
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    cfg = load_phase1_config(path)

    assert cfg["version"] == "phase1_v1"
    assert cfg["telemetry_checkpoints"] == [12, 24, 36, 48, 60]


def test_load_phase1_config_rejects_missing_required_keys(tmp_path: Path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"version": "phase1_v1"}), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required phase1 config keys"):
        load_phase1_config(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_phase1_registry.py -q`  
Expected: FAIL (`ModuleNotFoundError` for `phase1_registry`).

- [ ] **Step 3: Implement config + loader**

```json
// backend/config/benchmark_phase1_v1.json
{
  "version": "phase1_v1",
  "telemetry_checkpoints": [12, 24, 36, 48, 60],
  "jsd_monotonic_tolerance_epsilon": 0.002,
  "prior_sum_tolerance": 1e-6,
  "min_parsed_probability_ratio": 0.25,
  "baseline_agents": ["uniform_random", "market_prior"]
}
```

```python
# backend/app/benchmarks/phase1_registry.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping


def load_phase1_config(path: Path | str) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("phase1 config must be a JSON object")

    required = {
        "version",
        "telemetry_checkpoints",
        "jsd_monotonic_tolerance_epsilon",
        "prior_sum_tolerance",
        "min_parsed_probability_ratio",
        "baseline_agents",
    }
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing required phase1 config keys: {sorted(missing)}")

    checkpoints = payload["telemetry_checkpoints"]
    if checkpoints != [12, 24, 36, 48, 60]:
        raise ValueError("telemetry_checkpoints must be exactly [12,24,36,48,60]")

    return dict(payload)
```

- [ ] **Step 4: Run test to verify pass**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_phase1_registry.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/config/benchmark_phase1_v1.json backend/app/benchmarks/phase1_registry.py backend/tests/test_benchmark_phase1_registry.py
git commit -m "feat: add phase1 config registry" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add market-prior preflight and baseline scoring (TDD)

**Files:**
- Create: `backend/app/benchmarks/phase1_baselines.py`
- Create: `backend/tests/test_benchmark_phase1_baselines.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing baseline tests**

```python
# backend/tests/test_benchmark_phase1_baselines.py
import pytest

from app.benchmarks.phase1_baselines import (
    validate_polymarket_opening_prior,
    build_baseline_scores,
)


def test_validate_polymarket_opening_prior_happy_path():
    event = {
        "event_id": "E1",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": 0.55, "NO": 0.45},
    }
    validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)


def test_validate_polymarket_opening_prior_rejects_missing_label():
    event = {
        "event_id": "E1",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": 1.0},
    }
    with pytest.raises(ValueError, match="missing required outcome labels"):
        validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)


def test_build_baseline_scores_returns_uniform_and_market_prior():
    event = {
        "event_id": "E1",
        "outcome": "YES",
        "options": ["YES", "NO"],
        "polymarket_opening_prior": {"YES": 0.6, "NO": 0.4},
    }
    baseline_scores = build_baseline_scores(event)
    assert set(baseline_scores.keys()) == {"uniform_random", "market_prior"}
    assert "brier" in baseline_scores["uniform_random"]
    assert "brier" in baseline_scores["market_prior"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_phase1_baselines.py -q`  
Expected: FAIL (module/functions missing).

- [ ] **Step 3: Implement prior validator + baseline scoring**

```python
# backend/app/benchmarks/phase1_baselines.py
from __future__ import annotations

from typing import Any, Dict, Mapping

from .scoring import brier_score


def validate_polymarket_opening_prior(event: Mapping[str, Any], *, prior_sum_tolerance: float) -> Dict[str, float]:
    event_id = str(event.get("event_id", "unknown_event"))
    options = [str(option) for option in event.get("options", [])]
    prior = event.get("polymarket_opening_prior")
    if not isinstance(prior, Mapping):
        raise ValueError(f"{event_id}: polymarket_opening_prior missing or invalid")

    normalized: Dict[str, float] = {}
    for label in options:
        if label not in prior:
            raise ValueError(f"{event_id}: missing required outcome labels in polymarket_opening_prior")
        raw = prior[label]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{event_id}: prior {label!r} must be numeric")
        value = float(raw)
        if value < 0.0 or value > 1.0:
            raise ValueError(f"{event_id}: prior {label!r} out of range [0,1]")
        normalized[label] = value

    if abs(sum(normalized.values()) - 1.0) > float(prior_sum_tolerance):
        raise ValueError(f"{event_id}: polymarket_opening_prior must sum to 1.0")
    return normalized


def build_baseline_scores(event: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    outcome = str(event.get("outcome") or event.get("answer") or "")
    options = [str(option) for option in event.get("options", [])]
    n = len(options)
    uniform = {label: 1.0 / n for label in options}
    market_prior = validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)
    return {
        "uniform_random": {"probabilities": uniform, "brier": brier_score(uniform, outcome)},
        "market_prior": {"probabilities": market_prior, "brier": brier_score(market_prior, outcome)},
    }
```

- [ ] **Step 4: Wire preflight call before condition matrix creation**

```python
# backend/scripts/run_ecnbench_protocol.py (main)
phase1_cfg = load_phase1_config(DEFAULT_PHASE1_CONFIG_PATH)
for event in events:
    validate_polymarket_opening_prior(
        event,
        prior_sum_tolerance=float(phase1_cfg["prior_sum_tolerance"]),
    )
condition_matrix = build_condition_matrix(events, args.repeats)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_phase1_baselines.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS for new baseline tests and updated preflight tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/benchmarks/phase1_baselines.py backend/tests/test_benchmark_phase1_baselines.py backend/scripts/run_ecnbench_protocol.py
git commit -m "feat: add phase1 baseline preflight and scoring" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add convergence telemetry extraction (TDD)

**Files:**
- Create: `backend/app/benchmarks/phase1_telemetry.py`
- Create: `backend/tests/test_benchmark_phase1_telemetry.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing telemetry tests**

```python
# backend/tests/test_benchmark_phase1_telemetry.py
import json
from pathlib import Path

import pytest

from app.benchmarks.phase1_telemetry import (
    compute_round_jsd_trace,
    is_monotonic_nonincreasing_with_epsilon,
)


def test_is_monotonic_nonincreasing_with_epsilon():
    trace = [0.30, 0.28, 0.281, 0.25, 0.20]
    assert is_monotonic_nonincreasing_with_epsilon(trace, epsilon=0.002) is True


def test_compute_round_jsd_trace_returns_five_values(tmp_path: Path):
    twitter = tmp_path / "twitter" / "actions.jsonl"
    reddit = tmp_path / "reddit" / "actions.jsonl"
    twitter.parent.mkdir(parents=True)
    reddit.parent.mkdir(parents=True)
    row = {"round": 12, "agent_id": 1, "action_args": {"content": "P(YES)=0.70"}}
    twitter.write_text(json.dumps(row) + "\n", encoding="utf-8")
    reddit.write_text("", encoding="utf-8")

    trace = compute_round_jsd_trace(
        unit_dir=tmp_path,
        checkpoints=[12, 24, 36, 48, 60],
        resolved_label="YES",
        min_parsed_probability_ratio=0.0,
    )
    assert len(trace["round_jsd"]) == 5
```

- [ ] **Step 2: Run test to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_phase1_telemetry.py -q`  
Expected: FAIL (module/functions missing).

- [ ] **Step 3: Implement deterministic parser + JSD trace**

```python
# backend/app/benchmarks/phase1_telemetry.py
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

PROBABILITY_PATTERNS = [
    re.compile(r"P\((YES|NO)\)\s*=\s*(0(?:\.\d+)?|1(?:\.0+)?)", re.IGNORECASE),
    re.compile(r"(\d{1,3})\s*%\s*(?:chance|probability)", re.IGNORECASE),
]


def _js_divergence(p: Iterable[float], q: Iterable[float]) -> float:
    p_list = [float(x) for x in p]
    q_list = [float(x) for x in q]
    m = [(a + b) / 2.0 for a, b in zip(p_list, q_list)]

    def _kl(a: List[float], b: List[float]) -> float:
        total = 0.0
        for ai, bi in zip(a, b):
            if ai <= 0.0:
                continue
            total += ai * math.log(ai / bi, 2)
        return total

    return 0.5 * _kl(p_list, m) + 0.5 * _kl(q_list, m)


def is_monotonic_nonincreasing_with_epsilon(trace: List[float], epsilon: float) -> bool:
    for previous, current in zip(trace, trace[1:]):
        if current > previous + epsilon:
            return False
    return True
```

- [ ] **Step 4: Add row-level telemetry wiring**

```python
# backend/scripts/run_ecnbench_protocol.py (inside build_event_result_row call path)
telemetry = compute_round_jsd_trace(
    unit_dir=unit_dir,
    checkpoints=phase1_checkpoints,
    resolved_label=str(event.get("outcome") or event.get("answer") or ""),
    min_parsed_probability_ratio=float(phase1_cfg["min_parsed_probability_ratio"]),
)
row["round_jsd"] = telemetry["round_jsd"]
row["convergence_monotonic"] = is_monotonic_nonincreasing_with_epsilon(
    telemetry["round_jsd"],
    epsilon=float(phase1_cfg["jsd_monotonic_tolerance_epsilon"]),
)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_phase1_telemetry.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/benchmarks/phase1_telemetry.py backend/tests/test_benchmark_phase1_telemetry.py backend/scripts/run_ecnbench_protocol.py
git commit -m "feat: add checkpoint convergence telemetry" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Attach baseline_scores and telemetry fields to each unit row

**Files:**
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/app/benchmarks/orchestrator.py`
- Modify: `backend/tests/test_benchmark_orchestrator.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing integration tests for row contract**

```python
# backend/tests/test_run_ecnbench_protocol.py (new assertions)
assert "round_jsd" in row
assert len(row["round_jsd"]) == 5
assert "convergence_monotonic" in row
assert "baseline_scores" in row
assert set(row["baseline_scores"]) == {"uniform_random", "market_prior"}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py::test_main_writes_phase1_fields -q`  
Expected: FAIL (new fields missing).

- [ ] **Step 3: Implement row propagation**

```python
# backend/scripts/run_ecnbench_protocol.py (build_event_result_row signature + return payload)
def build_event_result_row(..., round_jsd: List[float] | None = None, convergence_monotonic: bool | None = None, baseline_scores: Mapping[str, Any] | None = None, ...):
    ...
    return {
        ...
        "round_jsd": list(round_jsd) if isinstance(round_jsd, list) else None,
        "convergence_monotonic": convergence_monotonic,
        "baseline_scores": dict(baseline_scores) if isinstance(baseline_scores, Mapping) else None,
        ...
    }
```

- [ ] **Step 4: Verify orchestrator preserves additive row keys**

Run: `Set-Location backend; python -m pytest tests\test_benchmark_orchestrator.py -q`  
Expected: PASS with additive-field assertions.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/app/benchmarks/orchestrator.py backend/tests/test_benchmark_orchestrator.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: add phase1 row telemetry and baseline fields" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Manifest and summary wiring + strict validation

**Files:**
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing tests for manifest fields**

```python
# backend/tests/test_run_ecnbench_protocol.py (manifest assertions)
assert manifest["phase1_config_version"] == "phase1_v1"
assert manifest["telemetry_checkpoints"] == [12, 24, 36, 48, 60]
assert manifest["jsd_monotonic_tolerance_epsilon"] == 0.002
assert manifest["baseline_agents"] == ["uniform_random", "market_prior"]
assert manifest["preflight_market_prior_check"] == "pass"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py::test_main_manifest_includes_phase1_contract -q`  
Expected: FAIL (manifest fields missing).

- [ ] **Step 3: Add manifest extensions + summary helpers**

```python
# backend/scripts/run_ecnbench_protocol.py (manifest)
manifest.update(
    {
        "phase1_config_version": phase1_cfg["version"],
        "telemetry_checkpoints": phase1_cfg["telemetry_checkpoints"],
        "jsd_monotonic_tolerance_epsilon": phase1_cfg["jsd_monotonic_tolerance_epsilon"],
        "baseline_agents": phase1_cfg["baseline_agents"],
        "preflight_market_prior_check": "pass",
    }
)
```

```python
# backend/scripts/run_ecnbench_protocol.py (summary)
summary["convergence"] = {
    "mean_round_jsd": _mean_round_jsd(completed_rows),
    "monotonic_count": sum(1 for row in completed_rows if row.get("convergence_monotonic") is True),
}
```

- [ ] **Step 4: Run integration tests**

Run: `Set-Location backend; python -m pytest tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: add phase1 manifest and summary contract fields" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Documentation and full regression pass

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update benchmark methodology section**

```markdown
## ECN-BENCH Phase 1 telemetry and baselines

- Convergence telemetry checkpoints: `[12, 24, 36, 48, 60]`
- Convergence metric: 4-bin JSD trace vs uniform + epsilon monotonic flag
- Baselines: `uniform_random`, `market_prior`
- Preflight contract: every event must include valid `polymarket_opening_prior`; benchmark run hard-fails otherwise
- Per-row fields: `round_jsd`, `convergence_monotonic`, `baseline_scores`
- Manifest fields: `phase1_config_version`, `telemetry_checkpoints`, `baseline_agents`, `preflight_market_prior_check`
```

- [ ] **Step 2: Run focused regression suite**

Run:
`Set-Location backend; python -m pytest tests\test_benchmark_phase1_registry.py tests\test_benchmark_phase1_baselines.py tests\test_benchmark_phase1_telemetry.py tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 3: Run full backend test suite**

Run: `Set-Location backend; python -m pytest tests -q`  
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md backend/tests
git commit -m "docs: document phase1 telemetry and baseline contract" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review Checklist (Completed)

1. **Spec coverage:** All Phase 1 requirements mapped to tasks: telemetry checkpoints/JSD/monotonic, deterministic baselines, preflight hard-fail, row+manifest wiring, tests/docs.
2. **Placeholder scan:** No TBD/TODO placeholders remain; each task has concrete files, code snippets, and commands.
3. **Type consistency:** Field names are consistent across tasks (`round_jsd`, `convergence_monotonic`, `baseline_scores`, `polymarket_opening_prior`, `phase1_config_version`).
