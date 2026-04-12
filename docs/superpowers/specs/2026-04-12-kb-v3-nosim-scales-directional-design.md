# ECN-BENCH KB v3 Alignment: No-Sim A, Canonical Scales, Directional Accuracy

## Problem

Current benchmark code is strict on schema validity, but still misses three KB v3.0 requirements:

1. Condition A must be a true No-Sim baseline (same MCQ protocol, no simulation subprocess).
2. `validated_scales` must be semantically defined (fixed keys, ranges, formulas), not only structurally valid.
3. Directional accuracy must be surfaced as a computed headline metric in summary outputs.

## Decisions (Confirmed)

1. Keep A/B/C per-event workflow and existing Brier/lift outputs.
2. Implement in-place hardening (no broad refactor/new executor family).
3. Condition A will skip simulation execution entirely and still count as completed when evaluation succeeds.
4. `validated_scales` becomes deterministic from `mcq_dimensions` (not free-form evaluator scores).
5. Directional accuracy uses top-1 label correctness: `argmax(probabilities) == ground_truth`.
6. Weighted rubric aggregate is enabled now with:
   - `prediction_accuracy`: `0.25`
   - each remaining dimension: `0.125`

## Scope

### In Scope

1. True No-Sim execution path for Condition A in protocol/orchestrator runtime.
2. Canonical `validated_scales` semantics with explicit formulas and strict validation.
3. Directional accuracy metrics in run summary (condition-level + overall + deltas).
4. Additive row/schema updates and README documentation.
5. Regression and targeted tests for all three requirements.

### Out of Scope

1. Changing A/B/C matrix topology.
2. Replacing Brier as a primary numeric metric.
3. Multi-model orchestration changes.

## Architecture

### 1) No-Sim Condition A Runtime (`backend/app/benchmarks/orchestrator.py`)

`ProtocolConditionExecutor.execute` will branch by condition:

- **Condition A**
  - Do not invoke `run_parallel_simulation.py`.
  - Build evidence from seed context only (same downstream evaluator path as B/C).
  - Preserve existing failure semantics (`evaluation_failed` on evaluator contract errors).
  - Mark unit completed when evaluation succeeds.

- **Conditions B/C**
  - Keep current simulation subprocess path unchanged.

Add explicit row/trace flag for auditability:

- `simulation_executed: bool` (`False` for A, `True` for B/C).

### 2) Canonical Validated Scales (`backend/app/benchmarks/evaluator.py`, `.../orchestrator.py`, `.../scoring.py`)

Define strict canonical score keys (all in `[0,1]`):

1. `prediction_accuracy_score`
2. `polarization_score`
3. `herd_effect_score`
4. `deliberation_quality_score`
5. `susceptibility_score`
6. `convergence_score`
7. `information_diversity_score`
8. `weighted_rubric_score`

Bucket projection anchors:

- `very_low = 0.0`
- `low = 1/3`
- `high = 2/3`
- `very_high = 1.0`

Per-dimension score formula:

`dimension_score = Σ p(bucket) * anchor(bucket)`

Weighted aggregate formula:

`weighted_rubric_score = Σ weight(dimension) * dimension_score`

Validation contract:

- `schema_version == "v1"`
- exact canonical key set above
- all values finite, numeric, and in `[0,1]`

Implementation behavior:

- Evaluator still requires strict MCQ dimensions.
- Canonical scales are computed deterministically from normalized MCQ buckets.
- Any malformed/non-canonical scale payload seen later in orchestrator/scoring is hard-failed.

### 3) Directional Accuracy Output (`backend/app/benchmarks/scoring.py`, `backend/scripts/run_ecnbench_protocol.py`)

Per-row derived boolean:

- `directional_correct = 1 if argmax(probabilities) == ground_truth else 0`

Summary block (additive):

- `directional_accuracy.overall`
- `directional_accuracy.by_condition` (`A`, `B`, `C`)
- `directional_accuracy.delta`
  - `A_to_B = acc(B) - acc(A)`
  - `A_to_C = acc(C) - acc(A)`
  - `B_to_C = acc(C) - acc(B)`

This keeps directional deltas sign-consistent with “positive means destination condition improves accuracy.”

## Data Flow

1. Build condition matrix (`events × A/B/C × repeats`) unchanged.
2. Execute unit:
   - A: no subprocess; evaluate from seed-only evidence.
   - B/C: simulation subprocess + evidence from simulation log + seed.
3. Evaluator normalizes `probabilities` and `mcq_dimensions`, computes canonical scales.
4. Orchestrator enforces payload validity and writes additive fields (`simulation_executed`, rubric artifacts).
5. Summary computes existing Brier/lift plus directional accuracy block.

## Error Handling

1. Condition A no-sim path exceptions remain isolated to unit-level failure.
2. Any invalid canonical scale values/keys/ranges are `evaluation_failed`.
3. Any invalid probability payload (including non-finite values, non-positive mass) remains `evaluation_failed`.
4. Only completed units contribute to Brier and directional summary aggregates.

## Testing Strategy

### Orchestrator / Protocol Tests

1. Condition A does not call simulation subprocess.
2. Condition A success path yields completed row and `simulation_executed=False`.
3. B/C still execute simulation subprocess (`simulation_executed=True`).
4. A/B/C unit lifecycle semantics remain explicit (`simulation_failed`, `evaluation_failed`, completed).

### Evaluator / Scoring Tests

1. Canonical scales computed deterministically from MCQ distributions.
2. Canonical scale keys are exact; malformed keys fail validation.
3. Canonical scale values enforce finite numeric `[0,1]`.
4. Weighted aggregate uses confirmed weights (`0.25 + 6 × 0.125`).
5. Directional accuracy summary fields computed correctly from top-1 outcomes.

### Regression Gate

Run benchmark-focused suite:

- `tests/test_benchmark_protocol.py`
- `tests/test_benchmark_evaluator_scoring.py`
- `tests/test_benchmark_role_router.py`
- `tests/test_benchmark_orchestrator.py`
- `tests/test_run_ecnbench_protocol.py`
- `tests/test_api_status.py`

## Compatibility Contract

1. Existing Brier summary and lift fields remain present and behaviorally stable.
2. Existing row fields remain; new fields are additive.
3. Run metadata keeps `workflow_mode: "abc-per-event"` and retains per-unit traceability (`unit_id`).

## Success Criteria

1. Condition A is a true No-Sim baseline in execution behavior.
2. `validated_scales` is semantically deterministic and strictly canonical.
3. Directional accuracy is emitted in summary outputs and test-covered.
4. Existing benchmark regression suite remains green.

