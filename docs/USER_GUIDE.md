# SAMKY Studio user guide

SAMKY Studio is an event-first interface built on the MiroFish-Offline pipeline: ingest source material, build a knowledge graph, generate an agent society, run social interactions, and optionally create a report.

Translations: [Tiếng Việt](USER_GUIDE_VI.md) · [Español](USER_GUIDE_ES.md)

## Choose a runtime

| Mode | Generation model | Event data | Best for |
|---|---|---|---|
| Offline | Ollama on your machine | Remains on your machine | Privacy and repeatable local work |
| Online | Your OpenAI-compatible endpoint | Prompts are sent to your provider | Stronger models or machines without enough RAM/GPU |
| Headless | Same server configuration | Same as the selected runtime | Batch jobs, notebooks, CI, and HPC |

Neo4j always stores the graph on your machine or Docker volume. In the default online setup, embeddings also stay local in Ollama; only generation requests go to the configured provider.

## 1. Run fully offline with Docker

Requirements: Docker Desktop/Engine with Compose v2. A 7B model generally needs at least 16 GB of system RAM; supported GPU acceleration is substantially faster.

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker exec mirofish-ollama ollama pull qwen2.5:7b
docker exec mirofish-ollama ollama pull nomic-embed-text
```

Open `http://localhost:3000`. The **Current environment** card should show that the model and Neo4j are ready. If a model has just finished downloading, press the refresh button.

Stop the stack without deleting data:

```powershell
docker compose down
```

Do not add `-v` unless you intentionally want to delete stored graphs and downloaded models.

## 2. Use an online model

Create a private configuration file:

```powershell
Copy-Item .env.online.example .env.online
```

Edit `.env.online` and set `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, and `OPENAI_API_KEY`. `OPENAI_API_BASE_URL` normally matches `LLM_BASE_URL`.

```powershell
docker compose -f compose.online.yml --env-file .env.online up -d --build
docker exec mirofish-embeddings ollama pull nomic-embed-text
```

Open `http://localhost:3000`. Studio detects **Online** from the configured endpoint. You can now enter or remove an API key on the setup page; it is kept in server memory and is not saved in browser storage.

## 3. Create a simulation in the UI

1. Enter an optional event name.
2. Ask a specific question. A useful question names a time horizon, stakeholders, and the signal you need—for example: “During the 30 days after the announcement, how might customers, the press, and competitors react, and what are the three largest reputation risks?”
3. Add at least one PDF, Markdown, or TXT source. Include only information the simulated society actually needs.
4. Choose online/offline, the API endpoint, model, and optional API key. Choose the number of rounds now; **60 rounds is recommended**.
5. Select **Start simulation**. Preparation runs automatically; the workspace shows the graph and progress bar.
6. After the run, generate a report or interview agents individually or as a group. See [the new interface guide](STUDIO_UI.md) for details.

## 4. Run without the UI

The CLI connects to the same API, so the server must already be running.

```powershell
python backend/scripts/sam_cli.py doctor
python backend/scripts/sam_cli.py run `
  --file .\examples\event.md `
  --goal "How will stakeholders react during the next 30 days?" `
  --name "Policy announcement" `
  --rounds 10 `
  --wait `
  --report
```

On Bash, use `\` instead of PowerShell backticks for line continuation. Repeat `--file` for multiple sources. The command prints JSON containing `project_id`, `graph_id`, `simulation_id`, and `report_id` when a report is requested.

Connect to another MiroFish server with `--base-url`:

```bash
python backend/scripts/sam_cli.py --base-url https://sam.example.com run \
  --file event.md --goal "Map stakeholder reactions" --rounds 20 --wait
```

## 5. Develop locally

```powershell
npm run setup
npm run setup:backend
npm run dev
```

The frontend runs at `http://localhost:3000`; the API runs at `http://localhost:5001`. Neo4j and Ollama still need to be available.

## Quick troubleshooting

- **Model not ready:** run `ollama list` or `docker exec mirofish-ollama ollama list`; the model name must exactly match `.env`.
- **Neo4j unavailable:** inspect `docker compose ps` and verify `NEO4J_PASSWORD`.
- **Online endpoint returns 401/403:** verify the key, `/v1` base URL, and model access.
- **Out of RAM/VRAM:** use a smaller local model, fewer agents/rounds, or an online endpoint.
- **First run feels slow:** ontology, graph, and personas are all generated before interaction begins. Validate with a short source and five rounds first.

## Safe interpretation

Do not send secrets, sensitive personal data, or unapproved documents to an online provider. Results depend on the source material, prompt, model, and persona assumptions. Record the configuration and consult domain experts before using a simulation in a consequential decision.
