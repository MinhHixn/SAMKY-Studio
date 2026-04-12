# A/B/C Workflow Continuation Design (Draft)

## Context

The continuation requirement is clarified: keep the current ECN-BENCH workflow as **A/B/C per event** and continue forward from the current implementation state.

This explicitly rejects a temporary pivot to a single-condition 30-run mode.

## Scope

### In Scope

1. Preserve benchmark run topology as `events × conditions(A,B,C) × repeats`.
2. Preserve single benchmark model per run via role routing.
3. Continue with existing CLI + orchestrator architecture:
   - `backend/scripts/run_ecnbench_protocol.py` as entrypoint
   - shared executor/orchestrator in `backend/app/benchmarks/orchestrator.py`
4. Continue hardening and verification work without changing protocol semantics.

### Out of Scope

1. Replacing A/B/C with one-condition pilot mode.
2. Redefining event-count semantics away from CLI-configured `--events`.
3. Any benchmark scoring-model redesign in this continuation step.

## Architecture and Components

1. **CLI Entrypoint:** Parses run args, resolves router/events/seeds/injections, passes run context to orchestrator.
2. **Role Router:** Keeps one benchmark model bound to the run for simulation units.
3. **Condition Matrix Builder:** Expands each event across A/B/C and repeats.
4. **Protocol Executor:** Executes each event-condition unit, captures traces/results/errors.
5. **Orchestrator:** Persists `run_manifest.json`, `event_results.json`, traces, and `summary.json`.

## Data Flow

1. Load `N` events (default `N=30`).
2. Build matrix over `(event_id, condition in A/B/C, repeat)`.
3. Execute each unit independently and collect row outputs.
4. Write run artifacts and summary from the collected rows.

## Reliability and Error Handling

1. Maintain run-unit fault isolation: one failed unit does not abort the full run.
2. Keep explicit status taxonomy and artifact schema stable.
3. Preserve traceability of failures via per-unit logs and trace rows.

## Testing and Validation

Primary continuation gate:

1. `test_benchmark_protocol.py`
2. `test_benchmark_evaluator_scoring.py`
3. `test_benchmark_role_router.py`
4. `test_benchmark_orchestrator.py`
5. `test_run_ecnbench_protocol.py`
6. `test_api_status.py`

Broader backend sweep is still run when environment dependencies are available.

## Success Criteria

1. Workflow remains A/B/C per event with no semantic drift.
2. Single benchmark model per run remains enforced.
3. Existing benchmark artifact contract remains intact.
4. Continuation work proceeds via planning and implementation without protocol topology changes.

