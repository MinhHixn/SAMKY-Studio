# Offline Ollama Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate MiroFish benchmark LLM routing from OpenRouter-default to local Ollama-default (offline-first) with strict model identity verification, deterministic controls, and resilient local retry behavior while keeping current simulation architecture unchanged.

**Architecture:** Keep the existing Flask → services → benchmark orchestration flow and inject all behavior changes at config, role-router, and LLM client boundaries. Add provider-mode and model-identity verification in `role_router`, extend config contract for local/cloud switching, and keep OpenAI SDK with `base_url` override in `LLMClient`. Preserve benchmark manifest compatibility by adding fields rather than replacing existing ones.

**Tech Stack:** Python 3.11, Flask, OpenAI SDK (`openai>=1.0.0`), Neo4j, pytest, dotenv, Ollama OpenAI-compatible endpoint.

---

## File Structure (planned changes)

### Core runtime files

- **Modify:** `backend/app/config.py`
  - Responsibility: load/validate new env contract (`LLM_PROVIDER_MODE`, role-model envs, local verification flags, deterministic local mode vars).
- **Modify:** `backend/app/benchmarks/role_router.py`
  - Responsibility: resolve provider mode + role models + local model identity verification metadata.
- **Modify:** `backend/app/utils/llm_client.py`
  - Responsibility: provider-aware timeout/retry policy and deterministic local behavior without breaking benchmark enforcement.
- **Modify:** `backend/scripts/run_ecnbench_protocol.py`
  - Responsibility: include model verification metadata in manifest while preserving existing keys.

### Tests

- **Create:** `backend/tests/test_llm_local_mode_config.py`
  - Responsibility: focused config contract tests for local-first env handling.
- **Modify:** `backend/tests/test_benchmark_role_router.py`
  - Responsibility: router mode selection and local verification behavior tests.
- **Modify:** `backend/tests/test_llm_client_openrouter.py`
  - Responsibility: local retry + deterministic local mode tests.
- **Modify:** `backend/tests/test_run_ecnbench_protocol.py`
  - Responsibility: manifest schema compatibility + new model identity fields.

### Docs & ops assets

- **Modify:** `.env.example`
  - Responsibility: local-first env template with dual-mode controls.
- **Create:** `backend/scripts/setup_ollama.sh`
  - Responsibility: pull/check required local models and embeddings.
- **Create:** `MIGRATION_GUIDE.md`
  - Responsibility: cloud/local switching instructions, strict benchmark checklist, PowerShell equivalents.

---

### Task 1: Add local-first config contract (TDD first)

**Files:**
- Create: `backend/tests/test_llm_local_mode_config.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_llm_local_mode_config.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_llm_local_mode_config.py
import importlib


def test_local_mode_defaults(monkeypatch):
    import app.config as config_module

    monkeypatch.setenv("LLM_PROVIDER_MODE", "local")
    monkeypatch.setenv("LLM_BASE_URL", "http://172.20.10.3:11434/v1")
    monkeypatch.setenv("LLM_API_KEY", "ollama")
    monkeypatch.setenv("ROLE_MODEL_GRAPH", "qwen2.5:7b")
    monkeypatch.setenv("ROLE_MODEL_BENCHMARK", "qwen2.5:14b")
    monkeypatch.setenv("ROLE_MODEL_EVALUATOR", "qwen2.5:14b")
    monkeypatch.setenv("VERIFY_LOCAL_MODEL", "true")
    monkeypatch.setenv("ALLOW_UNVERIFIED_LOCAL", "false")
    monkeypatch.setenv("DETERMINISTIC_MODE", "true")
    monkeypatch.setenv("RANDOM_SEED", "1337")

    config_module = importlib.reload(config_module)
    cfg = config_module.Config

    assert cfg.LLM_PROVIDER_MODE == "local"
    assert cfg.LLM_BASE_URL == "http://172.20.10.3:11434/v1"
    assert cfg.ROLE_MODEL_GRAPH == "qwen2.5:7b"
    assert cfg.ROLE_MODEL_BENCHMARK == "qwen2.5:14b"
    assert cfg.ROLE_MODEL_EVALUATOR == "qwen2.5:14b"
    assert cfg.VERIFY_LOCAL_MODEL is True
    assert cfg.ALLOW_UNVERIFIED_LOCAL is False
    assert cfg.DETERMINISTIC_MODE is True
    assert cfg.RANDOM_SEED == 1337
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_llm_local_mode_config.py::test_local_mode_defaults -v`  
Expected: FAIL with missing `Config` attributes (`LLM_PROVIDER_MODE`, `ROLE_MODEL_GRAPH`, etc.).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/config.py (inside Config)
LLM_PROVIDER_MODE = os.environ.get("LLM_PROVIDER_MODE", "local").strip().lower()
ROLE_MODEL_GRAPH = os.environ.get("ROLE_MODEL_GRAPH") or os.environ.get("OPENROUTER_GRAPH_MODEL") or LLM_MODEL_NAME
ROLE_MODEL_BENCHMARK = os.environ.get("ROLE_MODEL_BENCHMARK") or os.environ.get("OPENROUTER_BENCHMARK_MODEL") or LLM_MODEL_NAME
ROLE_MODEL_EVALUATOR = os.environ.get("ROLE_MODEL_EVALUATOR") or os.environ.get("OPENROUTER_EVALUATOR_MODEL") or LLM_MODEL_NAME
VERIFY_LOCAL_MODEL = _env_bool("VERIFY_LOCAL_MODEL", True)
ALLOW_UNVERIFIED_LOCAL = _env_bool("ALLOW_UNVERIFIED_LOCAL", False)
DETERMINISTIC_MODE = _env_bool("DETERMINISTIC_MODE", False)
RANDOM_SEED = _env_int_or_raw("RANDOM_SEED", 42)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_llm_local_mode_config.py::test_local_mode_defaults -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_llm_local_mode_config.py backend/app/config.py
git commit -m "feat: add local-first llm config contract"
```

---

### Task 2: Refactor role router to provider-mode + local model verification

**Files:**
- Modify: `backend/app/benchmarks/role_router.py`
- Modify: `backend/tests/test_benchmark_role_router.py`
- Test: `backend/tests/test_benchmark_role_router.py`

- [ ] **Step 1: Write the failing test**

```python
def test_router_uses_role_model_envs_in_local_mode(monkeypatch):
    from app import config as config_module
    from app.benchmarks import role_router as role_router_module

    monkeypatch.setattr(config_module.Config, "LLM_PROVIDER_MODE", "local", raising=False)
    monkeypatch.setattr(config_module.Config, "LLM_BASE_URL", "http://172.20.10.3:11434/v1", raising=False)
    monkeypatch.setattr(config_module.Config, "LLM_API_KEY", "ollama", raising=False)
    monkeypatch.setattr(config_module.Config, "ROLE_MODEL_GRAPH", "qwen2.5:7b", raising=False)
    monkeypatch.setattr(config_module.Config, "ROLE_MODEL_BENCHMARK", "qwen2.5:14b", raising=False)
    monkeypatch.setattr(config_module.Config, "ROLE_MODEL_EVALUATOR", "qwen2.5:14b", raising=False)

    router = role_router_module.BenchmarkRoleRouter.from_config(config_module.Config)
    assert router.model_for("graph") == "qwen2.5:7b"
    assert router.model_for("benchmark") == "qwen2.5:14b"
    assert router.model_for("evaluator") == "qwen2.5:14b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_role_router.py::test_router_uses_role_model_envs_in_local_mode -v`  
Expected: FAIL because router still hardcodes `OPENROUTER_*` fields.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/benchmarks/role_router.py (from_config path)
provider_mode = getattr(config, "LLM_PROVIDER_MODE", "local")
if provider_mode == "local":
    base_url = getattr(config, "LLM_BASE_URL", None)
    api_key = getattr(config, "LLM_API_KEY", None)
    graph_model = getattr(config, "ROLE_MODEL_GRAPH", None)
    benchmark_model = getattr(config, "ROLE_MODEL_BENCHMARK", None)
    evaluator_model = getattr(config, "ROLE_MODEL_EVALUATOR", None)
else:
    base_url = getattr(config, "OPENROUTER_BASE_URL", None)
    api_key = getattr(config, "OPENROUTER_API_KEY", None) or getattr(config, "LLM_API_KEY", None)
    graph_model = getattr(config, "OPENROUTER_GRAPH_MODEL", None) or getattr(config, "ROLE_MODEL_GRAPH", None)
    benchmark_model = getattr(config, "OPENROUTER_BENCHMARK_MODEL", None) or getattr(config, "ROLE_MODEL_BENCHMARK", None)
    evaluator_model = getattr(config, "OPENROUTER_EVALUATOR_MODEL", None) or getattr(config, "ROLE_MODEL_EVALUATOR", None)
```

- [ ] **Step 4: Add verification behavior tests**

```python
def test_local_verification_required_in_benchmark_mode(monkeypatch):
    from app import config as config_module
    from app.benchmarks import role_router as role_router_module

    monkeypatch.setattr(config_module.Config, "LLM_PROVIDER_MODE", "local", raising=False)
    monkeypatch.setattr(config_module.Config, "BENCHMARK_MODE", True, raising=False)
    monkeypatch.setattr(config_module.Config, "VERIFY_LOCAL_MODEL", True, raising=False)
    monkeypatch.setattr(config_module.Config, "ALLOW_UNVERIFIED_LOCAL", False, raising=False)

    with pytest.raises(ValueError, match="local model identity verification"):
        role_router_module.BenchmarkRoleRouter.from_config(config_module.Config)
```

- [ ] **Step 5: Run router tests**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_role_router.py -q`  
Expected: PASS for existing + new tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/benchmarks/role_router.py backend/tests/test_benchmark_role_router.py
git commit -m "feat: add dual-mode role router with local model identity checks"
```

---

### Task 3: Extend LLM client for local resilience + deterministic local mode

**Files:**
- Modify: `backend/app/utils/llm_client.py`
- Modify: `backend/tests/test_llm_client_openrouter.py`
- Test: `backend/tests/test_llm_client_openrouter.py`

- [ ] **Step 1: Write the failing deterministic-local test**

```python
def test_local_deterministic_mode_sets_seed_when_not_benchmark(monkeypatch):
    from app.utils import llm_client as llm_client_module
    store = {}
    _install_fake_openai(monkeypatch, store)

    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "DETERMINISTIC_MODE", True, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "RANDOM_SEED", 1337, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "http://172.20.10.3:11434/v1", raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "ollama", raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "qwen2.5:14b", raising=False)

    client = llm_client_module.LLMClient()
    client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.4)

    assert store["create_kwargs"]["seed"] == 1337
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_llm_client_openrouter.py::test_local_deterministic_mode_sets_seed_when_not_benchmark -v`  
Expected: FAIL because seed is not injected for non-benchmark local deterministic mode.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/utils/llm_client.py
self._deterministic_mode = bool(getattr(Config, "DETERMINISTIC_MODE", False))
self._random_seed = self._try_int(getattr(Config, "RANDOM_SEED", 42))

def _apply_local_determinism(self, request_kwargs: Dict[str, Any]) -> None:
    if self._benchmark_mode:
        return
    if not self._is_local_provider():
        return
    if not self._deterministic_mode:
        return
    if self._random_seed is not None and request_kwargs.get("seed") is None:
        request_kwargs["seed"] = self._random_seed
```

- [ ] **Step 4: Add provider-aware retry test for local busy signal**

```python
def test_local_busy_error_retries_with_backoff(monkeypatch):
    from app.utils import llm_client as llm_client_module
    store = {"calls": 0, "sleep_calls": []}

    class LocalBusyError(Exception):
        pass

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            if store["calls"] == 1:
                raise LocalBusyError("queue is full")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module.time, "sleep", store["sleep_calls"].append)
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "http://172.20.10.3:11434/v1", raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", 2, raising=False)

    client = llm_client_module.LLMClient()
    assert client.chat(messages=[{"role": "user", "content": "x"}]) == "ok"
    assert store["calls"] == 2
    assert store["sleep_calls"]
```

- [ ] **Step 5: Run llm client test file**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_llm_client_openrouter.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/utils/llm_client.py backend/tests/test_llm_client_openrouter.py
git commit -m "feat: add deterministic local mode and resilient local retry behavior"
```

---

### Task 4: Update env template, provisioning script, and migration guide

**Files:**
- Modify: `.env.example`
- Create: `backend/scripts/setup_ollama.sh`
- Create: `MIGRATION_GUIDE.md`
- Test: `backend/scripts/setup_ollama.sh` (dry-run lint + command preview)

- [ ] **Step 1: Write doc/ops tests first (failing checks)**

```bash
# from repo root
rg "LLM_PROVIDER_MODE|ROLE_MODEL_GRAPH|VERIFY_LOCAL_MODEL|ALLOW_UNVERIFIED_LOCAL|DETERMINISTIC_MODE|RANDOM_SEED" .env.example
```

Expected initially: some keys missing in `.env.example`.

- [ ] **Step 2: Update `.env.example`**

```dotenv
LLM_PROVIDER_MODE=local
LLM_BASE_URL=http://172.20.10.3:11434/v1
LLM_API_KEY=ollama

ROLE_MODEL_GRAPH=qwen2.5:7b
ROLE_MODEL_BENCHMARK=qwen2.5:14b
ROLE_MODEL_EVALUATOR=qwen2.5:14b

VERIFY_LOCAL_MODEL=true
ALLOW_UNVERIFIED_LOCAL=false
DETERMINISTIC_MODE=false
RANDOM_SEED=42
LLM_TIMEOUT_SECONDS=120
```

- [ ] **Step 3: Add provisioning script**

```bash
# backend/scripts/setup_ollama.sh
#!/usr/bin/env bash
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://172.20.10.3:11434}"

curl -fsS "${OLLAMA_HOST}/api/tags" >/dev/null
curl -fsS "${OLLAMA_HOST}/api/pull" -d '{"name":"qwen2.5:7b"}'
curl -fsS "${OLLAMA_HOST}/api/pull" -d '{"name":"qwen2.5:14b"}'
curl -fsS "${OLLAMA_HOST}/api/pull" -d '{"name":"nomic-embed-text"}'
curl -fsS "${OLLAMA_HOST}/api/tags"
```

- [ ] **Step 4: Add migration guide**

```markdown
# MIGRATION_GUIDE
## Local mode (default)
- Set `LLM_PROVIDER_MODE=local`
- Set `LLM_BASE_URL` and role models
- Run `backend/scripts/setup_ollama.sh`

## Cloud mode
- Set `LLM_PROVIDER_MODE=cloud`
- Provide `OPENROUTER_*` credentials/model ids

## PowerShell equivalent
curl http://172.20.10.3:11434/api/pull -d '{\"name\":\"qwen2.5:14b\"}'
curl http://172.20.10.3:11434/api/pull -d '{\"name\":\"nomic-embed-text\"}'
```

- [ ] **Step 5: Validate docs/scripts**

Run:

```bash
rg "LLM_PROVIDER_MODE|ROLE_MODEL_GRAPH|VERIFY_LOCAL_MODEL|ALLOW_UNVERIFIED_LOCAL|DETERMINISTIC_MODE|RANDOM_SEED" .env.example
bash backend/scripts/setup_ollama.sh || true
```

Expected:

- env keys found
- script reaches endpoint checks (or fails clearly if host unavailable)

- [ ] **Step 6: Commit**

```bash
git add .env.example backend/scripts/setup_ollama.sh MIGRATION_GUIDE.md
git commit -m "docs: add offline migration guide and ollama provisioning script"
```

---

### Task 5: Preserve manifest compatibility and add local identity fields

**Files:**
- Modify: `backend/scripts/run_ecnbench_protocol.py`
- Modify: `backend/tests/test_run_ecnbench_protocol.py`
- Test: `backend/tests/test_run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing manifest test**

```python
def test_manifest_includes_local_model_identity_fields(monkeypatch, tmp_path):
    from scripts import run_ecnbench_protocol as protocol_script

    manifest = {
        "run_id": "x",
        "telemetry_mode": "neo4j",
        "neo4j_connected": True,
        "telemetry_required": True,
    }
    manifest.update(
        {
            "model_name": "qwen2.5:14b",
            "model_digest": "sha256:test",
            "model_resolved": True,
            "verification_source": "api_tags",
        }
    )
    protocol_script._write_run_manifest(tmp_path, manifest)
    payload = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert payload["model_name"] == "qwen2.5:14b"
```

- [ ] **Step 2: Run failing test**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_run_ecnbench_protocol.py::test_manifest_includes_local_model_identity_fields -v`  
Expected: FAIL before manifest payload wiring is added.

- [ ] **Step 3: Add manifest wiring**

```python
# backend/scripts/run_ecnbench_protocol.py (manifest construction)
manifest["model_name"] = resolved_model_identity.get("model_name")
manifest["model_digest"] = resolved_model_identity.get("model_digest")
manifest["model_resolved"] = bool(resolved_model_identity.get("model_resolved"))
manifest["verification_source"] = resolved_model_identity.get("verification_source")
```

- [ ] **Step 4: Run protocol tests**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_run_ecnbench_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: include local model identity metadata in benchmark manifest"
```

---

### Task 6: End-to-end validation (strict local mode, no cloud dependency)

**Files:**
- Modify: none (validation only)
- Test: runtime artifacts under `backend/logs/phase0_minimal_local_ollama`

- [ ] **Step 1: Set strict local env**

```powershell
cd backend
$env:LLM_PROVIDER_MODE='local'
$env:LLM_BASE_URL='http://172.20.10.3:11434/v1'
$env:LLM_API_KEY='ollama'
$env:ROLE_MODEL_GRAPH='qwen2.5:7b'
$env:ROLE_MODEL_BENCHMARK='qwen2.5:14b'
$env:ROLE_MODEL_EVALUATOR='qwen2.5:14b'
$env:VERIFY_LOCAL_MODEL='true'
$env:ALLOW_UNVERIFIED_LOCAL='false'
$env:DEV_MINIMAL_MODE='true'
$env:DEV_MINIMAL_AGENT_COUNT='60'
$env:DEV_MINIMAL_MAX_STEPS='30'
$env:DEV_MINIMAL_INJECTION_STEP='15'
$env:TELEMETRY_REQUIRED='true'
$env:HEADLESS_MODE='true'
```

- [ ] **Step 2: Execute minimal run**

```powershell
.\.venv311\Scripts\python scripts\run_ecnbench_protocol.py `
  --seeds-dir ..\..\data\seeds `
  --events-raw ..\..\data\events_raw.json `
  --injection-bank ..\..\data\injections\step30_injection_bank.json `
  --output-dir logs\phase0_minimal_local_ollama `
  --events 1 --repeats 1 `
  --trace-out logs\phase0_minimal_local_ollama\trace.jsonl
```

- [ ] **Step 3: Verify artifact contract**

```powershell
$run = Get-ChildItem logs\phase0_minimal_local_ollama | ? {$_.PSIsContainer} | Sort LastWriteTime | Select -Last 1
Get-Content "$($run.FullName)\run_manifest.json"
Get-Content "$($run.FullName)\event_results.json"
Get-Content "$($run.FullName)\summary.json"
```

Expected:

- all three files exist
- `telemetry_mode` is `neo4j`
- checkpoint telemetry present

---

## Final verification commands (after all tasks)

```bash
cd backend
.\.venv311\Scripts\python -m pytest tests\test_llm_local_mode_config.py tests\test_benchmark_role_router.py tests\test_llm_client_openrouter.py tests\test_run_ecnbench_protocol.py -q
```

Expected: all targeted tests PASS.

## Spec coverage check

- Local offline default with OpenAI SDK base_url override: covered by Tasks 1-3.
- Role-based local model mapping (`graph`, `benchmark`, `evaluator`): covered by Tasks 1-2.
- Retry/backoff+jitter and timeout tuning: covered by Task 3.
- Determinism (`DETERMINISTIC_MODE`, `RANDOM_SEED` with benchmark precedence): covered by Tasks 1 and 3.
- Env/dependency/provisioning deliverables: covered by Task 4.
- Manifest compatibility and strict telemetry-related fields: covered by Task 5.
- Minimal phase-0 validation and required artifacts: covered by Task 6.

