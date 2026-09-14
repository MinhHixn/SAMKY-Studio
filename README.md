<div align="center">

# SAMKY Studio

**A friendly, local/online event simulation studio built on [MiroFish-Offline](https://github.com/nikmcfly/MiroFish-Offline).**

*Run document-to-simulation pipelines, social reaction simulations, and ECN-BENCH protocol experiments on your own infrastructure.*

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](./LICENSE)

</div>

> **SAM** stands for **Simulation · Agents · Momentum**. Configure your online/offline model, API key, and round count up front (60 recommended). Start opens a minimal graph and progress workspace, followed by reports and agent interviews. The headless CLI uses the same simulation API. See the [new interface guide](docs/STUDIO_UI.md). Read the [English user guide](docs/USER_GUIDE.md), [Vietnamese guide](docs/USER_GUIDE_VI.md), or [Spanish guide](docs/USER_GUIDE_ES.md).

Preparing your own GitHub repository? Follow the [Vietnamese publishing checklist](docs/GITHUB_PUBLISH_VI.md) before making it public.

## Quick start

```bash
cp .env.example .env
docker compose up -d --build
docker exec mirofish-ollama ollama pull qwen2.5:7b
docker exec mirofish-ollama ollama pull nomic-embed-text
```

Open `http://localhost:3000`. For automation, run `python backend/scripts/sam_cli.py doctor`, then use the `run` command documented in the guide. An online OpenAI-compatible configuration is available through `.env.online.example` and `compose.online.yml`.

## What this repository is

SAMKY Studio is a self-hostable product built on the MiroFish-Offline engine and focused on:

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

## Updates today (2026-05-26)

- **Architecture v5.14: Opinion Dynamics & Complexity Scaling Upgrades:**
  - **Friedkin-Johnsen Anchoring (Upgrade A):** Added a new cognitive anchoring protocol to simulate human-like opinion resistance and prevent premature consensus collapse in agent swarms. The system runs an initial "Round 0 Telemetry Probe" to establish each agent's baseline zero-shot belief $x_i(0)$. In subsequent telemetry checkpoints, the agent's baseline belief is dynamically retrieved from SQLite and injected back into their prompt context as a mathematical anchoring constraint, weighted by a stubbornness coefficient ($1 - \alpha_i$) tailored to their persona axis (e.g. 80% anchoring weight for institutional organizations, 30% for individual citizens).
  - **Mean-Field Swarm Aggregation (Upgrade B):** Solved the $O(N^2)$ context-window inflation and NFS locking bottleneck for massive-scale swarms ($N=3000$) by transitioning the simulation platform from pairwise communication to a linear $O(N)$ Mean-Field signal structure. At the end of each round, a single centralized **Swarm Narrative Summary** ($\mathbb{M}(t)$) is generated via LLM synthesis of top trending posts. Active agents in subsequent rounds receive this global trend directly in their timeline context, preserving global communication flow with minimal token overhead and sub-hour scaling speed.
  
- **HPC Deployment & File Sync Guide (`scp` instructions):**
  - **Modified Files:** To sync these updates to the GLiCID/Nautilus HPC cluster for production runs, you must transfer the following modified files using `scp`:
    ```bash
    # 1. Sync the updated core simulation runner (updated with FJ Anchoring & Mean-Field narratives)
    scp backend/scripts/run_parallel_simulation.py user@glicid:~/ecnbench/MiroFish-Offline/backend/scripts/

    # 2. Sync the consolidated project Knowledge Base
    scp ECN-HPC-DEPLOY/ECNBENCH_KnowledgeBase.md user@glicid:~/ecnbench/ECN-HPC-DEPLOY/
    ```
  - **Environment Toggles:** Enable the upgrades inside your Slurm execution scripts by exporting the environment toggles:
    ```bash
    export ENABLE_FJ_ANCHORING="True"
    export ENABLE_MEAN_FIELD_AGGREGATION="True"
    ```

## Updates yesterday (2026-05-20)


- **Architecture v5.11: Global SafeParser Integration & Dynamic Scaling:**
  - **Global Regex Shield:** Upgraded `SafeParser` and integrated it directly into `LLMClient.chat_json`. The system now uses aggressive Regex to extract JSON payloads from noisy LLM outputs (e.g., when a model appends conversational text outside of markdown tags), preventing `JSONDecodeError` crashes during Persona Generation and Evaluation.
  - **Dynamic Minimal Mode:** Patched `run_ecnbench_protocol.py` to allow `DEV_MINIMAL_MODE` to respect environment variables for scaling (`DEV_MINIMAL_MAX_STEPS`, `DEV_MINIMAL_AGENT_COUNT`). Checkpoint intervals are now computed dynamically (`range(6, max_steps + 1, 6)`), enabling full-length (e.g., 60-round) validation runs while retaining minimal mode safety fallbacks.
  - **Dependency Update:** Added `json-repair` as a mandatory dependency in all Slurm scripts to support the new parsing pipeline.

- **Architecture v5.10: Native vLLM Stabilization & Dual-Server Routing Protocol:**
  - **Dual-Server Routing Fix:** Refactored `backend/app/benchmarks/role_router.py` to enforce strict offline routing. Fixed a critical bug where `BenchmarkRoleRouter` leaked requests to OpenRouter's cloud API (causing 404s). Now explicitly splits traffic: Simulation (Port 8000) and Evaluator/Graph (Port 8001).
  - **Native Model Pivot:** Abandoned unstable `transformers` bind mounts for newer architectures (Gemma 4, Qwen 3.6). Standardized exclusively on models natively supported by vLLM v0.6.3 (Llama 3.1, Gemma 2, Qwen 2.5, DeepSeek R1 Distill) downloaded directly as AWQ quants.
  - **Robust JSON Handling Directive:** Identified severe JSON hallucination loops (e.g., infinite string repeats) and type errors (`AttributeError: 'str' object has no attribute 'get'`) in 8B-26B models during persona generation. A surgical patch to `intelligent_persona.py` for type-checking and fallback is required to prevent simulation crashes.
  - **Hugging Face Bulk Pre-fetch:** Successfully deployed an automated script to securely pre-fetch 11+ AWQ/GGUF models to the Waves NVMe cache using `snapshot_download`, bypassing HPC firewall restrictions.

## Updates yesterday (2026-05-19)

- **Architecture v5.9: Optimized Model Selection & Clean Slate Deployment:**
  - **Environment Restoration:** Terminated the "Dependency Hell" cycle by deleting all surgical library patches (`vllm_ext_packages`). Reverted to the native `vllm_v0.6.3.sif` container environment for maximum hardware-optimized stability.
  - **Stable Baseline Transition:** Pivoted from the problematic Gemma-4 and Moonlight-16B architectures to a **Qwen 2.5 32B-Instruct** baseline. This model offers native support, high reasoning fidelity, and perfect compatibility with the existing HPC container.
  - **AWQ Offline Pre-fetching:** Standardized a new pre-flight protocol to download `-AWQ` quantized models directly to NVMe scratch (`/scratch/waves`). This ensures consistent Brier Score measurements and prevents VRAM OOM errors without requiring unstable library overrides.
  - **Tiered Hardware Deployment:** Implemented dual-slurm configurations targeting both `visu` (2x A40) and `gpu` (4x A100) partitions to maximize throughput and bypass QOS limits.

- **Architecture v5.8: Python Path Injection & Gatekeeper Bypass:**

## Updates yesterday (2026-05-18)

- **Architecture v5.7: Surgical Patching & Weight Integrity:**
  - **Surgical Library Override (Bind Mount):** Successfully bypassed the `KeyError: 'gemma4'` limitation of vLLM 0.6.3 by using Apptainer Bind Mounts. The system now clones the latest `transformers` dev source to high-I/O scratch space and "hot-swaps" it into the immutable SIF container at runtime. 
    - **Critical Discovery:** Corrected the mount path to target **Python 3.12** inside the container, resolving a version mismatch with the host's Python 3.11 backend.
  - **Weight Integrity Protocol (Fixing the "Empty File Trap"):** Identified a failure mode where model snapshots appeared valid but contained only 5.5K of metadata. Implemented a mandatory pre-flight integrity check on the Login Node, using the `hf` CLI to perform a full 52GB pre-fetch of Gemma 4 weights before job submission.
  - **HF Hub Lock Mitigation:** Integrated an automated cleanup for stale `.lock` files in the Hugging Face cache to ensure non-blocking `resume-download` operations in the background.

## Updates yesterday (2026-05-17)

- **Architecture v5.6: Apptainer Isolation & Multimodal MoE Fixes:**
  - **Apptainer (Singularity) Integration:** Completely bypassed host-level `NVIDIA driver too old` and `undefined symbol: ncclCommWindowDeregister` errors on the Nautilus cluster by migrating the dual vLLM servers to **Apptainer Containers**.
    - The environment now standardizes on `docker://vllm/vllm-openai:v0.6.3.post1` (compiled into a `.sif` file) to ensure perfect CUDA/NCCL compatibility regardless of the underlying HPC node state.
  - **Gemma 4 Multimodal Fix:** Discovered and patched a critical timeout failure when loading Google's Gemma 4 26B-A4B. vLLM defaults caused a crash: `Chunked MM input disabled but max_tokens_per_mm_item is larger than max_num_batched_tokens`.
    - **Resolution:** Explicitly added `--max-num-batched-tokens 4096` to all vLLM Apptainer launch commands, successfully initializing the Mixture-of-Experts architecture.

## Updates yesterday (2026-05-16)

- **Architecture v5.5: Multi-GPU Isolation & Staggered Telemetry:**
  - **4-GPU Architecture:** Upgraded to a multi-GPU isolation strategy using two independent vLLM instances. The **Benchmark Server** (GPUs 0,1, Port 8000) handles agent actions, while the **Evaluator Server** (GPUs 2,3, Port 8001) handles telemetry probes and scoring. This prevents analytical bursts from starving the social simulation.
  - **Staggered Telemetry Throttling:** Reduced `_TELEMETRY_CONCURRENCY` to **5** to ensure stability under 100-agent census probing. Agents are now polled in serial micro-batches, drastically reducing KV-cache pressure and eliminating `openai.APITimeoutError`.
  - **NVMe Acceleration (Waves Cluster):** Migrated high-I/O data (Neo4j and simulation logs) to the **Waves NVMe scratch** space (`/scratch/waves`). This bypassed the Nautilus NFS latency bottlenecks, completely eliminating `database is locked` errors.
  - **Bulletproof Persona Generation:** Implemented a recursive generation loop that tracks persona failures and retries until 100% of the target population is instantiated with high-quality 4-Axis DNA.
  - **vLLM Protocol Fallback:** Added automated detection and fallback for vLLM 0.5.4's `json_schema` incompatibility. The system now seamlessly reverts to `json_object` after the first 400 error to maintain low-latency throughput.
  - **Massive Storage Cleanup:** Reclaimed **130GB+** of disk space on Nautilus by purging redundant GGUF and Ollama-registry models, standardizing the cache on native Hugging Face snapshots.

- **Architecture v5.0: The vLLM Scalability Migration:**
  - **Hybrid Inference Architecture:** Replaced the Ollama-only architecture with a **vLLM + Ollama Hybrid** setup to resolve fatal 3-hour timeouts during 100-agent telemetry probes. The primary conversational generation is now handled by vLLM (Continuous Batching, PagedAttention) via `http://localhost:8000/v1`, while background Graphiti embeddings remain routed to a dedicated Ollama instance (`http://localhost:11434`).
  - **NFS Database Lock Resolution:** Completely eliminated `database is locked` bottlenecks during high-concurrency writes on HPC Network File Systems (NFS). Expanded upon the SQLite WAL mode by strictly enforcing a `timeout=60` parameter on all `sqlite3.connect()` calls within the core simulation runners (`run_parallel_simulation.py`, `run_twitter_simulation.py`, `run_reddit_simulation.py`), forcing agents to queue gracefully rather than crash.
  - **vLLM Dependency Hardening:** Discovered and resolved a systemic `ModuleNotFoundError: No module named 'pyairports'` crash within the `outlines` library (a core vLLM dependency for guided decoding). Manually patched the `site-packages` directories (`lib` and `lib64`) on the Nautilus cluster with the raw package source, stabilizing the vLLM server boot process.
  - **Gated Model Caveat:** Officially documented that vLLM strictly requires native Hugging Face formats (`config.json`, `safetensors`). Models locked behind Hugging Face gates (e.g., `google/gemma-2-27b-it`) will trigger `401 Unauthorized` crashes unless an explicit `HF_TOKEN` is provided. The framework now defaults to native open-weights like `Qwen/Qwen2.5-32B-Instruct` for large-scale HPC benchmarking.

## Updates yesterday (2026-05-15)

- **HPC Scalability & Concurrency Fixes:**
  - **SQLite WAL Mode Integration:** Resolved severe `database is locked` bottlenecks during high-concurrency telemetry writes on HPC network file systems (NFS). Injected `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;` into all SQLite connections within `run_parallel_simulation.py`, enabling parallel read/write capabilities and unlocking 100+ agent scalability.
  - **Telemetry Throttling for Phase-0:** Identified and patched a dual-platform concurrency trap where `$N=100` sampling forced Ollama to process up to 200 simultaneous structured JSON requests (Twitter + Reddit), causing fatal 3-hour timeouts for Qwen 3.6 and Gemma 4. Hardcapped `_TELEMETRY_SAMPLE_SIZE = 30` to guarantee Phase-0 stability on single-node GPU deployments.
  - **Path to 3000-Agent Simulations:** Formally documented the requirement to transition from Ollama to **vLLM** (`--tensor-parallel-size N`) and utilize Continuous Batching for future large-scale ($N=3000$) runs, as Ollama lacks the batching queue required to survive telemetry bursts.

## Updates (2026-05-08)

- **Deep Framework Interoperability:**
  - **CAMEL-AI Monkeypatch (Fix 400 Bad Request):** Discovered and resolved a systemic conflict between the CAMEL-AI framework and Ollama's tool-use implementation. Gemma and Mistral models often return "does not support tools" errors when `tools` parameters are present. Implemented a recursive monkeypatch in `backend/apply_patch.py` that intercepts `OpenAIModel.arun` calls to force `tools=None`, enabling seamless simulation flow on Ollama.
  - **Ollama Version Enforcement:** Standardized all Slurm templates to use absolute paths (`$HOME/ecnbench/bin/ollama`). This bypasses outdated system binaries (v0.1.32) and ensures the use of **v0.23.1**, eliminating `412: newer version required` errors during model pulls.
- **Nautilus HPC Optimization:**
  - **Stable QoS Strategy:** Transitioned from `debug` (20m) to **`quick`** (3h) QoS. This provides the necessary headroom for high-parameter models (Qwen 3.6 27B, Gemma 27B) to complete complex persona generation and social interaction loops without timeout-induced state corruption.
  - **Persona Fidelity Verification:** Confirmed that Gemma 27B successfully generates high-fidelity, multi-axis personas (Worldview, Motivation, Style, Biases) while strictly adhering to the "English-Only" linguistic firewall, even in multi-lingual environments.

## Updates yesterday (2026-05-07)

- **Infrastructure & Model Support (Nautilus HPC):**
  - **Ollama Engine Upgrade:** Upgraded user-space Ollama to **v0.23.1**. This was required to resolve `412: newer version required` errors when pulling state-of-the-art models like `gemma4:26b` and `gpt-oss:20b`.
  - **Robust Parameter Filtering (Fix 400 Bad Request):** Implemented a multi-layered parameter stripping logic in `backend/app/utils/llm_client.py`. The client now recursively searches and removes `min_p`, `top_k`, and other unsupported sampling options from both top-level `kwargs` and nested `extra_body['options']`, preventing the "Invalid Options" crash common with Qwen and Gemma models on Nautilus.
  - **Diagnostic Telemetry:** Integrated real-time parameter validation logging. The system now alerts via `simulation.log` if any unsupported parameters are detected and stripped before the request is dispatched.
- **Protocol Reliability:**
  - **Evaluator Recovery:** Verified that fixing the `min_p` issue restores the integrity of the Evaluator pipeline, preventing `fallback_used_ratio: 1.0` caused by failed agent probes.

## Updates yesterday (2026-04-25)

- **Architecture v4.1: The 'Bulletproof' Milestone:**
  - **Hard-Override Stage 2:** Enforced strict attribute dominance (Name/Gender/MBTI) from Stage 1 to Stage 2, successfully eliminating LLM "Context" name hallucinations and garbage entity resets.
  - **Context Isolation (Memory Leak Fix):** Implemented event-specific checkpoints (`logs/checkpoints/expansion_{event_id}.json`) to prevent data leakage (Context Bleed) between sequential events in batch simulations.
  - **Anti-Leakage Prompting:** Mandated markdown-isolated JSON output (```json ... ```) and updated system messages to support high-parameter reasoning models (o1-class, DeepSeek-R1) without Chain-of-Thought contamination.
  - **Defensive Parsing Upgrades:** Integrated robust JSON unwrapping (handles arbitrary wrapper keys) and bulletproof age parsing (safe regex for `null`/non-string fields).
- **Experimental Design Evolution:**
  - **True Proxy Signals:** Completed a comprehensive rewrite of all 35 `relevant_update` entries. Replaced deterministic "Spoilers" with historically grounded leading indicators (e.g., specific demographic turnout shifts, technical scaling laws), forcing agents to perform evidentiary reasoning instead of reading comprehension.
- **Benchmark Results (Phase 0 Highlights):**
  - **DeepSeek v3.2 Baseline:** Achieved a record **0.37 Brier Score** on Event C9 (UK Trade Deal), demonstrating superior precision in multi-option geopolitical forecasting.
  - **All-Gemma High-Fidelity:** Verified the `Gemma-4-26B` swarm as a stable, unbiased baseline for autonomous sociological simulations, correctly identifying ground-truth outcomes across Social and Technical quadrants.

## Updates yesterday (2026-04-24)

- **Architecture v4.0: Cognitive Diversification Pipeline:**
  - **Multi-Stage Synthesis:** Replaced one-shot generation with a two-stage extraction/instantiation pipeline, restoring high-fidelity persona diversity.
  - **Institutional Accounts:** Mandated a mix of Individual (60%) and Institutional (40%) accounts, including Media and Financial desks.
  - **Structural Anchors:** Integrated few-shot examples into the Stage 2 prompt to stabilize character design in smaller models.
- **Architecture v3.12: Defensive Hardening:**
  - **Anti-Dump Shield:** Automated detection and safe-fallback for "Context" entity hallucinations and oversized bio dumps.
  - **DNA Compression:** Enforced a "One Sentence Per Axis" rule to prevent token bloat and maintain attention coherence.
  - **Safe Age Parsing:** Implemented Regex-based sanitization for all integer fields to prevent system crashes.
- **Architecture v3.11: Global Linguistic Firewall:**
  - **English-Only Mandate:** Implemented a multi-layered linguistic constraint to prevent "Linguistic Spill" in multi-lingual models (e.g. Qwen, DeepSeek).
- **Architecture v3.10: Hybrid Analytical Schema:**
  - **Inclusive Telemetry:** Ensured `micro_epistemic_mapping` and `mcq_dimensions` are preserved during strict key enforcement.
  - **Eliminated Data Leakage:** Refactored the Post-Simulation evaluation pipeline to ensure the Report Agent (Evaluator) has **zero access** to the original `context.md` (seed document).
  - **Blind Evidence Payload:** The `build_evidence_text` function now strictly provides only the simulation log tail and a representative sample of social media actions from `actions.jsonl`.
  - **Observational Mandate:** Hardened the Evaluator prompt to enforce reasoning derived solely from the observed swarm discussion, preventing "Ground Truth" hallucinations.
  - **Scale-Up Stabilization:** Optimized Async Micro-Batching (v3.5) for targets of 60+ agents with a stable `BATCH_SIZE=5` to maintain LLM coherence across concurrent generation tasks.

## Updates yesterday (2026-04-23)

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
# 1. Start Docker Desktop and Neo4j infrastructure
cd backend
uv run python scripts\start_neo4j_local.py --start-docker-desktop

# 2. Install all dependencies
cd ..
npm run setup:all

# 3. Start development servers
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

## HPC & Large Scale Simulation Guide (GLiCID / Slurm)

This section provides a battle-tested guide for running ECN-BENCH at scale (up to 3,000 agents) on HPC infrastructure like **GLiCID**, utilizing **User-Space Neo4j**, **Ollama**, and **Slurm** orchestration.

### 1. Data Syncing & Transfer

Large files (Neo4j tarballs, GGUF models) should be pushed via `scp`. If using a Bastion/ProxyJump setup (common on GLiCID), configure your `~/.ssh/config` and use the alias:

```powershell
# Example: Push Neo4j binary from local Downloads to HPC scratch
scp "C:\Users\...\neo4j-community-5.15.0-unix.tar.gz" Glicid:/scratch/waves/users/$USER/ecnbench/neo4j_home/
```

### 2. Neo4j User-Space Setup (No Docker) & Java 17 Requirement

Since Docker is often restricted on HPC, run Neo4j as a portable binary. **CRITICAL:** Neo4j 5.x strictly requires Java 17 or Java 21. If your HPC login node defaults to Java 8, Neo4j will fail to start silently.

1.  **Extract & Install APOC:**
    ```bash
    tar -xvf neo4j-community-5.15.0-unix.tar.gz
    cp neo4j-community-5.15.0/labs/apoc-*.jar neo4j-community-5.15.0/plugins/
    ```

2.  **Portable Java 17 Installation (If System Module Fails):**
    If `module load java/17` is unavailable on your HPC, you must download a portable JDK:
    ```bash
    mkdir -p $SCRATCH_DIR/java17 && cd $SCRATCH_DIR/java17
    wget "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.11%2B9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.11_9.tar.gz"
    tar -xzf OpenJDK17U-jdk_x64_linux_hotspot_17.0.11_9.tar.gz
    export JAVA_HOME="$SCRATCH_DIR/java17/jdk-17.0.11+9"
    export PATH="$JAVA_HOME/bin:$PATH"
    ```

3.  **Memory & Security Tuning (`conf/neo4j.conf`):**
    For 3,000 agents, high RAM is mandatory. Set these in `neo4j.conf`:
    ```conf
    dbms.security.procedures.unrestricted=apoc.*
    dbms.security.procedures.allowlist=apoc.*
    server.memory.heap.initial_size=16G
    server.memory.heap.max_size=16G
    server.memory.pagecache.size=16G
    dbms.connector.bolt.listen_address=0.0.0.0:7687
    ```

4.  **Initial Setup:**
    ```bash
    $NEO4J_HOME/bin/neo4j-admin dbms set-initial-password <your-password>
    $NEO4J_HOME/bin/neo4j start
    ```

### 3. Slurm Policies & QoS Troubleshooting (GLiCID Specific)

HPC clusters enforce strict Quality of Service (QoS) limits. Common pitfalls:

*   **The 5-Minute Wall:** Default jobs often fall into the `normal` QoS, which may limit runtime to **5 minutes**.
*   **Mandatory Account:** You MUST specify your project account (e.g., `--account=gem`) to access longer runtimes.
*   **QoS Selection:**
    *   Use `--qos=gpus` for GPU jobs (limit: 3 hours).
    *   Use `--qos=short` for large simulations (limit: 24 hours).
*   **Constraint Error:** If you get `Invalid qos specification`, ensure your account is authorized for that specific QoS/Partition combination using `sacctmgr show associations user=$USER`.

### 4. Phase-0 HPC Slurm Template

A production-ready script to boot Neo4j, Ollama, and run the C9 event:

```bash
#!/bin/bash
#SBATCH --job-name=ecnbench-phase0
#SBATCH --account=gem
#SBATCH --partition=gpu
#SBATCH --qos=gpus
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=02:59:00
#SBATCH --output=log/phase0_%j.log

# 1. Boot Infrastructure
$NEO4J_HOME/bin/neo4j start
sleep 30

export OLLAMA_MODELS=/scratch/.../ollama_storage
ollama serve > log/ollama.log 2>&1 &
sleep 45

# 2. Prepare Phase-0 Models (Gemma 4 + Llama 3.1)
ollama create gemma:4 -f Modelfile_gemma4
ollama create llama3.1:8b -f Modelfile_llama8b

# 3. Run Protocol
cd backend
source venv/bin/activate
export DEV_MINIMAL_MODE='true' # 60 agents / 30 rounds
python scripts/run_ecnbench_protocol.py --event-ids C9 --repeats 1

# 4. Cleanup
$NEO4J_HOME/bin/neo4j stop
pkill ollama
```

### 5. High-Concurrency Optimization (`.env`)

For 3,000 agents, ensure your `.env` on the HPC is tuned:
```env
# Massive scale settings
SYNTHETIC_EXPANSION_BATCH_SIZE=10
NEO4J_URI=bolt://localhost:7687
# HPC models
OPENROUTER_GRAPH_MODEL=gemma:4
OPENROUTER_BENCHMARK_MODEL=llama3.1:8b
OPENROUTER_EVALUATOR_MODEL=gemma:4
```

> [!IMPORTANT]
> **Defensive Execution:** At massive scale (>1000 agents), LLM JSON hallucinations are statistically inevitable. The pipeline enforces strict type-safe fallbacks (empty dicts) rather than failing, ensuring 100% completion rates for high-duration HPC jobs.

### 6. Nautilus Cluster (GLiCID) - Final Setup

**IMPORTANT:** Following recent migrations, all jobs must now target the **Nautilus** cluster. Avoid legacy `waves` paths.

*   **Login Node:** `ssh nautilus` (Requires [SSH Config](https://doc.glicid.fr/GLiCID-PUBLIC/quickstart_advanced_user.html) setup)
*   **Primary Scratch:** `/scratch/nautilus/users/mhnguyn2025@ec-nantes.fr/ecnbench/`
*   **Official Docs:** [GLiCID Documentation](https://doc.glicid.fr)

#### Manual Ollama Installation
Since system modules may not include Ollama, install it manually in your user-space. Using the `.tar.zst` archive is recommended to ensure all necessary libraries are included:

```bash
# Download and extract official Linux binary (v0.23.1+ recommended)
mkdir -p ~/ecnbench/bin
curl -L https://ollama.com/download/ollama-linux-amd64.tar.zst -o ~/ecnbench/ollama.tar.zst
tar -I zstd -xvf ~/ecnbench/ollama.tar.zst -C ~/ecnbench/

# Verify installation
~/ecnbench/bin/ollama --version
```

#### High-Priority Debugging (`debug` QoS)
For fast turnaround during smoke tests, use the `debug` QoS.
*   **Priority:** 300 (Highest)
*   **Max Wall Time:** 20 minutes (`00:20:00`)
*   **Partition:** `gpu`
*   **Constraint:** Job will be killed instantly if it exceeds 20m. Use `--qos=short` for longer runs.

### 7. Production-Ready Slurm Template (Nautilus)

Save as `run_phase0.slurm`. **Note:** If editing on Windows, run `tr -d '\r' < file > file.unix` on the HPC to fix line breaks.

```bash
#!/bin/bash
#SBATCH --job-name=ecnbench-debug
#SBATCH --account=gem
#SBATCH -p gpu
#SBATCH --qos=debug
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:20:00
#SBATCH --output=logs/benchmark_phase0_%j.log

# 1. Environment Initialization
source /etc/profile.d/modules.sh 2>/dev/null
module load python/3.11.5

# 2. Dynamic Path Configuration
USER_ID=$(whoami)
export PATH="$HOME/ecnbench/bin:$PATH"
export PROJECT_ROOT="/scratch/nautilus/users/$USER_ID/ECN-HPC-DEPLOY"
export SCRATCH_DIR="/scratch/nautilus/users/$USER_ID/ecnbench"
export OLLAMA_MODELS="$SCRATCH_DIR/ollama_storage"

mkdir -p "$OLLAMA_MODELS"
mkdir -p "$HOME/logs"

# 3. Background Services
ollama serve > "$HOME/logs/ollama_serve.log" 2>&1 &
sleep 15

# Register Model (Example using Mistral-Nemo GGUF)
echo "FROM $SCRATCH_DIR/models/Mistral-Nemo-Instruct-2407-Q4_K_M.gguf" > "$SCRATCH_DIR/models/Modelfile_nemo"
ollama create mistral-nemo -f "$SCRATCH_DIR/models/Modelfile_nemo"

# 4. Execution
cd "$PROJECT_ROOT/MiroFish-Offline/backend"
source venv/bin/activate

export BENCHMARK_MODE='true'
export DEV_MINIMAL_MODE='true'
export LLM_MODEL_NAME='mistral-nemo'

python scripts/run_ecnbench_protocol.py \
  --seeds-dir ../../data/seeds \
  --events-raw ../../data/events_raw.json \
  --injection-bank ../../data/injections/step30_injection_bank.json \
  --output-dir logs/benchmark_runs \
  --event-ids S6 \
  --repeats 1

# 5. Cleanup
pkill ollama
```

### 8. HPC Helper Scripts (Automated Operations)

To streamline interactions with the Nautilus cluster from a local machine (especially when using Bastion/ProxyJump), several Python paramiko scripts are provided in the `scratch/` directory. These scripts allow you to monitor, debug, and submit jobs without needing an interactive SSH shell.

*   `scratch/check_new_jobs.py`: Connects via Bastion SSH to check active queue/sacct for specific job IDs.
*   `scratch/sync_files.py`: Synchronizes modified files from the local workspace to the project directory on Nautilus.
*   `scratch/patch_and_resubmit.py`: Automates patching local slurm scripts, uploading them, cancelling running jobs, and submitting the batch jobs.
*   `scratch/tail_log.py`: Helper script to tail specific log files on Nautilus over SSH.
*   `scratch/check_llama_jobs_sacct.py`: Uses `sacct` and `squeue` to list the state of recent Llama jobs.
*   `scratch/monitor_progress.py`: Actively tails the log files of running simulation jobs to extract real-time execution progress (e.g., "Round 30/60").
*   `scratch/check_new_quality.py`: Scans completed `event_results.json` files to verify if `evaluator_fallback` was erroneously triggered, ensuring the quality of the generated personas.
*   `scratch/check_massive_fails.py`: Deploys an `srun` payload to the compute node to read the `simulation.log` directly from the node-local NVMe scratch (`$SLURM_TMPDIR`), bypassing NFS sync delays.
*   `scratch/submit_massive_final.py`: A master script that cleanly cancels old jobs, dynamically generates a Slurm configuration based on the robust `run_user_campaign_massive.slurm` template, and dispatches batch jobs ensuring 100% intelligent persona generation (disabling fallbacks).

**Usage Example:**
```bash
# Monitor the progress of currently running jobs
python scratch/monitor_progress.py
```

### 8. Model Architecture & Storage (Nautilus)

Models on Nautilus are managed via a hybrid approach: external GGUF files for specific versions and native Ollama pulls for standard library models.

**Storage Locations:**
- **Raw GGUF Models:** `/scratch/nautilus/users/mhnguyn2025@ec-nantes.fr/ecnbench/models/`
- **Ollama Internal Storage:** `/scratch/nautilus/users/mhnguyn2025@ec-nantes.fr/ecnbench/ollama_storage/` (Controlled by `OLLAMA_MODELS` env var)

**Available Models (GGUF Source):**
| Model Name (Ollama) | Source File (.gguf) |
|---|---|
| `mistral-nemo` | `Mistral-Nemo-Instruct-2407-Q4_K_M.gguf` |
| `mistralsmall` | `Mistral-Small-4-2603-Q4_K_M.gguf` |
| `gemma27b` | `gemma-2-27b-it-Q4_K_M.gguf` |
| `nomic` | `nomic-embed-text-v1.5.Q4_K_M.gguf` |

**Pulled Models (Ollama Registry):**
- `gemma:2b`, `gemma2:27b`, `gemma4:26b`
- `mistral:latest`, `mistral-large:latest`, `mistral-nemo:latest`
- `qwen2.5:7b`, `qwen3.6:27b`
- `gpt-oss:20b`
- `nomic-embed:latest`

**Workflow for New Models:**
1. Download GGUF to the `models/` directory.
2. Create/Update a `Modelfile_<name>` pointing to the GGUF.
3. Run `ollama create <name> -f Modelfile_<name>` within your Slurm job.

---

## HPC Operations & Troubleshooting Guide (Nautilus)

This section provides step-by-step instructions for developers to access the HPC, monitor jobs, and debug issues.

### 1. Accessing the Cluster

Access requires a configured SSH config (typically in `~/.ssh/config`). Use the `Nautilus` alias:

```bash
ssh Nautilus
```

If you need to run commands without entering an interactive shell:
```bash
ssh Nautilus "squeue --me"
```

### 2. Finding Files and Logs

The project is located in the scratch directory:
- **Project Root:** `/scratch/nautilus/users/$USER/ECN-HPC-DEPLOY`
- **Benchmark Logs:** `MiroFish-Offline/backend/logs/benchmark_runs/`

To find recent log files:
```bash
ssh Nautilus "ls -lt /scratch/nautilus/users/\$(whoami)/ECN-HPC-DEPLOY/MiroFish-Offline/backend/logs/benchmark_runs"
```

### 3. Monitoring Jobs

- **Check active jobs:** `squeue --me`
- **Check job history (last 24h):** `sacct -S \$(date -d '1 day ago' +%Y-%m-%d) --format=JobID,JobName,State,ExitCode,Elapsed`
- **View real-time simulation progress:**
  ```bash
  ssh Nautilus "tail -f /scratch/nautilus/users/\$(whoami)/ECN-HPC-DEPLOY/MiroFish-Offline/backend/logs/benchmark_runs/<model_name>/<run_id>/<event_id>/simulation.log"
  ```

### 4. Common Troubleshooting

#### Model Not Found (404)
If a job fails with "model not found", check available models in the active Ollama instance:
```bash
ssh Nautilus "ollama list"
```
**Note:** Ollama must be running as a background process within the Slurm job for this to work during execution.

#### Invalid Options (e.g., 'min_p' error)
Some models or Ollama versions may reject specific sampling parameters. If you see `invalid options: min_p` or similar, it usually means the LLM client is sending an unsupported parameter.

**Fix:** The `backend/app/utils/llm_client.py` has been upgraded with **Robust Parameter Filtering**. It now recursively strips `min_p`, `top_k`, and penalty parameters from both top-level `kwargs` and nested `extra_body['options']`. If errors persist, check `simulation.log` for the "Ollama Request Check" diagnostic warnings to see exactly which parameters are being passed. Ensure the HPC has the latest version of this file.

#### Corrupted Binaries or Models (The "Empty File" Trap)
If you see errors like `bash: ollama: command not found` or `model not found` despite the files existing:
1. **Check file size:** 
   - A valid Ollama binary is **~300MB**.
   - A valid GGUF model is usually **>5GB**.
   - If a file is only a few bytes (e.g., 9B, 29B), it is **corrupted**.
2. **Check file content:** Corrupted files often contain download error messages.
   ```bash
   # Example: If this returns "Invalid username or password" or "Not Found", delete and re-upload.
   ssh Nautilus "cat /scratch/nautilus/users/\$(whoami)/ecnbench/models/my_model.gguf"
   ```

#### PATH Logic (HOME vs SCRATCH)
Always prefer the binary stored in your **HOME** directory for stability:
```bash
# Correct PATH setup in Slurm scripts
export PATH="\$HOME/ecnbench/bin:\$PATH"
```
Avoid using binaries in the scratch directory as they are more prone to accidental corruption during large data syncs.

#### Line Break Errors (Windows to Linux)
If `sbatch` fails with "Batch script contains DOS line breaks", fix it on the HPC before running:
```bash
tr -d '\r' < script_windows.slurm > script_unix.slurm
sbatch script_unix.slurm
```

#### Ollama Service Verification
Within a running job or debug session, you can verify if Ollama is actually responding:
```bash
# Check loaded models and versions
ssh Nautilus "export PATH=\$HOME/ecnbench/bin:\$PATH; ollama list"
```

#### Fix: Sync from Local
If downloading directly to the HPC fails (common for gated models or expired tokens), download locally and use `scp` to push:
```bash
scp ./models/my_model.gguf Nautilus:/scratch/nautilus/users/\$USER/ecnbench/models/
```

#### Short Execution Time
If a simulation finishes in seconds (e.g., < 1 minute) but was configured for many rounds:
1. Check `simulation.log` for LLM connection errors (e.g., 400 or 404).
2. Verify that Neo4j is reachable (`bolt://localhost:7687`).
3. Check `summary.json` for `evaluator_fallback` or high Brier scores indicating failed inference.

#### Small Model Constraints & Execution Failures (Gemma 1.1 2B / CodeGemma 7B)
If running small models (<15B parameters) on the Nautilus HPC cluster, jobs might fail early or crash with out-of-memory errors due to strict configuration limits and guided decoding bugs:
1. **Context length limit**: Models supporting 8K context (like Gemma 1.1 2B and CodeGemma 7B) must be explicitly configured with `--max-model-len 8192` in Slurm scripts. By default, vLLM may launch with a lower default limit (e.g., 4096), causing `Error 400` when event prompts combined with target outputs exceed the limit.
2. **GPU Memory Allocation**: Setting context length to 8K requires increasing `--gpu-memory-utilization` to at least `0.40` (for Gemma 1.1 2B) or `0.45` (for CodeGemma 7B). A lower value (like `0.20` in older batch scripts) will cause the vLLM server to crash with OOM errors during KV cache allocation at startup.
3. **The Guided-Decoding JSON Schema Mismatch**: Local vLLM instances running AWQ/quantized models do not support `json_schema` guided-decoding (via outlines) due to compiler errors/hangs. Consequently, small models (<15B) consistently fail to generate valid JSON lists for Stage 1 stakeholder extraction under the original unmodified system code, immediately throwing `ValueError: Intelligent persona generation failed` and aborting.
4. **Recommendation**: Unless the system code is patched to support non-strict JSON parsing/fallbacks, small models (<15B) must be **skipped** for local HPC execution, or run exclusively in cloud-guided environments (e.g., OpenRouter) that guarantee schema enforcement.

---

## Architecture v5.15: Tool-Call & Persona Diversity Repair (2026-06-23)

Two production defects were diagnosed and patched from the Llama-3.1-8B AWQ campaign (`scratch/llama_results_10947512/`):

### Defect #2 — Agents performed ZERO social interactions
**Symptom:** `C8_B_r1/reddit/actions.jsonl` contained only `TELEMETRY_PROBE` (×600) and `CREATE_POST` (×2). No `LIKE_POST`, `DISLIKE_POST`, `CREATE_COMMENT`, `FOLLOW`, `REPOST`, etc. Twitter finished in 90s for 120 rounds (impossible if real interactions occur).

**Root causes discovered & resolved (2026-06-23):**
1. **vLLM Auto Tool Choice (HTTP 400)**: When client requests `tool_choice="auto"`, vLLM throws a `BadRequestError: "auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set` unless `--enable-auto-tool-choice` is explicitly provided in the server CLI.
2. **Missing `curl` on Compute Nodes**: The wait loops inside Slurm templates used `curl` to verify if vLLM started up. Because `curl` is missing on Nautilus compute nodes, the loop hung forever or triggered false timeouts.
3. **Empty Username in Container**: Inside the Nautilus Slurm container, `USER_ID=$(whoami)` failed (`whoami: cannot find name for user ID 8001273`), causing directories to point to invalid paths like `/scratch/nautilus/users//ECN-HPC-DEPLOY` and crash with permission errors.

**Fixes:**
1. **vLLM Auto Tool Choice**: Added `--enable-auto-tool-choice` to all vLLM launch commands in `run_user_campaign.slurm` and `run_tool_call_test.slurm`.
2. **Robust Socket Check**: Replaced all `curl` checks with a lightweight Python socket check:
   ```bash
   while ! python3 -c "import socket; s = socket.socket(); s.connect(('127.0.0.1', $VLLM_PORT))" 2>/dev/null
   ```
   For multi-server checks (e.g., in `run_user_campaign.slurm`):
   ```bash
   while ! python3 -c "import socket; [socket.socket().connect(('127.0.0.1', p)) for p in ($VLLM_PORT, $VLLM_GRAPH_PORT, $VLLM_EVAL_PORT)]" 2>/dev/null
   ```
3. **Hardcoded User Fallback**: Replaced `USER_ID=$(whoami)` with a hardcoded export:
   ```bash
   USER_ID="mhnguyn2025@ec-nantes.fr"
   ```
4. **Tool Sanitization**: Stripped `strict`, `additionalProperties`, and `$defs` from CAMEL's tool definitions before sending to vLLM.

### Defect #1 — Persona diversity collapse (300 "Political Analyst" clones)
**Symptom:** `reddit_profiles.json` had `name == "Political Analyst"` for all 300 agents, `username` pattern `context_0_*`, and 44% of `profession` values were "*Analyst*". The swarm was behaviourally homogeneous, invalidating Claim 1 (Prediction Lift) and Dimension 7 (Information Diversity).

**Root cause:** when intelligent generation + synthetic micro-batches failed (a downstream casualty of the same vLLM 400 crash affecting `chat_json`/expansion), `expand_profiles_to_target` fell to its rule-based fallback which deep-copied a SINGLE base profile `needed` times. `build_base_profile` also hardcoded the name "Political Analyst" for every `context.md` seed, and the checkpoint preflight short-circuited to one profile.

**Fix:**
- `protocol.py` rule-based fallback now rotates distinct first/last names, professions, countries, MBTI, ages, and DNA templates per replica (no two clones identical).
- `build_base_profile` (in both `run_ecnbench_protocol.py` and `run_ecnbench_protocol_hpc.py`) is now index-aware: rotates a pool of names/professions/countries instead of collapsing to "Political Analyst".
- New toggle `BUST_PERSONA_CHECKPOINT=true` discards a stale/poisoned checkpoint (e.g. one that captured the 300 clones) and regenerates diverse personas from scratch.

### Validating the fixes — C8 smoke test orchestrator

A self-contained paramiko orchestrator runs the whole validation over SSH (bastion → Nautilus), mirroring the `scratch/sync_files.py` / `scratch/submit_massive_final.py` patterns documented in the HPC Operations section above.

**Files involved:**
| File | Role |
|---|---|
| `scratch/run_c8_smoke_v515.slurm` | 1-GPU+1-GPU smoke job: 300 agents, 60 rounds, event C8, conditions A/B/C. Enables `--enable-auto-tool-choice --tool-call-parser hermes`, exports `BUST_PERSONA_CHECKPOINT=true` and `DISABLE_TOOL_USE=false`. |
| `scratch/run_c8_smoke_v515.py` | Paramiko orchestrator: SYNC patched files + slurm → SUBMIT → POLL → VERIFY. |

**Run it (from repo root, Windows PowerShell):**

```powershell
# Ensure paramiko is available
pip install paramiko

# Full pipeline: sync patched files, submit, poll up to 3h, then verify
python scratch\run_c8_smoke_v515.py

# If files were already synced (e.g. you re-ran after editing only the slurm):
python scratch\run_c8_smoke_v515.py --skip-sync

# Just re-check the latest completed run without submitting a new job:
python scratch\run_c8_smoke_v515.py --verify-only

# Extend poll window for a slow queue:
python scratch\run_c8_smoke_v515.py --poll-timeout 14400
```

**What the verifier checks (remote Python on Nautilus):**
1. Locates the newest `C8_B_r1` run directory under `/scratch/waves/users/<USER>/ecnbench_workspace/simulation_logs/`.
2. Parses `reddit/actions.jsonl` and counts `action_type`. Asserts ≥ 5 social actions (`LIKE_POST`/`DISLIKE_POST`/`CREATE_COMMENT`/`LIKE_COMMENT`/`DISLIKE_COMMENT`/`FOLLOW`/`REPOST`/`QUOTE_POST`).
3. Parses `reddit_profiles.json` and asserts ≥ 30 unique `name` values (was 1 before the fix).
4. Prints `VERDICT: PASS` / `VERDICT: FAIL` with the reason.

**Expected outcome after v5.15:**
- `ACTION_COUNTS` shows a healthy mix including `LIKE_POST`, `CREATE_COMMENT`, `FOLLOW` (not just telemetry).
- `UNIQUE_NAMES` ≈ 300 (or ≥ 30 if the rule-based fallback kicked in).
- Twitter/Reddit rounds take **minutes**, not 90 seconds.
- `summary.json` `evaluator_unstable` should no longer drop 6/7 dimensions.

**If VERDICT is FAIL:**
- Check `$PROJECT_ROOT/logs/vllm_c8_bench_<JOB>.log` for remaining `400` / `strict` errors → confirm `--enable-auto-tool-choice --tool-call-parser hermes` are present in the launch command.
- If tool 400s persist for this model, set `export DISABLE_TOOL_USE='true'` in the slurm (last-resort; OASIS will use text-action parsing).
- Check `simulation.log` for `BUST_PERSONA_CHECKPOINT=true: deleting stale checkpoint` → confirms a poisoned checkpoint was cleared.
- Re-run `python scratch\run_c8_smoke_v515.py --verify-only` after a manual fix.

### Promoting to the full 30-event campaign

Once the C8 smoke test passes, replicate the same two vLLM flags + the three env toggles (`BUST_PERSONA_CHECKPOINT`, `DISABLE_TOOL_USE=false`, `ENABLE_FJ_ANCHORING`/`ENABLE_MEAN_FIELD_AGGREGATION`) into `scratch/run_user_campaign_massive_llama.slurm` (or your production template), then re-sync and submit with `scratch/submit_massive_final.py`.

---

## License


AGPL-3.0. See [LICENSE](./LICENSE).

## Credits

Modified fork of [MiroFish](https://github.com/666ghj/MiroFish).  
Simulation stack includes OASIS/CAMEL-AI components, with local-first infrastructure integration in this repository.
