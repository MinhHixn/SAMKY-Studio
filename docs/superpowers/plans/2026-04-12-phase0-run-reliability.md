# Phase 0 Run Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 1-model, one-event test reliable by excluding non-event taxonomy artifacts from run selection, enforcing B/C injection coverage preflight, and converting OpenRouter 429 handling into no-cap wait-and-retry behavior.

**Architecture:** Tighten event parsing in `run_ecnbench_protocol.py` so only true event records become runnable units, add an explicit injection-coverage preflight gate before orchestration, and extend `LLMClient` retry logic to treat 429 throttling as waitable until provider reset. Keep all changes additive and preserve existing A/B/C workflow, scoring, and output schema.

**Tech Stack:** Python 3.11, pytest, OpenAI Python SDK (OpenRouter via OpenAI-compatible API), existing benchmark orchestrator + trace writer.

---

## File Structure and Responsibilities

- Modify: `backend/scripts/run_ecnbench_protocol.py`
  - Owns raw event extraction, run preflight, and benchmark execution wiring.
- Modify: `backend/app/benchmarks/injection_loader.py`
  - Owns injection bank lookup and event-id coverage introspection.
- Modify: `backend/app/utils/llm_client.py`
  - Owns retry logic for OpenRouter/LLM requests.
- Modify: `backend/tests/test_run_ecnbench_protocol.py`
  - Verifies parser behavior and benchmark preflight behavior.
- Modify: `backend/tests/test_llm_client_openrouter.py`
  - Verifies retry/backoff behavior for transient and rate-limit failures.

---

### Task 1: Prevent taxonomy artifacts from becoming benchmark events

**Files:**
- Modify: `backend/tests/test_run_ecnbench_protocol.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`

- [ ] **Step 1: Write the failing parser test**

```python
def test_load_events_ignores_taxonomy_key_value_maps(tmp_path):
    payload = {
        "study": {
            "taxonomy_axes": {
                "axis_2_resolution_horizon": {"short": "2-4 weeks", "medium": "1-3 months"}
            }
        },
        "core_events": [{"id": "S2", "question": "Q", "outcome": "YES"}],
    }
    path = tmp_path / "events.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    events = protocol_script.load_events_from_raw(path)

    assert [event["event_id"] for event in events] == ["S2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_run_ecnbench_protocol.py::test_load_events_ignores_taxonomy_key_value_maps -v`
Expected: FAIL because `short`/`medium` are currently included as parsed events.

- [ ] **Step 3: Implement parser guard in `_collect_events`**

```python
def _looks_like_scalar_event_map(payload: Mapping[str, Any]) -> bool:
    if not payload:
        return False
    if any(isinstance(value, (dict, list, tuple)) for value in payload.values()):
        return False
    allowed_keys = {"event_id", "id", "question", "prompt", "text", "title", "outcome", "answer", "label", "ground_truth", "target", "correct_answer", "options", "choices", "answers"}
    return set(str(key) for key in payload.keys()).issubset(allowed_keys)

# in _collect_events, replace the old scalar-map branch with:
if _looks_like_scalar_event_map(payload) and _looks_like_event(payload):
    _fallback_index[0] += 1
    events.append(_normalize_event_record(payload, _fallback_index[0]))
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_run_ecnbench_protocol.py::test_load_events_ignores_taxonomy_key_value_maps -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "test: exclude taxonomy maps from event parsing"
```

---

### Task 2: Add explicit B/C injection coverage preflight

**Files:**
- Modify: `backend/tests/test_run_ecnbench_protocol.py`
- Modify: `backend/app/benchmarks/injection_loader.py`
- Modify: `backend/scripts/run_ecnbench_protocol.py`

- [ ] **Step 1: Write failing preflight test**

```python
def test_validate_injection_coverage_raises_for_missing_event(tmp_path):
    class DummyInjectionLoader:
        def has_event(self, event_id):
            return event_id != "E2"

    events = [{"event_id": "E1"}, {"event_id": "E2"}]

    with pytest.raises(ValueError, match=r"Missing step-30 injection payloads for event_ids: E2"):
        protocol_script.validate_injection_coverage(events, DummyInjectionLoader())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_run_ecnbench_protocol.py::test_validate_injection_coverage_raises_for_missing_event -v`
Expected: FAIL because preflight helper does not exist yet.

- [ ] **Step 3: Implement minimal preflight support**

```python
# backend/app/benchmarks/injection_loader.py
def has_event(self, event_id: str) -> bool:
    return str(event_id) in self._events

# backend/scripts/run_ecnbench_protocol.py
def validate_injection_coverage(events: List[Mapping[str, Any]], injection_loader: Step30InjectionLoader) -> None:
    missing = [str(event["event_id"]) for event in events if not injection_loader.has_event(str(event["event_id"]))]
    if missing:
        ordered = sorted(set(missing))
        raise ValueError(f"Missing step-30 injection payloads for event_ids: {', '.join(ordered)}")

# in main(), after injection_loader init:
validate_injection_coverage(events, injection_loader)
```

- [ ] **Step 4: Run targeted tests**

Run: `pytest backend/tests/test_run_ecnbench_protocol.py -k "injection_coverage or load_events_ignores_taxonomy" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/injection_loader.py backend/scripts/run_ecnbench_protocol.py backend/tests/test_run_ecnbench_protocol.py
git commit -m "feat: enforce injection coverage preflight for benchmark events"
```

---

### Task 3: Make 429 handling wait-until-success with reset-aware sleep

**Files:**
- Modify: `backend/tests/test_llm_client_openrouter.py`
- Modify: `backend/app/utils/llm_client.py`

- [ ] **Step 1: Write failing rate-limit tests**

```python
def test_rate_limit_retries_even_when_max_retries_zero(monkeypatch):
    store = {"calls": 0, "sleep_calls": []}

    class FakeRateLimitError(Exception):
        def __init__(self):
            self.body = {"error": {"metadata": {"headers": {"X-RateLimit-Reset": "4102444800000"}}}}

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            if store["calls"] == 1:
                raise FakeRateLimitError()
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(llm_client_module.time, "sleep", store["sleep_calls"].append)
    monkeypatch.setattr(llm_client_module.time, "time", lambda: 0.0)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_HTTP_REFERER", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_X_TITLE", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", 0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_INITIAL_DELAY", 0.1, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_DELAY", 1.0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_JITTER_MAX", 0.0, raising=False)

    client = llm_client_module.LLMClient()
    response = client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.4)

    assert response == "ok"
    assert store["calls"] == 2
    assert store["sleep_calls"] == [4102444800.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_llm_client_openrouter.py -k "rate_limit_retries_even_when_max_retries_zero" -v`
Expected: FAIL because current retry loop stops at max retries.

- [ ] **Step 3: Implement reset-aware, no-cap 429 retry**

```python
def _extract_rate_limit_reset_wait_seconds(self, error: Exception) -> Optional[float]:
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return None
    detail = body.get("error", body)
    if not isinstance(detail, dict):
        return None
    metadata = detail.get("metadata")
    if not isinstance(metadata, dict):
        return None
    headers = metadata.get("headers")
    if not isinstance(headers, dict):
        return None
    raw_reset = headers.get("X-RateLimit-Reset")
    try:
        reset_epoch_ms = int(raw_reset)
    except (TypeError, ValueError):
        return None
    return max(0.0, (reset_epoch_ms / 1000.0) - time.time())

def _chat_create_with_retry(self, kwargs: Dict[str, Any]):
    delay = max(0.0, self._retry_initial_delay)
    attempt = 0
    while True:
        try:
            return self.client.chat.completions.create(**kwargs)
        except Exception as error:
            if isinstance(error, RateLimitError):
                wait_seconds = self._extract_rate_limit_reset_wait_seconds(error)
                if wait_seconds is None:
                    wait_seconds = min(delay, self._retry_max_delay) + (random.uniform(0, self._retry_jitter_max) if self._retry_jitter_max > 0 else 0.0)
                    delay = min(delay * 2 if delay > 0 else 0.0, self._retry_max_delay)
                time.sleep(wait_seconds)
                continue

            should_retry = self._is_retryable_error(error)
            if attempt >= self._retry_max_retries or not should_retry:
                raise
            sleep_delay = min(delay, self._retry_max_delay) + (random.uniform(0, self._retry_jitter_max) if self._retry_jitter_max > 0 else 0.0)
            time.sleep(sleep_delay)
            delay = min(delay * 2 if delay > 0 else 0.0, self._retry_max_delay)
            attempt += 1
```

- [ ] **Step 4: Run targeted retry tests**

Run: `pytest backend/tests/test_llm_client_openrouter.py -k "rate_limit or retry_backoff" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/llm_client.py backend/tests/test_llm_client_openrouter.py
git commit -m "feat: add no-cap reset-aware retry for 429 rate limits"
```

---

### Task 4: End-to-end verification for benchmark reliability path

**Files:**
- Modify: none (validation task)
- Test: `backend/tests/test_run_ecnbench_protocol.py`, `backend/tests/test_llm_client_openrouter.py`

- [ ] **Step 1: Run combined targeted tests**

Run: `pytest backend/tests/test_run_ecnbench_protocol.py backend/tests/test_llm_client_openrouter.py -v`
Expected: PASS.

- [ ] **Step 2: Run benchmark smoke with 1 event**

Run:
```bash
cd backend
python scripts/run_ecnbench_protocol.py --seeds-dir ..\..\data\seeds --events-raw ..\..\data\events_raw.json --injection-bank ..\..\data\injections\step30_injection_bank.json --output-dir logs\benchmark_runs --events 1 --repeats 1
```
Expected:
- run manifest includes real event ID (no `short`/`medium`),
- no `Missing injection event_id` error,
- if throttled, process waits/retries instead of immediate terminal failure.

- [ ] **Step 3: Commit final reliability fixes**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/app/benchmarks/injection_loader.py backend/app/utils/llm_client.py backend/tests/test_run_ecnbench_protocol.py backend/tests/test_llm_client_openrouter.py
git commit -m "fix: harden phase0 event integrity and 429 retry reliability"
```
Expected: commit created with only reliability-fix files.

