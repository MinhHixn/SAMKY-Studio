# ECN-BENCH Rubric Evaluator Contract (Additive) Design

## Problem

Current code precisely supports MVP evaluation (`probabilities -> Brier -> condition lift`), but does not yet encode the KnowledgeBase v3.0 rubric depth:

1. 7 MCQ dimensions with explicit per-dimension probability buckets.
2. Validated scales persisted in run artifacts.
3. Formalized protocol parity checks for Condition A/B/C rubric schema consistency.

## Decisions (Confirmed)

1. Keep A/B/C workflow and current Brier/lift outputs unchanged.
2. Use additive dual-surface evaluator output (no breaking schema).
3. Implement strict rubric schema now; defer weighted aggregate rubric scoring formulas.
4. MCQ bucket schema per dimension is fixed to:
   - `very_low`
   - `low`
   - `high`
   - `very_high`
5. `validated_scales` is strict and persisted now, but not yet included in weighted aggregate scoring.
6. Condition A parity guard is hard-fail at evaluation stage when rubric schema contract is violated.

## Scope

### In Scope

1. Add strict evaluator contract fields:
   - `probabilities` (legacy; retained)
   - `mcq_dimensions` (new; strict)
   - `validated_scales` (new; strict persistence)
2. Validate and normalize per-dimension 4-bucket mappings.
3. Persist rubric artifacts in per-unit results.
4. Add parity checks so A/B/C use the same rubric schema contract.
5. Keep existing scoring contract and consumers backward-compatible.

### Out of Scope

1. Weighted 7-dimension aggregate scoring formulas.
2. Replacing current Brier/lift summary as the primary computed output.
3. Changing benchmark run topology (must remain events × A/B/C × repeats).

## Architecture

### 1) Evaluator Contract Layer (`backend/app/benchmarks/evaluator.py`)

Extend evaluator output contract from:

- `probabilities`

to:

- `probabilities`
- `mcq_dimensions`
- `validated_scales`

Validation rules:

1. `probabilities` remains strict as today (non-empty, finite, non-negative, normalized).
2. `mcq_dimensions` must include exactly 7 required dimensions with non-empty string keys mapped from canonical dimension IDs.
3. Each dimension must include exactly the 4 required buckets (`very_low`, `low`, `high`, `very_high`), finite non-negative numeric values, total mass > 0, normalized to sum 1.
4. `validated_scales` must be a strict object with required shape:
   - `schema_version` (non-empty string)
   - `scores` (non-empty mapping of non-empty string keys to finite numeric values)

Output keeps both normalized legacy probabilities and normalized per-dimension bucket mappings.

### 2) Protocol Runner Layer (`backend/scripts/run_ecnbench_protocol.py`)

1. Extend per-unit row payload to include:
   - `mcq_dimensions`
   - `validated_scales`
2. Preserve existing row keys (`probabilities`, `brier`, statuses, etc.).
3. Preserve existing summary behavior (completed rows only for Brier/lift).
4. Enforce rubric schema parity contract in evaluation path:
   - if evaluator output does not satisfy schema, unit becomes `evaluation_failed`.

### 3) Scoring Layer (`backend/app/benchmarks/scoring.py`)

1. Leave existing `brier_score` and `summarize_condition_scores` unchanged.
2. Add additive rubric helper(s) for persistence/summary scaffolding only (no weighted aggregate formula yet).

## Data Flow

1. Executor completes simulation unit.
2. Evaluator returns contract payload with legacy + rubric surfaces.
3. Validation/normalization runs in evaluator layer.
4. Protocol row stores both legacy and rubric fields.
5. Existing summary computes condition means/lift from legacy Brier fields.
6. Rubric artifacts remain available in row-level outputs for future weighted pipeline.

## Error Handling

1. Any rubric schema violation is an evaluation contract error.
2. Contract errors mark the unit as `evaluation_failed` with explicit error text.
3. Run-unit fault isolation is preserved: one failed unit does not abort the run.
4. Legacy Brier summary remains computed only from fully completed units.

## Testing Strategy

### Evaluator Tests

1. Accept valid `mcq_dimensions` with all 7 dimensions and 4 buckets each.
2. Reject missing dimension.
3. Reject missing bucket.
4. Reject non-finite / negative values.
5. Reject zero total mass per dimension.
6. Verify normalization per dimension sums to 1.
7. Verify strict `validated_scales` shape checks (`schema_version` + non-empty numeric `scores` mapping).

### Protocol Tests

1. Result rows include `mcq_dimensions` and `validated_scales`.
2. Legacy fields still present and valid (`probabilities`, `brier`, statuses).
3. Schema mismatch produces `evaluation_failed`.
4. Existing artifact files and summary shape remain backward-compatible.

### Scoring Tests

1. Existing Brier/lift tests remain unchanged and passing.
2. New rubric helper tests verify additive behavior without weighted aggregate dependencies.

## Compatibility Contract

1. Additive-only schema evolution.
2. Existing integrations using legacy fields continue to work unchanged.
3. A/B/C per-event topology remains unchanged.

## Success Criteria

1. Strict 7-dimension rubric schema is enforced in code.
2. `validated_scales` is strictly validated and persisted in unit outputs.
3. Condition A/B/C rubric contract parity violations fail units as `evaluation_failed`.
4. Existing Brier/lift summaries remain stable and backward-compatible.
5. Weighted aggregate rubric scoring remains explicitly deferred for next iteration.

