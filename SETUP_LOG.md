# Environment Setup Log

This document records the steps taken to prepare the MiroFish-Offline environment for simulations.

## Prerequisites Verified
- **Node.js:** v24.13.0
- **Python:** 3.14.2
- **uv:** 0.10.11
- **Docker:** Installed and active.

## Setup Steps

### 1. Dependency Installation
- **Root:** `npm install` completed.
- **Frontend:** `npm install` in `frontend/` completed.
- **Backend:** `uv sync` in `backend/` completed.

### 2. Configuration
- `.env` file created in `MiroFish-Offline/` with local settings for Ollama and Neo4j.
- Verified `OPENROUTER_*` routing for benchmark roles.

### 3. Infrastructure Initialization
- **Docker Desktop:** Started.
- **Neo4j Container:** Launched using `scripts/start_neo4j_local.py`.
- **Status:** Neo4j is running at `bolt://localhost:7687` (Container: `mirofish-neo4j`).

### 4. Data Mapping
- Verified existence of research seeds and event data:
  - `data/seeds/`
  - `data/events_raw.json`
  - `data/injections/`

## Verification
- Run `docker ps` to ensure `mirofish-neo4j` is running.
- Ensure Ollama is running locally at `http://localhost:11434`.
