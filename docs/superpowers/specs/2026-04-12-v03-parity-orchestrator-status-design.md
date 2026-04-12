# v0.3 Parity Design: ECN-BENCH Orchestrator Extraction + `/api/status`

## Problem Statement

The current codebase is **partially aligned** with the project plan:

- Core architecture and benchmark primitives exist (Neo4j/Ollama-local stack, `GraphStorage` + `Neo4jStorage`, role router, Brier scoring, 5-step UI flow).
- Key v0.3-oriented gaps remain:
  - No roadmap-level `/api/status` endpoint.
  - No reusable `BenchmarkRunOrchestrator` / `ConditionExecutor` classes (logic is largely procedural in `scripts/run_ecnbench_protocol.py`).

This design closes those core parity gaps while preserving current benchmark behavior and output contracts.

## Scope

### In Scope

1. Extract reusable ECN-BENCH orchestration classes:
   - `BenchmarkRunOrchestrator`
   - `ConditionExecutor`
2. Keep `backend/scripts/run_ecnbench_protocol.py` as a thin CLI wrapper.
3. Add `/api/status` endpoint with roadmap-minimum health fields:
   - Neo4j connectivity
   - Ollama model availability
   - Disk usage
4. Preserve existing benchmark artifact contract and semantics.

### Out of Scope (Explicitly Deferred)

1. Rich rubric-level benchmark dimensions beyond current scoring surface.
2. Long-term roadmap features: auth/multi-user, plugin system, graph versioning.
3. Broad refactors across unrelated app surfaces.

## Recommended Approach

Use **incremental extraction**:

1. Keep existing protocol helpers and data contracts.
2. Move run lifecycle responsibilities into focused classes in `backend/app/benchmarks/`.
3. Leave script entrypoint responsibilities limited to argument parsing and dependency wiring.
4. Add a small health endpoint module for `/api/status`.

This minimizes migration risk and keeps behavior stable.

## Architecture

### 1. `ConditionExecutor` (new, reusable)

**Responsibility:** execute one benchmark unit `(event, condition, repeat)`.

Core operations:

1. Build per-unit simulation config (including step-30 perturbation for B/C via existing loader/protocol helpers).
2. Run simulation subprocess with existing benchmark model routing.
3. Build evaluation evidence text and call probability evaluator.
4. Return normalized unit result payload and trace events.

Expected output shape (conceptual):

- `simulation_status`
- `simulation_completed`
- `evaluation_completed`
- `probabilities` (if available)
- `brier` (if available)
- `error` (if failed)
- unit metadata (`event_id`, `condition`, `repeat`, `seed_file`)

### 2. `BenchmarkRunOrchestrator` (new, reusable)

**Responsibility:** own full run lifecycle.

Core operations:

1. Initialize run directory, trace writer, and manifest.
2. Build condition matrix from events × A/B/C × repeats.
3. For each matrix row, call `ConditionExecutor.execute(...)`.
4. Append row results, persist trace records, and maintain fault isolation.
5. Write `event_results.json` and aggregate `summary.json`.

### 3. CLI wrapper (`scripts/run_ecnbench_protocol.py`)

After extraction, script retains:

1. argument parsing
2. dependency construction (`BenchmarkRoleRouter`, injections, events, seeds/profiles, output paths)
3. single orchestrator call

No business logic duplication between script and class layer.

### 4. `/api/status` endpoint (new API module)

Add a dedicated route under existing API registration so users can call:

- `GET /api/status`

Minimal response contract:

```json
{
  "success": true,
  "data": {
    "neo4j": { "connected": true, "error": null },
    "ollama": {
      "reachable": true,
      "model_configured": "qwen2.5:32b",
      "model_available": true,
      "error": null
    },
    "disk": {
      "path": "C:\\",
      "total_bytes": 0,
      "used_bytes": 0,
      "free_bytes": 0
    },
    "timestamp_utc": "2026-04-12T00:00:00Z"
  }
}
```

## Data Flow

1. CLI resolves config and IO paths.
2. CLI builds orchestrator and invokes `run(...)`.
3. Orchestrator prepares run metadata and iterates matrix rows.
4. Executor runs one unit and returns structured result.
5. Orchestrator persists row, trace events, and final summaries.
6. Existing consumers continue reading unchanged artifact files.

## Error Handling Model

1. **Run-unit fault isolation:** one failed unit does not abort full run.
2. **Explicit status signaling:** preserve `simulation_failed`, `evaluation_failed`, `completed`.
3. **Protocol integrity enforcement:** continue hard checks via existing protocol/injection validators.
4. **Status endpoint resilience:** return per-subsystem health with errors; do not silently report overall success.

## Compatibility Requirements

1. Keep artifact filenames and key JSON field names stable:
   - `run_manifest.json`
   - `event_results.json`
   - `summary.json`
   - `traces/execution.jsonl`
2. Preserve current scoring semantics (Brier + condition summary/lift).
3. No behavior changes to non-benchmark APIs.

## Testing Strategy

1. Unit tests for `ConditionExecutor`:
   - success path
   - subprocess timeout / non-zero exit
   - evaluator failure path
2. Unit tests for `BenchmarkRunOrchestrator`:
   - matrix execution
   - aggregation counters
   - summary/trace persistence
3. API tests for `/api/status`:
   - healthy dependencies
   - Neo4j down
   - Ollama/model unavailable
4. Regression tests:
   - CLI still writes expected artifacts with existing schema expectations.

## Extension Points for Deferred Metrics

To support richer future benchmark dimensions without breaking current consumers:

1. `ConditionExecutor` returns structured result objects with room for additional metric fields.
2. `BenchmarkRunOrchestrator` accepts pluggable summarizers in future revisions.
3. Current summary output remains unchanged for compatibility.

## Success Criteria

1. `/api/status` is available and reports roadmap-minimum health fields.
2. Protocol execution logic is reusable via orchestrator classes in `backend/app/benchmarks`.
3. Existing benchmark artifact contract and behavior are preserved.
4. Advanced metric depth remains deferred, but extension hooks are explicit.

