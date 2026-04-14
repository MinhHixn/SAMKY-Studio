# ECN-BENCH Core Scoring Contract Design (Validity Upgrade)

## Problem

Current ECN-BENCH benchmark outputs preserve A/B/C protocol and artifact stability, but several validity-critical requirements are still missing:

1. Pre-registered dimension weights and explicit composite score calculation.
2. Direction-aware susceptibility semantics (`pro_YES` / `anti_YES`) instead of magnitude-only deltas.
3. Fixed MCQ prompt contract externalized from inline evaluator prompt text.
4. Reliability gating for evaluator instability (Cohen's kappa thresholding).
5. Additional statistical and baseline outputs needed for claim strength.

This design keeps all non-negotiables unchanged while adding an additive, compatibility-safe scoring contract.

## Non-Negotiables (Locked)

1. Keep 3-condition design: A (No-Sim), B (With-Sim), C (Null Injection).
2. Keep identical seed + ReportAgent protocol + `workflow_mode: "abc-per-event"` across conditions.
3. Continue using Polymarket as resolved-question curation source, not direct competitor.
4. Preserve artifact files:
   - `run_manifest.json`
   - `traces/execution.jsonl`
   - `event_results.json`
   - `summary.json`
5. Keep deterministic benchmark mode active (`BENCHMARK_MODE=true`, temperature `0.0`, seed `42`).

## Scope and Decomposition

This request spans multiple subsystems. We implement in layered slices while preserving behavior at each layer:

- **Slice A (core scoring contract):** weights config, prompt registry, signed susceptibility, composite score, schema-compatible outputs.
- **Slice B (telemetry/statistics):** round-JSD checkpoints, RPS, calibration curves, effect-size CI, power-analysis block.
- **Slice C (reliability/leakage gates):** evaluator kappa gating, leakage preflight and manifest logging.
- **Optional slice:** delta-conformity, entropy + embedding diversity, topology sensitivity metadata.

This spec defines the full contract and boundaries. Implementation planning starts with Slice A.

## Architecture

### 1) Contract and Prompt Registry

Add file-backed registries:

- `backend/config/benchmark_weights_v1.json`
- `backend/prompts/ecnbench_mcq_v1.yaml`

Evaluator prompt assembly consumes prompt YAML directly (no hidden inline wording drift). Existing internal dimension keys stay unchanged:

- `prediction_accuracy`
- `polarization`
- `herd_effect`
- `deliberation_quality` (DQI concept maps here)
- `susceptibility`
- `convergence`
- `information_diversity`

### 2) Seed Metadata Contract

Attach metadata per seed folder (`data/seeds/<event_id>/metadata.json`):

- `event_id`
- `injection_direction` (`pro_YES` or `anti_YES`)
- `seed_snapshot_at` (used in leakage timing checks)
- optional metadata for auditing

### 3) Telemetry and Statistics Layer

Add pure metric calculators (no orchestration rewrites) for:

- checkpoint distributions
- JSD sequences
- RPS
- baseline scoring
- effect size + confidence intervals
- calibration bins

### 4) Reliability and Gating Layer

For each dimension, evaluate MCQ twice at temperature 0 and compute Cohen's kappa.

- If `kappa < 0.80`, mark dimension noisy.
- Exclude noisy dimensions from composite score.
- Renormalize stable weights to sum to 1.0.

## Data Contract Additions (Additive)

### New Files

1. `backend/config/benchmark_weights_v1.json`
2. `backend/prompts/ecnbench_mcq_v1.yaml`
3. `data/seeds/<event_id>/metadata.json`

### `run_manifest.json` (additive fields)

- `weights_schema_version`
- `mcq_prompt_version`
- `deterministic_mode` snapshot:
  - `benchmark_mode`
  - `temperature`
  - `seed`
- `leakage_check: "pass"` when preflight passes (otherwise run hard-fails before execution)

### `event_results.json` (additive fields)

- `round_jsd`: `[r1, r2, r3, r4, r5]` (checkpoints `[12,24,36,48,60]`)
- `convergence_monotonic`: boolean
- `injection_direction`
- `signed_delta`
- `belief_update_failure`
- `rps`
- `baseline_scores`:
  - `no_sim`
  - `uniform_random`
  - `market_prior`
- evaluator reliability support fields as needed for summary joins

### `summary.json` (additive fields)

- `composite_score`
- `composite_score_details` (included/excluded dimensions, renormalized weights)
- `evaluator_reliability` (per-dimension kappa, noisy dimensions list)
- `power_analysis` (dynamic from `events_loaded`, target `ΔBrier=0.05`)
- `effect_sizes` (A→B Cohen's d with 95% CI)
- `rps_summary`
- `calibration_curve` (4 brackets)

Existing fields remain unchanged.

## Metric Definitions

### 1) Composite Score

Let `S` be stable dimensions (`kappa >= 0.80`).

1. Base weights from `benchmark_weights_v1.json`.
2. Renormalize stable weights:
   - `w'_i = w_i / Σ_{j in S} w_j`
3. Compute:
   - `composite_score = Σ_{i in S} (w'_i * normalized_score_i)`

### 2) Convergence Trace (DeGroot-aligned operationalization)

Use five checkpoints from current 60-round simulation:

- rounds: `12, 24, 36, 48, 60`

At each checkpoint, build `P_round(outcome)` and compute:

- `JSD(P_round || Uniform)`

Persist `round_jsd = [jsd_12, jsd_24, jsd_36, jsd_48, jsd_60]`.

Set `convergence_monotonic = true` iff sequence is non-increasing.

### 3) Injection Direction Validity

From per-seed `injection_direction`:

- `direction_sign = +1` for `pro_YES`
- `direction_sign = -1` for `anti_YES`

Compute:

- `signed_delta = direction_sign * (P(YES)_B - P(YES)_C)`

Flag:

- `belief_update_failure = true` when movement is opposite expected direction.

### 4) Secondary Proper Scoring / Statistics

- Add `RPS` (Ranked Probability Score) alongside Brier.
- Report A→B effect size with Cohen's d and 95% CI (no point estimate alone).
- Build 4-bin calibration curve: predicted probability vs empirical frequency.

### 5) Baselines

Add baseline scorers:

1. `UniformRandomAgent` (uniform over outcomes)
2. `MarketPriorAgent` (opening-price priors from `events_raw.json`)
3. Existing `No-Sim` condition

Policy: if opening priors are missing for any selected event, fail preflight.

## Leakage Preflight

Preflight checks before run:

1. Seed snapshot date must be at least 7 days before event resolution.
2. Seed content must pass regex-based leakage keyword blocking.

Any failure aborts run. Passing runs set `leakage_check: "pass"` in manifest.

## Error Handling

1. Missing/invalid prompt or weight files: hard fail preflight.
2. Missing seed metadata or invalid `injection_direction`: hard fail preflight.
3. Missing market priors for selected events: hard fail preflight.
4. Leakage violation: hard fail preflight.
5. Per-unit simulation/evaluator failures remain isolated as currently designed.

## Testing Strategy

1. Unit tests:
   - composite renormalization and exclusion logic
   - signed susceptibility + belief-update-failure
   - JSD checkpoint vector calculation
   - RPS scoring
2. Contract tests:
   - prompt YAML parser and schema
   - weights JSON parser and sum/keys validation
   - seed metadata loader validation
3. Protocol integration tests:
   - additive fields in `run_manifest.json`, `event_results.json`, `summary.json`
   - existing artifact and key compatibility
4. Preflight tests:
   - missing metadata
   - missing market priors
   - leakage regex hit

## Success Criteria

1. Composite score is computed from pre-registered weights with reliability gating and renormalization.
2. Susceptibility is direction-aware (`signed_delta`) with explicit failure flags.
3. Evaluator uses fixed prompt contract from YAML.
4. Summary includes effect-size/CI and proper uncertainty blocks (not point-only).
5. Baseline comparisons and leakage checks are first-class, auditable outputs.
6. Existing A/B/C workflow and artifact structure remain intact.

