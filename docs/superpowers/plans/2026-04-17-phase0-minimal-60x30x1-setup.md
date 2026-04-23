# Phase 0 Minimal 60x30x1 Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure and run one successful Phase 0 minimal protocol execution with 60 agents, 30 rounds, 1 event, strict Neo4j telemetry, and triple-role model routing to `gemini-3-flash-preview:cloud`.

**Architecture:** Use existing runtime controls in `backend/scripts/run_ecnbench_protocol.py` (`DEV_MINIMAL_MODE`, `DEV_MINIMAL_AGENT_COUNT`, `DEV_MINIMAL_MAX_STEPS`, `--events`, `--repeats`) and existing benchmark role router env vars (`OPENROUTER_*`). Do not modify protocol code. Validate setup through preflight checks and output artifact verification (`run_manifest.json`, `event_results.json`, `summary.json`).

**Tech Stack:** Python 3.11+, uv, Flask backend scripts, Neo4j, Ollama OpenAI-compatible endpoint, PowerShell.

---

## File structure and responsibilities

- Modify: `.env` (local runtime configuration only; do not commit secrets)
- Use: `backend/scripts/run_ecnbench_protocol.py` (protocol entrypoint)
- Read: `backend/logs/benchmark_runs/<run_id>/run_manifest.json` (runtime truth)
- Read: `backend/logs/benchmark_runs/<run_id>/event_results.json` (per-unit outcomes)
- Read: `backend/logs/benchmark_runs/<run_id>/summary.json` (aggregate results)

No production code changes are planned.

### Task 1: Preflight tooling and service readiness

**Files:**
- Modify: `.env` (confirm file exists from `.env.example`)
- Test: N/A (service checks via commands)

- [ ] **Step 1: Verify local toolchain commands exist**

Run:

```powershell
uv --version
python --version
node --version
docker --version
```

Expected: each command prints a version and exits `0`.

- [ ] **Step 2: Verify Ollama endpoint is reachable**

Run:

```powershell
Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get | ConvertTo-Json -Depth 5
```

Expected: JSON object with a `models` array.

- [ ] **Step 3: Verify Neo4j bolt socket is reachable**

Run:

```powershell
Test-NetConnection -ComputerName localhost -Port 7687
```

Expected: `TcpTestSucceeded : True`.

- [ ] **Step 4: Commit**

No commit for this task (runtime checks only).

### Task 2: Configure Phase 0 minimal 60x30x1 environment

**Files:**
- Modify: `.env`
- Test: `backend/scripts/run_ecnbench_protocol.py` argument/env preflight

- [ ] **Step 1: Write the configuration block in `.env`**

Append/update the following keys in `.env`:

```env
OPENROUTER_API_KEY=ollama
OPENROUTER_BASE_URL=http://localhost:11434/v1
OPENROUTER_GRAPH_MODEL=gemini-3-flash-preview:cloud
OPENROUTER_BENCHMARK_MODEL=gemini-3-flash-preview:cloud
OPENROUTER_EVALUATOR_MODEL=gemini-3-flash-preview:cloud

DEV_MINIMAL_MODE=true
DEV_MINIMAL_AGENT_COUNT=60
DEV_MINIMAL_MAX_STEPS=30
DEV_MINIMAL_INJECTION_STEP=15

BENCHMARK_MODE=true
TELEMETRY_REQUIRED=true
```

- [ ] **Step 2: Run a role-router preflight to verify required vars are present**

Run from `backend`:

```powershell
uv run python -c "from app.benchmarks.role_router import BenchmarkRoleRouter; r=BenchmarkRoleRouter.from_config(); print(r.model_for('graph')); print(r.model_for('benchmark')); print(r.model_for('evaluator'))"
```

Expected: prints `gemini-3-flash-preview:cloud` three times without exception.

- [ ] **Step 3: Verify config values are loaded by runtime config**

Run from `backend`:

```powershell
uv run python -c "from app.config import Config; print(Config.BENCHMARK_MODE, Config.NEO4J_URI)"
```

Expected: first value `True`; second value a valid bolt URI.

- [ ] **Step 4: Commit**

No commit for this task (`.env` is local machine config and may contain sensitive values).

### Task 3: Execute one protocol run (1 event, 1 repeat)

**Files:**
- Create: `backend/logs/benchmark_runs/<run_id>/...` (runtime artifacts)
- Modify: none in source tree
- Test: protocol execution command

- [ ] **Step 1: Run protocol command from `backend`**

```powershell
uv run python scripts\run_ecnbench_protocol.py `
  --seeds-dir ..\..\data\seeds `
  --events-raw ..\..\data\events_raw.json `
  --injection-bank ..\..\data\injections\step30_injection_bank.json `
  --output-dir logs\benchmark_runs `
  --events 1 `
  --repeats 1
```

Expected: command exits `0` and reports a completed run directory.

- [ ] **Step 2: Capture the latest run directory**

Run:

```powershell
$run = Get-ChildItem .\logs\benchmark_runs -Directory | Sort-Object LastWriteTime | Select-Object -Last 1
$run.FullName
```

Expected: prints a path like `...\backend\logs\benchmark_runs\ecnbench_<timestamp>`.

- [ ] **Step 3: Commit**

No commit for this task (runtime artifacts are generated outputs).

### Task 4: Validate outputs match 60x30x1 requirements

**Files:**
- Read: `backend/logs/benchmark_runs/<run_id>/run_manifest.json`
- Read: `backend/logs/benchmark_runs/<run_id>/event_results.json`
- Read: `backend/logs/benchmark_runs/<run_id>/summary.json`

- [ ] **Step 1: Validate manifest core fields**

Run (replace `$run` with latest run path):

```powershell
$manifest = Get-Content (Join-Path $run.FullName "run_manifest.json") | ConvertFrom-Json
$manifest.events_loaded
$manifest.repeats
$manifest.total_agents
$manifest.total_simulation_hours
```

Expected:
- `events_loaded` = `1`
- `repeats` = `1`
- `total_agents` = `60`
- `total_simulation_hours` = `30`

- [ ] **Step 2: Validate required artifact files exist**

Run:

```powershell
Test-Path (Join-Path $run.FullName "event_results.json")
Test-Path (Join-Path $run.FullName "summary.json")
```

Expected: both commands print `True`.

- [ ] **Step 3: Validate strict Neo4j telemetry was active**

Run:

```powershell
$manifest.telemetry_required
$manifest.neo4j_connected
```

Expected:
- `telemetry_required` = `True`
- `neo4j_connected` = `True`

- [ ] **Step 4: Commit**

No commit for this task (validation only).

### Task 5: Recovery path if requested model is unavailable

**Files:**
- Modify: `.env` (only if inference fails due to model availability)
- Re-run: `backend/scripts/run_ecnbench_protocol.py`

- [ ] **Step 1: Detect model-not-found failure from run output**

Look for error patterns indicating the model is not installed or not recognized by the endpoint.

- [ ] **Step 2: Swap all three role vars to an installed Ollama model**

Example fallback:

```env
OPENROUTER_GRAPH_MODEL=qwen2.5:14b
OPENROUTER_BENCHMARK_MODEL=qwen2.5:14b
OPENROUTER_EVALUATOR_MODEL=qwen2.5:14b
```

- [ ] **Step 3: Re-run Task 3 and Task 4**

Run the same protocol command and validation commands.

- [ ] **Step 4: Commit**

No commit for this task (`.env` local only).

---

## Self-review results

1. **Spec coverage:** covered runtime config, execution command, strict telemetry, 60/30/1 verification, and model-availability risk handling.
2. **Placeholder scan:** no `TODO`, `TBD`, or ambiguous deferred actions remain.
3. **Type/field consistency:** manifest fields (`events_loaded`, `repeats`, `total_agents`, `total_simulation_hours`, `telemetry_required`, `neo4j_connected`) are referenced consistently across tasks.
