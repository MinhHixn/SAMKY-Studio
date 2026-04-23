<div align="center">

<img src="./static/image/mirofish-offline-banner.png" alt="MiroFish Offline" width="100%"/>

# MiroFish-Offline

**Local-first multi-agent simulation platform (Neo4j + Ollama + Flask + Vue).**

*Run document-to-simulation pipelines, social reaction simulations, and ECN-BENCH protocol experiments on your own infrastructure.*

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](./LICENSE)

</div>

## What this repository is

MiroFish-Offline is an English, self-hostable fork of MiroFish focused on:

1. **Local model execution** via Ollama (OpenAI-compatible endpoint).
2. **Local graph memory** via Neo4j Community.
3. **Benchmark and protocol tooling** for repeatable ECN-BENCH-style runs.

It supports day-to-day simulation workflows and benchmark automation in the same codebase.

## Current stack (as implemented)

| Layer | Technology |
|---|---|
| Backend API | Flask (`backend/run.py`, default `:5001`) |
| Frontend | Vue + Vite (`frontend`, default `:3000`) |
| Graph storage | Neo4j Community (`bolt://localhost:7687`) |
| LLM endpoint | Ollama OpenAI-compatible API (`http://localhost:11434/v1`) |
| Embeddings | Ollama embedding endpoint (`http://localhost:11434`) |
| Benchmark runner | `backend/scripts/run_ecnbench_protocol.py` |
| Role routing for benchmark | `backend/app/benchmarks/role_router.py` |

## High-level workflow

1. Ingest source material and build/update graph memory.
2. Run simulation rounds (Twitter/Reddit style) with persona populations.
3. Evaluate outcomes and collect benchmark traces/artifacts.
4. Generate report outputs from the resulting graph/simulation state.

## Updates today (2026-04-23)

- **Architecture v3.2: Epistemic Mapping Pipeline:**
  - **Dynamic Belief Probing:** Integrated a 3-tier micro-question protocol into the Post-Simulation evaluation phase to map the swarm's internal logic.
  - **Dynamic Prompt Injection:** The Evaluator LLM (Report Agent) now receives event-specific micro-questions and 4-bucket options injected directly into the system prompt.
  - **Structured Epistemic Output:** Enforced a strict JSON schema for the `micro_epistemic_mapping` field, capturing `dominant_tag` and `short_rationale` for every probed belief.
  - **Logic Verification:** Enabled "Grey-Box" evaluation, allowing researchers to verify if a swarm's macro-prediction is grounded in factually correct granular reasoning (e.g., cooling CPI leading to a Fed cut).

- **Architecture v3.1: Small Model Optimization:**
  - **Refactored Synthetic Expansion:** Subdivided agent generation into concurrent micro-batches (5 agents/request) using `asyncio` to bypass linear time-costs and environment timeouts.
  - **Fault-Tolerant JSON Parsing:** Integrated `json-repair` to automatically recover truncated or malformed JSON from smaller models (<15B parameters).
  - **Context Isolation (Persona Compression):** Implemented 4-axis metadata steering (Worldview, Motivation, Style, Biases) to compress 1,000-word biographies into high-signal tags, reducing prompt overhead by ~85%.
  - **Incremental Checkpointing:** Simulation state is now serialized to `logs/synthetic_expansion_checkpoint.json` after every batch, enabling instant resumption after timeouts.
  - **Universal Encoding Synchronization:** Explicitly enforced UTF-8 across all file I/O and injected `PRAGMA encoding = 'UTF-8';` into all SQLite database initializations.

## Updates (2026-04-17)

## Repository structure

```text
MiroFish-Offline/
|- backend/
|  |- app/
|  |  |- api/          # Flask API routes
|  |  |- benchmarks/   # ECN-BENCH orchestration, scoring, telemetry
|  |  |- services/     # report + simulation services
|  |  |- storage/      # Neo4j and graph storage implementation
|  |  |- utils/        # LLM client, tracing, helpers
|  |- scripts/         # protocol/simulation runners, local Neo4j starter
|  |- tests/           # backend test suite
|  |- run.py           # backend entrypoint
|  |- pyproject.toml   # python dependencies
|- frontend/
|  |- src/             # Vue application
|- docs/
|  |- superpowers/
|     |- plans/
|     |- specs/
|- docker-compose.yml
|- .env.example
```

## Quick start

### Prerequisites

- Node.js 18+
- Python 3.11+
- Neo4j 5.x
- Ollama

### Option A: one-command local dev (recommended)

From repo root:

```powershell
npm run setup:all
npm run dev
```

This runs:

- Backend at `http://localhost:5001`
- Frontend at `http://localhost:3000`

### Option B: Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up -d
```

Services exposed by default:

- Frontend: `3000`
- Backend: `5001`
- Neo4j Browser: `7474`
- Neo4j Bolt: `7687`
- Ollama: `11434`

## Configuration

**IMPORTANT:** The `.env` file must be located in the **project root** directory (`MiroFish-Offline/.env`). Do NOT create or modify a `.env` file inside the `backend/` directory, as the application strictly loads configuration from the root.

Copy `.env.example` to `.env` and update values as needed.

### Core local settings

```env
LLM_API_KEY=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL_NAME=qwen2.5:32b

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=mirofish

EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_BASE_URL=http://localhost:11434
```

### Triple-role benchmark routing on local Ollama

For ECN-BENCH protocol mode, role routing is configured with `OPENROUTER_*` variable names, but these can point to local Ollama directly:

```env
OPENROUTER_API_KEY=ollama
OPENROUTER_BASE_URL=http://localhost:11434/v1
OPENROUTER_GRAPH_MODEL=llama3.1:8b
OPENROUTER_BENCHMARK_MODEL=llama3.1:8b
OPENROUTER_EVALUATOR_MODEL=llama3.1:8b
BENCHMARK_MODE=true
```

`BENCHMARK_MODE=true` enforces deterministic benchmark parameters (temperature/seed) and headless behavior in protocol subprocesses.

### Optional cloud routing

If you intentionally want cloud routing, set `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1` and provide a real API key/models.

## Running the ECN-BENCH protocol

From `backend`:

```powershell
uv run python scripts\run_ecnbench_protocol.py `
  --seeds-dir ..\..\data\seeds `
  --events-raw ..\..\data\events_raw.json `
  --injection-bank ..\..\data\injections\step30_injection_bank.json `
  --output-dir logs\benchmark_runs `
  --events 30 `
  --repeats 1
```

### Filtering events

You can now filter which events to run by category or specific IDs:

**By category:**
Valid categories: `social_short`, `social_medium`, `tech_short`, `tech_medium`, `supplementary`.

```powershell
uv run python scripts\run_ecnbench_protocol.py `
  --seeds-dir ..\..\data\seeds `
  --events-raw ..\..\data\events_raw.json `
  --category tech_short
```

**By specific IDs:**
Provide a comma-separated list of event IDs.

```powershell
uv run python scripts\run_ecnbench_protocol.py `
  --seeds-dir ..\..\data\seeds `
  --events-raw ..\..\data\events_raw.json `
  --event-ids S3,T1,C1
```

Main output directory:

`backend\logs\benchmark_runs\<run_id>\`

Important artifacts:

- `run_manifest.json`
- `event_results.json`
- `summary.json`
- `traces\execution.jsonl` (default when `--trace-out` not provided)

### Phase-0 minimal OpenRouter run (60 agents, 30 rounds, 1 event)

**Definition:** A fast "smoke test" run designed to validate the entire pipeline end-to-end. It uses a reduced agent count ($N=60$) and truncated steps ($T=30$) with a single event, while still executing all three benchmark conditions (A, B, C).

#### Step 1: Prepare the Environment
Ensure you are using **Python 3.11**. If using a virtual environment (recommended):

```powershell
# From MiroFish-Offline/backend/
.\.venv311\Scripts\activate
```

#### Step 2: Start Infrastructure (Docker + Neo4j)
The simulation requires **Neo4j** for graph memory and telemetry. Use the provided helper script to ensure Docker is running and the container is ready:

```powershell
# From MiroFish-Offline/backend/
python scripts\start_neo4j_local.py --start-docker-desktop --wait-seconds 300
```

#### Step 3: Configure OpenRouter Models
Ensure your **root** `.env` file (`MiroFish-Offline/.env`) is configured for the research model (e.g., Gemma 4):

```env
OPENROUTER_API_KEY=<your_key>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_GRAPH_MODEL=google/gemma-4-26b-a4b-it
OPENROUTER_BENCHMARK_MODEL=google/gemma-4-26b-a4b-it
OPENROUTER_EVALUATOR_MODEL=google/gemma-4-26b-a4b-it
```

#### Step 4: Execute the Run
From `backend` in PowerShell:

```powershell
# Set runtime overrides
$env:BENCHMARK_MODE='true'
$env:DEV_MINIMAL_MODE='true'
$env:DEV_MINIMAL_AGENT_COUNT='60'
$env:DEV_MINIMAL_MAX_STEPS='30'
$env:DEV_MINIMAL_INJECTION_STEP='15'

# Start simulation
uv run python scripts\run_ecnbench_protocol.py `
  --seeds-dir ..\..\data\seeds `
  --events-raw ..\..\data\events_raw.json `
  --injection-bank ..\..\data\injections\step30_injection_bank.json `
  --output-dir logs\benchmark_runs `
  --event-ids S6 `
  --repeats 1
```

#### Step 5: Monitor & Verify
- **Logs:** Check `backend/logs/benchmark_runs/<run_id>/S6_B_r1/simulation.log` for real-time agent interactions.
- **Results:** Once finished, the `summary.json` in the run directory will contain the final JSD convergence metrics and Brier scores.

This profile is a fast protocol smoke run: one event only, but full condition execution (`A/B/C`) with deterministic benchmark mode and the same OpenRouter model for graph generation, benchmark inference, and evaluator scoring.

If you want **OpenRouter cloud** for all three benchmark roles, also set:

```env
OPENROUTER_API_KEY=<your_openrouter_key>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_GRAPH_MODEL=google/gemma-4-26b-a4b-it
OPENROUTER_BENCHMARK_MODEL=google/gemma-4-26b-a4b-it
OPENROUTER_EVALUATOR_MODEL=google/gemma-4-26b-a4b-it
```

If you want **local Ollama** for all three roles, set:

```env
OPENROUTER_API_KEY=ollama
OPENROUTER_BASE_URL=http://localhost:11434/v1
OPENROUTER_GRAPH_MODEL=llama3.1:8b
OPENROUTER_BENCHMARK_MODEL=llama3.1:8b
OPENROUTER_EVALUATOR_MODEL=llama3.1:8b
```

## System status endpoint

`GET /api/status` returns runtime checks for:

- Neo4j connectivity
- Ollama reachability and model availability
- Disk usage snapshot

Example URL:

`http://localhost:5001/api/status`

## Hardware guidance

| Component | Minimum | Recommended |
|---|---|---|
| RAM | 16 GB | 32 GB+ |
| GPU VRAM | 10 GB (smaller models) | 24 GB+ |
| CPU | 4 cores | 8+ cores |
| Disk | 20 GB | 50 GB+ |

CPU-only mode is possible but slower for simulation-heavy and benchmark-heavy runs.

## Troubleshooting

- If backend startup fails with config errors, verify `.env` values first.
- If protocol preflight fails, confirm Neo4j (`7687`) and Ollama (`11434`) are reachable.
- If using benchmark role routing, ensure all three are set:
  - `OPENROUTER_GRAPH_MODEL`
  - `OPENROUTER_BENCHMARK_MODEL`
  - `OPENROUTER_EVALUATOR_MODEL`
- For local Neo4j bootstrap helpers, check `backend/scripts/start_neo4j_local.py`.

## License

AGPL-3.0. See [LICENSE](./LICENSE).

## Credits

Modified fork of [MiroFish](https://github.com/666ghj/MiroFish).  
Simulation stack includes OASIS/CAMEL-AI components, with local-first infrastructure integration in this repository.
