# SAMKY Studio interface

SAM now uses one visual system for setup, graph preparation, simulation, reports, and interviews. Existing project, simulation, report, and interaction URLs open the new interface.

## Start a simulation

1. Add a name, a question, and PDF, Markdown, or TXT sources (50 MB total).
2. Choose **Offline** for Ollama or your own OpenAI-compatible server, or **Online** for a hosted provider. Enter the API base URL, discover available models, or enter a model ID directly.
3. Enter an API key if the endpoint needs one. **Remove key** clears the key from the pending settings. Settings are applied when you press **Start simulation**. Keys are kept in the server process and are never placed in project files, browser storage, or runtime responses. Restarting the server restores its `.env` configuration.
4. Select the round count on this first page. **60 is the default recommendation**; valid values are 1–1,000. Select either community or both.
5. Press **Start simulation** once. Document processing, graph construction, persona preparation, and simulation start automatically. The running workspace shows the graph and a progress bar. Select an entity for details; drag, zoom, or reset the graph view.

The round count is saved in the project, then applied as the exact simulation duration. The legacy REST/CLI `max_rounds` parameter retains its truncation behavior. Round progress follows the slower community when both are enabled. Stopping is shown separately from successful completion.

Persona preparation uses 12 concurrent model requests for online providers and retains 5 for offline servers. API callers can explicitly set `parallel_profile_count` from 1 to 32. This affects new preparation tasks; a task already running keeps its original worker count.

## Reports and interviews

After the simulation finishes, choose **Create report** or **Interview agents**. Interviews do not require generating a report first. A report adds the report analyst as a conversation target.

Each person has a separate conversation. **Group interview** sends one question to the selected people. Conversations are retained in session storage for the current browser tab and can be exported as Markdown. The interface reports unavailable interview environments and request errors. **Close interview session** gracefully releases the OASIS process when you finish.

Model settings apply to one server process. SAM prevents changing them during model requests, preparation/report tasks, or a live simulation/interview environment. Local embeddings and Neo4j still use their existing server configuration.

## Development checks

```powershell
cd frontend
npm run build
node --test --test-isolation=none tests/run-state.test.mjs
cd ../backend
.\.venv311\Scripts\python -m pytest tests/test_studio_ui_contract.py -q
```

`frontend/tests/mock-api.mjs` is an optional synthetic fixture server for UI development. It never calls a real model or graph database. Start it with `node tests/mock-api.mjs`, then run Vite in a separate terminal with `VITE_API_BASE_URL=http://127.0.0.1:5181`. Do not use this fixture endpoint for real simulations.

Before a real run, verify the selected model, Ollama embeddings, and Neo4j are available. The remaining manual acceptance checks are a real model run through the chosen round count, report generation, individual/group interviews, and responsive layouts on your devices.
