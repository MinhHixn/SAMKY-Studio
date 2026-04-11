# ECN-BENCH Protocol-Completion Prototype (OpenRouter) — Design

## Problem Statement

The current codebase is a strong simulation foundation but does not yet execute the ECN-BENCH protocol end-to-end. Missing benchmark-critical behavior includes condition orchestration (A/B/C), hard protocol enforcement (3,000 agents, 60 steps, mandatory step-30 perturbation in B/C), evaluator-driven probability scoring, and clear per-event benchmark outputs.

This design adds a benchmark wrapper pipeline around existing services/scripts so the prototype can run ECN-BENCH-style experiments for one benchmarked model via OpenRouter, with strict model-role separation.

## Scope

### In Scope (v1)

1. End-to-end benchmark command for 30 events.
2. A/B/C condition orchestration with strict parity in prompt/evaluation chain.
3. Hard enforcement of:
   - exactly 3,000 agents
   - exactly 60 steps
   - mandatory step-30 injection for B/C
4. Strict model-role routing:
   - Graph extraction: `nvidia/nemotron-3-super-120b-a12b:free`
   - Benchmarked simulation model: `minimax/minimax-m2.5:free`
   - Evaluator/scorer model: `google/gemma-4-31b-it:free`
5. Evaluator output as outcome probability distribution and Brier scoring pipeline.
6. Clear per-event outputs for each full event simulation.
7. Resilient OpenRouter rate-limit handling (429 exponential backoff with jitter).

### Out of Scope (v1)

1. 7-dimension qualitative rubric scoring.
2. Multi-benchmarked-model leaderboard orchestration.
3. Major refactor of existing API product surface.

## High-Level Approach

Use a **Protocol Wrapper**: add benchmark-specific orchestration modules that call existing simulation/report pathways, rather than rewriting core simulation internals.

Benefits:
1. Lower implementation risk.
2. Preserves current app behavior for non-benchmark flows.
3. Enables strict benchmark controls in one dedicated pipeline.

## Architecture

### 1. BenchmarkRunOrchestrator

Coordinates the full matrix:
- events (30) × conditions (A/B/C) × repeats (default 1)

Responsibilities:
1. Build run manifest with immutable protocol settings.
2. Enforce protocol constraints before each run unit.
3. Dispatch condition execution.
4. Trigger evaluator and scoring stages.
5. Emit final artifacts and summary.

### 2. ConditionExecutor

Runs one `(event, condition, repeat)` unit.

Responsibilities:
1. Build condition-specific config from shared base config.
2. Execute full simulation run (no partial shortcuts).
3. Ensure Condition A uses identical pipeline as B/C minus perturbation application.
4. Ensure B/C apply only the perturbation difference at step 30.

### 3. InjectionLoader

Loads `data/injections/step30_injection_bank.json`.

Responsibilities:
1. Resolve event-specific relevant/null payloads.
2. Validate payload presence and shape.
3. Hard-fail run unit if required payload is absent or invalid.

### 4. LLMRoleRouter

Provides role-specific `LLMClient` instances and prevents role mixing.

Responsibilities:
1. Read role model config.
2. Validate all required role-model mappings at startup.
3. Inject proper client into:
   - graph extraction path (NER/structured extraction)
   - simulation benchmark path
   - evaluator path

### 5. EvaluatorClient

Calls evaluator model to output outcome probabilities for each completed run unit.

Responsibilities:
1. Normalize probability distribution.
2. Return evaluator metadata (top outcome, confidence, rationale summary).
3. Fail explicitly when output is malformed.

### 6. ScoringEngine

Computes benchmark metrics from evaluator outputs and ground truth.

Responsibilities:
1. Per event × condition Brier score.
2. Per condition aggregate Brier mean.
3. Lift/delta metrics for A→B, A→C, B→C.

### 7. ArtifactWriter

Writes reproducible run outputs.

Responsibilities:
1. Persist run manifest, traces, per-event results, summary.
2. Record explicit failure records with structured error codes.

## Protocol Semantics

## Conditions

1. **A (Control):** identical prompt/evaluation chain, no simulation perturbation at step 30.
2. **B (Relevant):** apply event-relevant perturbation at step 30.
3. **C (Null):** apply null perturbation at step 30.

## Hard Constraints

All run units must satisfy:
1. `agent_count == 3000`
2. `max_steps == 60`
3. `step30_injection_present == true` for B/C

Any violation marks that run unit as failed with explicit error metadata; no silent fallback.

## Model Routing & Config Surface

Introduce explicit role-based settings in config/environment:

1. `OPENROUTER_API_KEY` (secret, env only)
2. `OPENROUTER_BASE_URL` (default `https://openrouter.ai/api/v1`)
3. `OPENROUTER_GRAPH_MODEL`
4. `OPENROUTER_BENCHMARK_MODEL`
5. `OPENROUTER_EVALUATOR_MODEL`
6. Optional metadata headers (`OPENROUTER_HTTP_REFERER`, `OPENROUTER_X_TITLE`)

Validation behavior:
1. Missing required role model config fails startup for benchmark command.
2. Role model mismatch is not auto-corrected.

## End-to-End Command

Add one CLI benchmark entrypoint (script), e.g.:

```bash
python backend/scripts/run_ecnbench_protocol.py --events 30 --repeats 1
```

Behavior:
1. Loads benchmark events and ground truth.
2. Runs full simulation for each event in A/B/C (and repeat loop if set).
3. Runs evaluator stage per completed run unit.
4. Writes per-event outputs and aggregate summary.

## Artifact Contract

Output directory:

`benchmark_runs/<run_id>/`

Files:
1. `run_manifest.json` — immutable run config, model-role mapping, event list.
2. `traces/execution.jsonl` — run lifecycle trace entries.
3. `event_results.json` — per-event, per-condition:
   - run status
   - evaluator probabilities
   - Brier score
   - failure metadata if failed
4. `summary.json` — aggregate condition metrics, lift, completion/failure counts.

Per-event clarity requirement:
Each event must have an explicit record showing:
1. whether all A/B/C full simulations completed
2. per-condition probability distribution
3. per-condition Brier result (or explicit failure reason)

## Rate Limiting & Reliability

OpenRouter free models may return 429 due to shared RPM limits.

Required behavior:
1. Retry on 429 with exponential backoff + jitter.
2. Retry on transient transport/5xx errors using same retry policy class.
3. Use bounded max retries and emit structured failure once exhausted.
4. Do not swallow final failures.

Backoff policy baseline:
1. attempt delay = `base * 2^attempt + random_jitter`
2. configurable base and max retries via env/config
3. evaluator and benchmark stages both use this policy

## Error Handling Model

1. **Run-unit level fault isolation:** one failed event-condition-repeat does not abort the full benchmark run.
2. **Protocol integrity faults:** missing mandatory injection for B/C fails that unit immediately.
3. **Output integrity faults:** malformed evaluator distribution fails scoring for that unit.
4. **Summary integrity:** aggregate metrics computed only from valid completed units; failed units are counted and listed.

## Testing Strategy

1. Unit tests:
   - role router config validation
   - injection loader validation/error paths
   - protocol constraint enforcement
   - evaluator output normalization
   - Brier scorer correctness
   - retry/backoff trigger behavior for 429
2. Integration tests:
   - one synthetic event through A/B/C pipeline
   - artifact schema validation
   - failure-path persistence in outputs
3. Regression tests:
   - existing simulation scripts remain operational in non-benchmark mode

## Success Criteria

1. Single command runs 30-event prototype benchmark with A/B/C conditions.
2. Strict model-role split is enforced for graph/benchmark/evaluator.
3. Hard protocol constraints are enforced and auditable in artifacts.
4. Per-event outputs clearly show completion, probabilities, and Brier by condition.
5. 429 rate limits are handled with exponential backoff and explicit bounded retry behavior.
