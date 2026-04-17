# Phase 0 Minimal Setup Design (60 Agents, 30 Rounds, 1 Event)

## Context

The goal is to run a constrained Phase 0 protocol test in this repository with:

- 60 agents
- 30 rounds
- 1 event
- Neo4j required
- Ollama endpoint at `http://localhost:11434/v1`
- Same model for graph/benchmark/evaluator: `gemini-3-flash-preview:cloud`

This should use existing protocol and routing code paths, with no new feature development.

## Design summary

Use `run_ecnbench_protocol.py` in `DEV_MINIMAL_MODE` with explicit runtime overrides and benchmark role-router variables. Keep strict telemetry enabled so Neo4j connectivity is mandatory.

## Configuration design

Set these environment variables for the run:

```env
OPENROUTER_API_KEY=ollama
OPENROUTER_BASE_URL=http://localhost:11434/v1
OPENROUTER_GRAPH_MODEL=gemini-3-flash-preview:cloud
OPENROUTER_BENCHMARK_MODEL=gemini-3-flash-preview:cloud
OPENROUTER_EVALUATOR_MODEL=gemini-3-flash-preview:cloud

DEV_MINIMAL_MODE=true
DEV_MINIMAL_AGENT_COUNT=60
DEV_MINIMAL_MAX_STEPS=30

BENCHMARK_MODE=true
TELEMETRY_REQUIRED=true
```

Protocol CLI arguments:

- `--events 1`
- `--repeats 1`

## Execution design

Run protocol from `backend`:

```powershell
uv run python scripts\run_ecnbench_protocol.py `
  --seeds-dir ..\..\data\seeds `
  --events-raw ..\..\data\events_raw.json `
  --injection-bank ..\..\data\injections\step30_injection_bank.json `
  --output-dir logs\benchmark_runs `
  --events 1 `
  --repeats 1
```

## Validation design

Verify in order:

1. Ollama endpoint reachable at `http://localhost:11434/v1`
2. Neo4j reachable at `bolt://localhost:7687`
3. Run output created under `backend\logs\benchmark_runs\<run_id>\`
4. Artifacts include:
   - `run_manifest.json`
   - `event_results.json`
   - `summary.json`

Expected manifest/runtime values:

- `events_loaded = 1`
- `repeats = 1`
- `total_agents = 60`
- `total_simulation_hours = 30`

## Risks and handling

1. Model availability risk: `gemini-3-flash-preview:cloud` may not exist on local Ollama registry.
   - Handling: keep requested model as configured; if runtime fails on model-not-found, switch all three role vars to an installed Ollama model.
2. Neo4j dependency risk: strict telemetry mode blocks runs if Neo4j is unreachable.
   - Handling: keep `TELEMETRY_REQUIRED=true`; treat any connectivity failure as setup failure.

## Scope boundaries

In scope:

- Environment variable setup for this run profile
- Single run execution profile (`1 event`, `1 repeat`, `60/30`)
- Validation checks and artifact confirmation

Out of scope:

- Protocol code changes
- Benchmark methodology changes
- New role-routing features

