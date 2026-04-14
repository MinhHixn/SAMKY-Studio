<div align="center">

<img src="./static/image/mirofish-offline-banner.png" alt="MiroFish Offline" width="100%"/>

# MiroFish-Offline

**Fully local fork of [MiroFish](https://github.com/666ghj/MiroFish) — no cloud APIs required. English UI.**

*A multi-agent swarm intelligence engine that simulates public opinion, market sentiment, and social dynamics. Entirely on your hardware.*

[![GitHub Stars](https://img.shields.io/github/stars/nikmcfly/MiroFish-Offline?style=flat-square&color=DAA520)](https://github.com/nikmcfly/MiroFish-Offline/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/nikmcfly/MiroFish-Offline?style=flat-square)](https://github.com/nikmcfly/MiroFish-Offline/network)
[![Docker](https://img.shields.io/badge/Docker-Build-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](./LICENSE)

</div>

## What is this?

MiroFish is a multi-agent simulation engine: upload any document (press release, policy draft, financial report), and it generates hundreds of AI agents with unique personalities that simulate the public reaction on social media. Posts, arguments, opinion shifts — hour by hour.

The [original MiroFish](https://github.com/666ghj/MiroFish) was built for the Chinese market (Chinese UI, Zep Cloud for knowledge graphs, DashScope API). This fork makes it **fully local and fully English**:

| Original MiroFish | MiroFish-Offline |
|---|---|
| Chinese UI | **English UI** (1,000+ strings translated) |
| Zep Cloud (graph memory) | **Neo4j Community Edition 5.15** |
| DashScope / OpenAI API (LLM) | **Ollama** (qwen2.5, llama3, etc.) |
| Zep Cloud embeddings | **nomic-embed-text** via Ollama |
| Cloud API keys required | **Zero cloud dependencies** |

## Workflow

1. **Graph Build** — Extracts entities (people, companies, events) and relationships from your document. Builds a knowledge graph with individual and group memory via Neo4j.
2. **Env Setup** — Generates hundreds of agent personas, each with unique personality, opinion bias, reaction speed, influence level, and memory of past events.
3. **Simulation** — Agents interact on simulated social platforms: posting, replying, arguing, shifting opinions. The system tracks sentiment evolution, topic propagation, and influence dynamics in real time.
4. **Report** — A ReportAgent analyzes the post-simulation environment, interviews a focus group of agents, searches the knowledge graph for evidence, and generates a structured analysis.
5. **Interaction** — Chat with any agent from the simulated world. Ask them why they posted what they posted. Full memory and personality persists.

## Screenshot

<div align="center">
<img src="./static/image/mirofish-offline-screenshot.jpg" alt="MiroFish Offline — English UI" width="100%"/>
</div>

## Quick Start

### Prerequisites

- Docker & Docker Compose (recommended), **or**
- Python 3.11+, Node.js 18+, Neo4j 5.15+, Ollama

### Option A: Docker (easiest)

```bash
git clone https://github.com/nikmcfly/MiroFish-Offline.git
cd MiroFish-Offline
cp .env.example .env

# Start all services (Neo4j, Ollama, MiroFish)
docker compose up -d

# Pull the required models into Ollama
docker exec mirofish-ollama ollama pull qwen2.5:32b
docker exec mirofish-ollama ollama pull nomic-embed-text
```

Open `http://localhost:3000` — that's it.

### Option B: Manual

**1. Start Neo4j**

```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/mirofish \
  neo4j:5.15-community
```

**2. Start Ollama & pull models**

```bash
ollama serve &
ollama pull qwen2.5:32b      # LLM (or qwen2.5:14b for less VRAM)
ollama pull nomic-embed-text  # Embeddings (768d)
```

**3. Configure & run backend**

```bash
cp .env.example .env
# Edit .env if your Neo4j/Ollama are on non-default ports

cd backend
pip install -r requirements.txt
python run.py
```

**4. Run frontend**

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Configuration

All settings are in `.env` (copy from `.env.example`):

```bash
# LLM — points to local Ollama (OpenAI-compatible API)
LLM_API_KEY=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL_NAME=qwen2.5:32b
OPENROUTER_HTTP_REFERER=
OPENROUTER_X_TITLE=

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=mirofish

# Embeddings
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_BASE_URL=http://localhost:11434

# Deterministic benchmark mode
BENCHMARK_MODE=false
BENCHMARK_TEMPERATURE=0.0
BENCHMARK_SEED=42

# LLM transient retry policy
LLM_RETRY_MAX_RETRIES=3
LLM_RETRY_INITIAL_DELAY=1.0
LLM_RETRY_MAX_DELAY=30.0
```

Works with any OpenAI-compatible API — swap Ollama for Claude, GPT, or any other provider by changing `LLM_BASE_URL` and `LLM_API_KEY`.

### OpenRouter prototype mode

To run against OpenRouter, set:

- `LLM_BASE_URL=https://openrouter.ai/api/v1`
- `LLM_API_KEY=<your_openrouter_key>`
- Optional attribution headers:
  - `OPENROUTER_HTTP_REFERER=https://your-project-url`
  - `OPENROUTER_X_TITLE=MiroFish Offline`

For reproducible benchmark runs, enable deterministic mode:

- `BENCHMARK_MODE=true` forces chat temperature to `BENCHMARK_TEMPERATURE`
- `BENCHMARK_SEED` is sent on each chat request
- Retries are transient-only (429/5xx + transport errors), configurable via `LLM_RETRY_*`

#### Phase 0 prototype profile (OpenRouter free-tier)

Phase 0 prototyping uses OpenRouter free-tier models to validate pipeline feasibility and reduce iteration latency while HPC queues are unavailable:

- Graph construction model: `google/gemma-4-31b-it:free`
- MCQ evaluator model: `google/gemma-4-31b-it:free`
- Benchmark simulation model: `minimax/minimax-m2.5:free`

Methodological limitations (documented for transparency):

1. The evaluator is not independent from graph-building in Phase 0 (shared model family/path).
2. Free-tier rate limits can increase retry pressure and occasionally increase output schema-drift risk.
3. Public evaluation coverage for `minimax/minimax-m2.5` remains limited.

Safe local shell setup (do not commit secrets):

```powershell
$env:LLM_BASE_URL='https://openrouter.ai/api/v1'
$env:LLM_API_KEY='<set-your-openrouter-key-in-local-shell-only>'
$env:OPENROUTER_GRAPH_MODEL='google/gemma-4-31b-it:free'
$env:OPENROUTER_EVALUATOR_MODEL='google/gemma-4-31b-it:free'
$env:OPENROUTER_BENCHMARK_MODEL='minimax/minimax-m2.5:free'
$env:BENCHMARK_MODE='true'
$env:BENCHMARK_TEMPERATURE='0.0'
$env:BENCHMARK_SEED='42'
```

Phase 1 transitions to the full KB v3.0 offline stack with an isolated evaluator (`GPT-4o-mini`) plus self-hosted open-weight models for methodological rigor and reproducibility.

Run the ECN-BENCH OpenRouter prototype from `backend`:

```powershell
Set-Location backend

# Targeted OpenRouter prototype tests
.\.venv311\Scripts\python -m pytest tests\test_llm_client_openrouter.py tests\test_benchmark_trace.py tests\test_run_ecnbench_openrouter.py -q

# Flatten 30 seed context files into a single directory expected by the orchestrator
$flatSeeds = "tmp_seeds_flat"
if (Test-Path $flatSeeds) { Remove-Item $flatSeeds -Recurse -Force }
New-Item -ItemType Directory -Path $flatSeeds | Out-Null
Get-ChildItem ..\..\data\seeds -Directory | ForEach-Object {
    $contextPath = Join-Path $_.FullName "context.md"
    if (Test-Path $contextPath) {
        Copy-Item $contextPath (Join-Path $flatSeeds "$($_.Name).md")
    }
}

# Queue ECN-BENCH batches (dry-run style queue output)
.\.venv311\Scripts\python scripts\run_ecnbench_openrouter.py `
  --seeds-dir $flatSeeds `
  --events-raw ..\..\data\events_raw.json `
  --batch-size 10 `
  --repeat-runs 2 `
  --trace-out logs\ecnbench_trace.jsonl `
  --variance-out logs\variance_summary.json
```

Run the end-to-end ECN-BENCH protocol benchmark:

```powershell
Set-Location backend

.\.venv311\Scripts\python scripts\run_ecnbench_protocol.py `
  --seeds-dir ..\..\data\seeds `
  --events-raw ..\..\data\events_raw.json `
  --injection-bank ..\..\data\injections\step30_injection_bank.json `
  --output-dir logs\benchmark_runs `
  --events 30 `
  --repeats 1 `
  --trace-out logs\benchmark_traces\ecnbench_trace.jsonl
```

Omit `--trace-out` to use the default `logs\benchmark_runs\<run_id>\traces\execution.jsonl`.

Artifacts are written to `logs\benchmark_runs\<run_id>\`:

- `run_manifest.json` — run inputs, selected events, and generated file list
- `traces\execution.jsonl` — per-unit benchmark trace events
- `event_results.json` — one row per event × condition × repeat
- `summary.json` — mean Brier scores, reliability-gated renormalized `composite_score`, lift, and success/failure counts
- `simulation_config.json`, `twitter_profiles.csv`, `reddit_profiles.json` — per-unit simulation inputs

#### Benchmark methodology (Phase 1 telemetry + baselines)

- Telemetry checkpoints are fixed at rounds `[12, 24, 36, 48, 60]`.
- Convergence telemetry uses 4-bin JSD against a uniform distribution; `round_jsd` stores the five checkpoint values.
- `convergence_monotonic` is `true` when `round_jsd` is non-increasing within the epsilon tolerance (`jsd_monotonic_tolerance_epsilon`).
- Baselines are always `uniform_random` and `market_prior` (from `polymarket_opening_prior`), persisted per row under `baseline_scores`.
- Each event must include a valid `polymarket_opening_prior` (hard preflight); the manifest records the preflight marker (`preflight_market_prior_check: "pass"`).
- `run_manifest.json` additionally records `phase1_config_version`, `telemetry_checkpoints`, `jsd_monotonic_tolerance_epsilon`, and `baseline_agents`.

#### ECN-BENCH continuation invariants

- Workflow mode remains A/B/C per event (`workflow_mode: "abc-per-event"`).
- `run_manifest.json` includes:
  - `benchmark_model`
  - `expected_run_units` (derived from generated condition matrix size; in current A/B/C mode this equals `events_loaded * 3 * repeats`)
  - `weights_schema_version`
  - `mcq_prompt_version`
  - `deterministic_mode` snapshot
- `event_results.json` includes `unit_id` (`<event_id>_<condition>_r<repeat>`) so each run unit is explicit.
- `event_results.json` rows include:
  - `injection_direction`
  - `signed_delta`
  - `belief_update_failure`

#### ECN-BENCH rubric evaluator contract (additive)

- Evaluator output now includes:
  - `probabilities` (legacy output, unchanged)
  - `mcq_dimensions` (7 dimensions × 4 buckets: `very_low`, `low`, `high`, `very_high`)
  - `validated_scales` (includes `schema_version` (v1) and validated numeric scores)
- Summary output now includes:
  - `composite_score` (reliability-gated, renormalized)
- Event result rows include:
  - `yes_probability` (resolved from `probabilities["YES"]` when present)
  - `strict_contract` (`true` for mapping payloads, `false` for legacy tuple payloads)
- Numeric aggregation remains unchanged: multiclass Brier scoring + condition lift (`A_to_B`, `A_to_C`, `B_to_C`).
- Summary includes `content_susceptibility.delta.B_minus_C = mean_yes_probability(B) - mean_yes_probability(C)`.
- Phase 1 MVP uses placeholder weights (prediction_accuracy=0.25, others=0.125) for pipeline validation. Empirical weight optimization will be applied to pilot data prior to Phase 2 per KB §2.9.

### ECN-BENCH v0.3 parity architecture update

- Benchmark run lifecycle now uses reusable orchestrator classes in `backend/app/benchmarks/orchestrator.py`:
  - `ConditionExecutor` / `ProtocolConditionExecutor` for per-condition execution and evaluation handling
  - `BenchmarkRunOrchestrator` for run-level lifecycle (manifest, traces, event-results, summary coordination)
- `backend/scripts/run_ecnbench_protocol.py` remains the CLI entrypoint and delegates orchestration to these classes.

#### Verification traceability (v0.3 parity)

Run from `backend` to keep this parity work auditable:

Sanity preflight (set before running the protocol sanity command):

- `OPENROUTER_API_KEY` (or `LLM_API_KEY` fallback)
- `OPENROUTER_BASE_URL` (defaults to `https://openrouter.ai/api/v1`; override only if needed)
- `OPENROUTER_GRAPH_MODEL`
- `OPENROUTER_BENCHMARK_MODEL`
- `OPENROUTER_EVALUATOR_MODEL`

If these are missing/empty, sanity execution can be blocked with `ValueError: Missing benchmark router config ...`. Re-run the same sanity command after exporting the missing values in the current shell/session.

```powershell
python -m pytest tests\test_benchmark_protocol.py tests\test_benchmark_evaluator_scoring.py tests\test_benchmark_role_router.py tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py tests\test_api_status.py -q
python scripts\run_ecnbench_protocol.py --seeds-dir ..\..\data\seeds --events-raw ..\..\data\events_raw.json --injection-bank ..\..\data\injections\step30_injection_bank.json --output-dir logs\benchmark_runs --events 1 --repeats 1 --trace-out logs\benchmark_traces\ecnbench_trace_sanity.jsonl
# Broader regression sweep traceability: python -m pytest tests -q
# Blocker in this environment: collection fails with `ModuleNotFoundError: camel` (install `oasis-ai`/`camel-ai`).
```

##### Verification evidence (this branch)

- Benchmark regression command: `python -m pytest tests\test_benchmark_protocol.py tests\test_benchmark_evaluator_scoring.py tests\test_benchmark_role_router.py tests\test_benchmark_orchestrator.py tests\test_run_ecnbench_protocol.py tests\test_api_status.py -q`
- Observed in this branch: `60 passed`.
- Sanity command form (with preflight vars, run from `backend`): `$env:OPENROUTER_API_KEY='<set>'; $env:OPENROUTER_BASE_URL='https://openrouter.ai/api/v1'; $env:OPENROUTER_GRAPH_MODEL='<set>'; $env:OPENROUTER_BENCHMARK_MODEL='<set>'; $env:OPENROUTER_EVALUATOR_MODEL='<set>'; python scripts\run_ecnbench_protocol.py --seeds-dir ..\..\data\seeds --events-raw ..\..\data\events_raw.json --injection-bank ..\..\data\injections\step30_injection_bank.json --output-dir logs\benchmark_runs --events 1 --repeats 1`
- Observed branch sanity outcome: command exit code `0`; artifacts written under `backend\logs\benchmark_runs\ecnbench_<UTC timestamp>\`.
- Post-run field check in this branch: across `run_manifest.json` and `event_results.json`, the traceability fields `workflow_mode`, `benchmark_model`, `expected_run_units` (matrix-derived; currently `events_loaded * 3 * repeats` in A/B/C mode), and `unit_id` are present after run (`unit_id` is per-row in `event_results.json`).

### System status endpoint

`GET /api/status` returns a top-level response envelope with `success` and `data`:

```json
{
  "success": true,
  "data": {
    "neo4j": {
      "connected": true,
      "error": null
    },
    "ollama": {
      "reachable": true,
      "model_configured": "qwen2.5:32b",
      "model_available": true,
      "error": null
    },
    "disk": {
      "path": "data/simulation_data",
      "total_bytes": 1000000000,
      "used_bytes": 400000000,
      "free_bytes": 600000000,
      "error": null
    },
    "timestamp_utc": "2026-04-12T10:00:00Z"
  }
}
```

Inside `data`, the status payload includes:

- `neo4j`: connectivity state and sanitized error details
- `ollama`: service reachability, configured model, model availability, and sanitized error details
- `disk`: configured simulation data path plus total/used/free bytes (or a sanitized disk-check error)
- `timestamp_utc`: server timestamp for the status snapshot

## Architecture

This fork introduces a clean abstraction layer between the application and the graph database:

```
┌─────────────────────────────────────────┐
│              Flask API                   │
│  graph.py  simulation.py  report.py     │
└──────────────┬──────────────────────────┘
               │ app.extensions['neo4j_storage']
┌──────────────▼──────────────────────────┐
│           Service Layer                  │
│  EntityReader  GraphToolsService         │
│  GraphMemoryUpdater  ReportAgent         │
└──────────────┬──────────────────────────┘
               │ storage: GraphStorage
┌──────────────▼──────────────────────────┐
│         GraphStorage (abstract)          │
│              │                            │
│    ┌─────────▼─────────┐                │
│    │   Neo4jStorage     │                │
│    │  ┌───────────────┐ │                │
│    │  │ EmbeddingService│ ← Ollama       │
│    │  │ NERExtractor   │ ← Ollama LLM   │
│    │  │ SearchService  │ ← Hybrid search │
│    │  └───────────────┘ │                │
│    └───────────────────┘                │
└─────────────────────────────────────────┘
               │
        ┌──────▼──────┐
        │  Neo4j CE   │
        │  5.15       │
        └─────────────┘
```

**Key design decisions:**

- `GraphStorage` is an abstract interface — swap Neo4j for any other graph DB by implementing one class
- Dependency injection via Flask `app.extensions` — no global singletons
- Hybrid search: 0.7 × vector similarity + 0.3 × BM25 keyword search
- Synchronous NER/RE extraction via local LLM (replaces Zep's async episodes)
- All original dataclasses and LLM tools (InsightForge, Panorama, Agent Interviews) preserved

## Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| RAM | 16 GB | 32 GB |
| VRAM (GPU) | 10 GB (14b model) | 24 GB (32b model) |
| Disk | 20 GB | 50 GB |
| CPU | 4 cores | 8+ cores |

CPU-only mode works but is significantly slower for LLM inference. For lighter setups, use `qwen2.5:14b` or `qwen2.5:7b`.

## Use Cases

- **PR crisis testing** — simulate the public reaction to a press release before publishing
- **Trading signal generation** — feed financial news and observe simulated market sentiment
- **Policy impact analysis** — test draft regulations against simulated public response
- **Creative experiments** — someone fed it a classical Chinese novel with a lost ending; the agents wrote a narratively consistent conclusion

## License

AGPL-3.0 — same as the original MiroFish project. See [LICENSE](./LICENSE).

## Credits & Attribution

This is a modified fork of [MiroFish](https://github.com/666ghj/MiroFish) by [666ghj](https://github.com/666ghj), originally supported by [Shanda Group](https://www.shanda.com/). The simulation engine is powered by [OASIS](https://github.com/camel-ai/oasis) from the CAMEL-AI team.

**Modifications in this fork:**
- Backend migrated from Zep Cloud to local Neo4j CE 5.15 + Ollama
- Entire frontend translated from Chinese to English (20 files, 1,000+ strings)
- All Zep references replaced with Neo4j across the UI
- Rebranded to MiroFish Offline
