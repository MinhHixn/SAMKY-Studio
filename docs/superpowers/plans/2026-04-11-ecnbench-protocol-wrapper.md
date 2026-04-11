# ECN-BENCH Protocol Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an end-to-end ECN-BENCH prototype command that runs 30 events across A/B/C conditions with strict 3000-agent / 60-step / step-30 injection enforcement, role-based OpenRouter routing, evaluator probabilities, and Brier scoring outputs.

**Architecture:** Add a benchmark-focused protocol wrapper around existing simulation scripts and graph stack, rather than replacing core app flows. New benchmark modules will handle condition assembly, injection loading, evaluator/scoring, and artifact writing, while existing OASIS runners continue executing simulation dynamics. Strict model-role routing is centralized so graph extraction, benchmark simulation, and evaluator scoring cannot silently share models.

**Tech Stack:** Python 3.11, Flask config layer, OpenAI SDK (OpenRouter-compatible), Neo4j storage, OASIS simulation scripts, pytest.

---

## File Structure (planned changes)

- Create: `backend/app/benchmarks/__init__.py`  
  Benchmark package entrypoint and shared exports.
- Create: `backend/app/benchmarks/role_router.py`  
  Strict role→model resolution + `LLMClient` factory (graph/benchmark/evaluator).
- Create: `backend/app/benchmarks/injection_loader.py`  
  Loads and validates `step30_injection_bank.json`.
- Create: `backend/app/benchmarks/protocol.py`  
  Condition enum, hard-constraint enforcement, step-30 event construction, profile expansion to exactly 3000.
- Create: `backend/app/benchmarks/evaluator.py`  
  Evaluator-model probability extraction + normalization.
- Create: `backend/app/benchmarks/scoring.py`  
  Brier and aggregate/lift calculations.
- Create: `backend/scripts/run_ecnbench_protocol.py`  
  Single end-to-end benchmark command.
- Modify: `backend/app/config.py`  
  Role-based model envs + retry jitter config.
- Modify: `backend/app/utils/llm_client.py`  
  Add retry jitter support for 429/5xx backoff.
- Modify: `backend/scripts/run_parallel_simulation.py`  
  Consume `event_config.scheduled_events` and apply step-30 injected posts.
- Modify: `.env.example`  
  Document role-based model env keys and retry jitter key.
- Modify: `README.md`  
  Document protocol command, required envs, and output artifacts.
- Test: `backend/tests/test_llm_client_openrouter.py`  
  Retry jitter + transient retry behavior.
- Test: `backend/tests/test_benchmark_role_router.py`  
  Role config validation and client construction.
- Test: `backend/tests/test_benchmark_protocol.py`  
  3000/60/step30 enforcement + profile expansion + injection validation.
- Test: `backend/tests/test_benchmark_evaluator_scoring.py`  
  Probability normalization and Brier/lift correctness.
- Test: `backend/tests/test_run_parallel_scheduled_events.py`  
  Step-30 scheduled event application helper behavior.
- Test: `backend/tests/test_run_ecnbench_protocol.py`  
  End-to-end orchestration helpers and artifact writing.

### Task 1: Role-based model routing foundation

**Files:**
- Create: `backend/app/benchmarks/__init__.py`
- Create: `backend/app/benchmarks/role_router.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_benchmark_role_router.py`

- [ ] **Step 1: Write failing router tests**

```python
# backend/tests/test_benchmark_role_router.py
import pytest

from app.benchmarks.role_router import BenchmarkRoleRouter


def test_router_requires_all_role_models():
    with pytest.raises(ValueError, match="OPENROUTER_GRAPH_MODEL"):
        BenchmarkRoleRouter(
            api_key="k",
            base_url="https://openrouter.ai/api/v1",
            graph_model="",
            benchmark_model="minimax/minimax-m2.5:free",
            evaluator_model="google/gemma-4-31b-it:free",
        )


def test_router_returns_exact_model_for_each_role():
    router = BenchmarkRoleRouter(
        api_key="k",
        base_url="https://openrouter.ai/api/v1",
        graph_model="nvidia/nemotron-3-super-120b-a12b:free",
        benchmark_model="minimax/minimax-m2.5:free",
        evaluator_model="google/gemma-4-31b-it:free",
    )
    assert router.model_for("graph") == "nvidia/nemotron-3-super-120b-a12b:free"
    assert router.model_for("benchmark") == "minimax/minimax-m2.5:free"
    assert router.model_for("evaluator") == "google/gemma-4-31b-it:free"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_role_router.py -q`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.benchmarks.role_router'`

- [ ] **Step 3: Implement config + router**

```python
# backend/app/config.py (additions)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY") or LLM_API_KEY
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_GRAPH_MODEL = os.environ.get("OPENROUTER_GRAPH_MODEL", "")
OPENROUTER_BENCHMARK_MODEL = os.environ.get("OPENROUTER_BENCHMARK_MODEL", "")
OPENROUTER_EVALUATOR_MODEL = os.environ.get("OPENROUTER_EVALUATOR_MODEL", "")
LLM_RETRY_JITTER_MAX = _env_float_or_raw("LLM_RETRY_JITTER_MAX", 0.25)
```

```python
# backend/app/benchmarks/role_router.py
from dataclasses import dataclass
from typing import Literal

from ..utils.llm_client import LLMClient

Role = Literal["graph", "benchmark", "evaluator"]


@dataclass(frozen=True)
class BenchmarkRoleRouter:
    api_key: str
    base_url: str
    graph_model: str
    benchmark_model: str
    evaluator_model: str

    def __post_init__(self) -> None:
        missing = []
        if not self.api_key:
            missing.append("OPENROUTER_API_KEY")
        if not self.base_url:
            missing.append("OPENROUTER_BASE_URL")
        if not self.graph_model:
            missing.append("OPENROUTER_GRAPH_MODEL")
        if not self.benchmark_model:
            missing.append("OPENROUTER_BENCHMARK_MODEL")
        if not self.evaluator_model:
            missing.append("OPENROUTER_EVALUATOR_MODEL")
        if missing:
            raise ValueError(f"Missing required benchmark routing config: {', '.join(missing)}")

    def model_for(self, role: Role) -> str:
        return {
            "graph": self.graph_model,
            "benchmark": self.benchmark_model,
            "evaluator": self.evaluator_model,
        }[role]

    def client_for(self, role: Role) -> LLMClient:
        return LLMClient(api_key=self.api_key, base_url=self.base_url, model=self.model_for(role))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_role_router.py -q`  
Expected: PASS (all tests green)

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/benchmarks/__init__.py backend/app/benchmarks/role_router.py backend/tests/test_benchmark_role_router.py .env.example
git commit -m "feat: add strict benchmark model role router" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: 429 exponential backoff with jitter

**Files:**
- Modify: `backend/app/utils/llm_client.py`
- Modify: `backend/tests/test_llm_client_openrouter.py`

- [ ] **Step 1: Add failing retry jitter tests**

```python
def test_rate_limit_retry_uses_exponential_backoff_with_jitter(monkeypatch):
    store = {"calls": 0, "sleep_calls": []}

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            if store["calls"] < 3:
                raise TimeoutError("transient")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module.time, "sleep", store["sleep_calls"].append)
    monkeypatch.setattr(llm_client_module.random, "uniform", lambda a, b: 0.25)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "k")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "m")
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", 3)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_INITIAL_DELAY", 1.0)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_DELAY", 8.0)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_JITTER_MAX", 0.5, raising=False)

    client = llm_client_module.LLMClient()
    assert client.chat([{"role": "user", "content": "x"}]) == "ok"
    assert store["sleep_calls"] == [1.25, 2.25]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_llm_client_openrouter.py::test_rate_limit_retry_uses_exponential_backoff_with_jitter -q`  
Expected: FAIL because jitter config/logic is not yet implemented.

- [ ] **Step 3: Implement jitter in `LLMClient`**

```python
# backend/app/utils/llm_client.py
import random

self._retry_jitter_max = self._coerce_non_negative_float(
    Config.LLM_RETRY_JITTER_MAX,
    "LLM_RETRY_JITTER_MAX",
)

def _next_retry_sleep(self, delay: float) -> float:
    base = min(delay, self._retry_max_delay)
    jitter = random.uniform(0.0, self._retry_jitter_max) if self._retry_jitter_max > 0 else 0.0
    return base + jitter

# in _chat_create_with_retry
if delay > 0:
    time.sleep(self._next_retry_sleep(delay))
delay = min(delay * 2 if delay > 0 else self._retry_initial_delay, self._retry_max_delay)
```

- [ ] **Step 4: Run llm-client tests**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_llm_client_openrouter.py -q`  
Expected: PASS with new jitter test and existing retry tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/llm_client.py backend/tests/test_llm_client_openrouter.py
git commit -m "feat: add jittered exponential backoff for transient LLM retries" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Protocol primitives (A/B/C, 3000/60 enforcement, injection loading)

**Files:**
- Create: `backend/app/benchmarks/injection_loader.py`
- Create: `backend/app/benchmarks/protocol.py`
- Test: `backend/tests/test_benchmark_protocol.py`

- [ ] **Step 1: Write failing protocol tests**

```python
# backend/tests/test_benchmark_protocol.py
import pytest

from app.benchmarks.protocol import enforce_protocol_constraints, expand_profiles_to_target
from app.benchmarks.injection_loader import Step30InjectionLoader


def test_enforce_protocol_requires_exact_60_rounds():
    config = {"time_config": {"total_simulation_hours": 72, "minutes_per_round": 60}, "agent_configs": [{}] * 3000}
    with pytest.raises(ValueError, match="exactly 60"):
        enforce_protocol_constraints(config)


def test_expand_profiles_reaches_exact_target_size():
    base = [{"user_id": 0, "username": "agent_0", "name": "Agent 0", "persona": "x", "bio": "x"}]
    expanded = expand_profiles_to_target(base, target_count=3000)
    assert len(expanded) == 3000
    assert expanded[2999]["user_id"] == 2999


def test_injection_loader_requires_event_payload(tmp_path):
    path = tmp_path / "bank.json"
    path.write_text('{"events":[{"event_id":"C1","relevant_update":{"body":"x"},"null_update":{"body":"y"}}]}', encoding="utf-8")
    loader = Step30InjectionLoader(path)
    with pytest.raises(KeyError, match="C2"):
        loader.get_payload("C2", "B")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_protocol.py -q`  
Expected: FAIL with import errors for missing benchmark protocol modules.

- [ ] **Step 3: Implement protocol + loader**

```python
# backend/app/benchmarks/injection_loader.py
import json
from pathlib import Path
from typing import Any, Dict, Literal


Condition = Literal["A", "B", "C"]


class Step30InjectionLoader:
    def __init__(self, path: Path | str):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        events = payload.get("events", [])
        self._events = {str(event["event_id"]): event for event in events}

    def get_payload(self, event_id: str, condition: Condition) -> Dict[str, Any] | None:
        if condition == "A":
            return None
        event = self._events.get(event_id)
        if not event:
            raise KeyError(f"Missing injection event_id: {event_id}")
        key = "relevant_update" if condition == "B" else "null_update"
        if key not in event:
            raise KeyError(f"Missing '{key}' payload for event_id: {event_id}")
        return event[key]
```

```python
# backend/app/benchmarks/protocol.py
from copy import deepcopy
from typing import Any, Dict, List, Literal

Condition = Literal["A", "B", "C"]


def enforce_protocol_constraints(config: Dict[str, Any]) -> None:
    agents = config.get("agent_configs", [])
    if len(agents) != 3000:
        raise ValueError(f"Protocol requires exactly 3000 agents, got {len(agents)}")
    time_cfg = config.get("time_config", {})
    rounds = (int(time_cfg.get("total_simulation_hours", 0)) * 60) // int(time_cfg.get("minutes_per_round", 1))
    if rounds != 60:
        raise ValueError(f"Protocol requires exactly 60 rounds, got {rounds}")


def expand_profiles_to_target(base_profiles: List[Dict[str, Any]], target_count: int = 3000) -> List[Dict[str, Any]]:
    if not base_profiles:
        raise ValueError("Cannot expand profiles from an empty base list")
    expanded: List[Dict[str, Any]] = []
    for idx in range(target_count):
        source = deepcopy(base_profiles[idx % len(base_profiles)])
        source["user_id"] = idx
        source["username"] = f"{source.get('username', 'agent')}_{idx}"
        expanded.append(source)
    return expanded


def build_step30_scheduled_event(payload: Dict[str, Any], poster_agent_id: int = 0) -> Dict[str, Any]:
    content = payload.get("body") or payload.get("headline") or ""
    if not content:
        raise ValueError("Injection payload must include body/headline text")
    return {
        "trigger_round": 30,
        "posts": [{"poster_agent_id": poster_agent_id, "content": content}],
    }
```

- [ ] **Step 4: Run protocol tests**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_protocol.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/injection_loader.py backend/app/benchmarks/protocol.py backend/tests/test_benchmark_protocol.py
git commit -m "feat: add benchmark protocol constraints and injection loader" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Step-30 scheduled injection execution in simulation runtime

**Files:**
- Modify: `backend/scripts/run_parallel_simulation.py`
- Test: `backend/tests/test_run_parallel_scheduled_events.py`

- [ ] **Step 1: Add failing scheduled-event test**

```python
# backend/tests/test_run_parallel_scheduled_events.py
from scripts.run_parallel_simulation import collect_scheduled_posts_for_round


def test_collect_scheduled_posts_for_round_matches_round_30_only():
    event_cfg = {
        "scheduled_events": [
            {"trigger_round": 30, "posts": [{"poster_agent_id": 7, "content": "Injected update"}]}
        ]
    }
    assert collect_scheduled_posts_for_round(event_cfg, 29) == []
    posts = collect_scheduled_posts_for_round(event_cfg, 30)
    assert len(posts) == 1
    assert posts[0]["content"] == "Injected update"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_run_parallel_scheduled_events.py -q`  
Expected: FAIL (helper does not exist yet).

- [ ] **Step 3: Implement helper + runtime hook**

```python
# backend/scripts/run_parallel_simulation.py
def collect_scheduled_posts_for_round(event_config: Dict[str, Any], round_num: int) -> List[Dict[str, Any]]:
    posts: List[Dict[str, Any]] = []
    for event in event_config.get("scheduled_events", []):
        if int(event.get("trigger_round", -1)) == round_num:
            posts.extend(event.get("posts", []))
    return posts

# inside simulation loop (both twitter/reddit paths), before LLMAction batch:
scheduled_posts = collect_scheduled_posts_for_round(event_config, round_num + 1)
if scheduled_posts:
    scheduled_actions = {}
    for post in scheduled_posts:
        agent = result.env.agent_graph.get_agent(post.get("poster_agent_id", 0))
        scheduled_actions[agent] = ManualAction(
            action_type=ActionType.CREATE_POST,
            action_args={"content": post.get("content", "")},
        )
    if scheduled_actions:
        await result.env.step(scheduled_actions)
```

- [ ] **Step 4: Run new + existing benchmark runner tests**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_run_parallel_scheduled_events.py tests\test_run_ecnbench_openrouter.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_parallel_simulation.py backend/tests/test_run_parallel_scheduled_events.py
git commit -m "feat: execute step-based scheduled injection events in parallel simulation" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Evaluator workflow + Brier/lift scoring

**Files:**
- Create: `backend/app/benchmarks/evaluator.py`
- Create: `backend/app/benchmarks/scoring.py`
- Test: `backend/tests/test_benchmark_evaluator_scoring.py`

- [ ] **Step 1: Add failing evaluator/scoring tests**

```python
# backend/tests/test_benchmark_evaluator_scoring.py
import pytest

from app.benchmarks.scoring import brier_score, summarize_condition_scores


def test_brier_score_is_zero_for_correct_certainty():
    assert brier_score({"YES": 1.0, "NO": 0.0}, "YES") == 0.0


def test_brier_score_handles_multiclass_distribution():
    score = brier_score({"A": 0.5, "B": 0.3, "C": 0.2}, "B")
    assert round(score, 4) == 0.3900


def test_summary_reports_lift_deltas():
    rows = [
        {"condition": "A", "brier": 0.40},
        {"condition": "B", "brier": 0.32},
        {"condition": "C", "brier": 0.45},
    ]
    summary = summarize_condition_scores(rows)
    assert summary["lift"]["A_to_B"] == 0.08
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_evaluator_scoring.py -q`  
Expected: FAIL with missing module errors.

- [ ] **Step 3: Implement evaluator + scoring**

```python
# backend/app/benchmarks/evaluator.py
from typing import Any, Dict

from .role_router import BenchmarkRoleRouter


class ProbabilityEvaluator:
    def __init__(self, router: BenchmarkRoleRouter):
        self._llm = router.client_for("evaluator")

    def evaluate(self, event_question: str, condition: str, evidence_text: str) -> Dict[str, Any]:
        prompt = (
            "Return ONLY JSON: "
            '{"probabilities":{"<outcome>":0.0},"top_outcome":"<outcome>"}\n'
            f"Question: {event_question}\nCondition: {condition}\nEvidence:\n{evidence_text}"
        )
        result = self._llm.chat_json([{"role": "user", "content": prompt}], temperature=0.0)
        probs = result.get("probabilities", {})
        total = sum(float(v) for v in probs.values())
        if total <= 0:
            raise ValueError("Evaluator returned zero/invalid probability mass")
        result["probabilities"] = {k: float(v) / total for k, v in probs.items()}
        return result
```

```python
# backend/app/benchmarks/scoring.py
from collections import defaultdict
from typing import Dict, List


def brier_score(probabilities: Dict[str, float], truth: str) -> float:
    labels = set(probabilities.keys()) | {truth}
    return sum((probabilities.get(label, 0.0) - (1.0 if label == truth else 0.0)) ** 2 for label in labels)


def summarize_condition_scores(rows: List[Dict]) -> Dict:
    bucket = defaultdict(list)
    for row in rows:
        bucket[row["condition"]].append(float(row["brier"]))
    means = {cond: sum(vals) / len(vals) for cond, vals in bucket.items() if vals}
    return {
        "condition_mean_brier": means,
        "lift": {
            "A_to_B": round(means.get("A", 0.0) - means.get("B", 0.0), 6),
            "A_to_C": round(means.get("A", 0.0) - means.get("C", 0.0), 6),
            "B_to_C": round(means.get("B", 0.0) - means.get("C", 0.0), 6),
        },
    }
```

- [ ] **Step 4: Run evaluator/scoring tests**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_evaluator_scoring.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmarks/evaluator.py backend/app/benchmarks/scoring.py backend/tests/test_benchmark_evaluator_scoring.py
git commit -m "feat: add evaluator probability normalization and brier scoring" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: End-to-end benchmark command and artifacts

**Files:**
- Create: `backend/scripts/run_ecnbench_protocol.py`
- Test: `backend/tests/test_run_ecnbench_protocol.py`
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Add failing orchestrator tests**

```python
# backend/tests/test_run_ecnbench_protocol.py
from scripts.run_ecnbench_protocol import build_condition_matrix, build_event_result_row


def test_condition_matrix_defaults_to_one_repeat():
    matrix = build_condition_matrix(["C1"], repeats=1)
    assert len(matrix) == 3
    assert {row["condition"] for row in matrix} == {"A", "B", "C"}


def test_event_result_row_marks_full_simulation_completion():
    row = build_event_result_row(
        event_id="C1",
        condition="B",
        simulation_status="completed",
        probabilities={"YES": 0.7, "NO": 0.3},
        brier=0.18,
        error=None,
    )
    assert row["full_simulation_completed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .\.venv311\Scripts\python -m pytest tests\test_run_ecnbench_protocol.py -q`  
Expected: FAIL with missing script/module.

- [ ] **Step 3: Implement orchestration script**

```python
# backend/scripts/run_ecnbench_protocol.py (core flow)
import argparse
import json
import subprocess
from pathlib import Path

from app.config import Config
from app.utils.benchmark_trace import BenchmarkTraceWriter
from app.benchmarks.role_router import BenchmarkRoleRouter
from app.benchmarks.injection_loader import Step30InjectionLoader
from app.benchmarks.protocol import build_step30_scheduled_event, enforce_protocol_constraints
from app.benchmarks.evaluator import ProbabilityEvaluator
from app.benchmarks.scoring import brier_score, summarize_condition_scores


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events-raw", required=True)
    parser.add_argument("--injection-bank", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--trace-out", required=True)
    parser.add_argument("--events", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=1)
    return parser.parse_args()


def load_events(events_raw_path: str, limit: int) -> list[dict]:
    data = json.loads(Path(events_raw_path).read_text(encoding="utf-8"))
    events = data if isinstance(data, list) else data.get("events", [])
    return events[:limit]


def build_condition_matrix(event_ids: list[str], repeats: int) -> list[dict]:
    matrix = []
    for event_id in event_ids:
        for repeat in range(1, repeats + 1):
            for condition in ("A", "B", "C"):
                matrix.append({"event_id": event_id, "repeat": repeat, "condition": condition})
    return matrix


def build_event_result_row(event_id, condition, simulation_status, probabilities, brier, error):
    return {
        "event_id": event_id,
        "condition": condition,
        "full_simulation_completed": simulation_status == "completed",
        "simulation_status": simulation_status,
        "probabilities": probabilities,
        "brier": brier,
        "error": error,
    }


def build_base_simulation_config(event: dict, model_name: str) -> dict:
    return {
        "llm_model": model_name,
        "time_config": {"total_simulation_hours": 60, "minutes_per_round": 60},
        "agent_configs": [{"agent_id": i, "entity_name": f"agent_{i}"} for i in range(3000)],
        "event_config": {
            "initial_posts": [{"poster_agent_id": 0, "content": event.get("question", "")}],
            "scheduled_events": [],
        },
    }


def build_condition_config(base_config: dict, loader, event_id: str, condition: str) -> dict:
    config = json.loads(json.dumps(base_config))
    if condition in {"B", "C"}:
        payload = loader.get_payload(event_id, condition)
        config["event_config"]["scheduled_events"] = [build_step30_scheduled_event(payload, poster_agent_id=0)]
    return config


def run_full_simulation(config: dict, run_dir: str):
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    config_path = run_path / "simulation_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    process = subprocess.run(
        ["python", "scripts/run_parallel_simulation.py", "--config", str(config_path), "--max-rounds", "60", "--no-wait"],
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        return "failed", {"error": process.stderr or process.stdout}
    evidence_text = (run_path / "simulation.log").read_text(encoding="utf-8") if (run_path / "simulation.log").exists() else ""
    return "completed", {"evidence_text": evidence_text}


def execute_run_unit(router, loader, event, condition, repeat, run_dir):
    base_config = build_base_simulation_config(event=event, model_name=router.model_for("benchmark"))
    condition_config = build_condition_config(base_config, loader, event["event_id"], condition)
    enforce_protocol_constraints(condition_config)
    simulation_status, artifacts = run_full_simulation(condition_config, run_dir)
    if simulation_status != "completed":
        return build_event_result_row(event["event_id"], condition, simulation_status, None, None, artifacts["error"])
    eval_result = ProbabilityEvaluator(router).evaluate(event["question"], condition, artifacts["evidence_text"])
    brier = brier_score(eval_result["probabilities"], event["answer"])
    return build_event_result_row(event["event_id"], condition, simulation_status, eval_result["probabilities"], brier, None)


def write_event_results(rows: list[dict], output_dir: str):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "event_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def write_summary(rows: list[dict], scoring_summary: dict, output_dir: str):
    failed = [row for row in rows if row["simulation_status"] != "completed"]
    payload = {
        "completed_units": len(rows) - len(failed),
        "failed_units": len(failed),
        "failed_items": failed,
        **scoring_summary,
    }
    (Path(output_dir) / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    args = parse_args()
    events = load_events(args.events_raw, limit=args.events)
    router = BenchmarkRoleRouter(
        api_key=Config.OPENROUTER_API_KEY,
        base_url=Config.OPENROUTER_BASE_URL,
        graph_model=Config.OPENROUTER_GRAPH_MODEL,
        benchmark_model=Config.OPENROUTER_BENCHMARK_MODEL,
        evaluator_model=Config.OPENROUTER_EVALUATOR_MODEL,
    )
    loader = Step30InjectionLoader(args.injection_bank)
    trace = BenchmarkTraceWriter(args.trace_out)
    rows = []
    for unit in build_condition_matrix([event["event_id"] for event in events], repeats=args.repeats):
        event = next(item for item in events if item["event_id"] == unit["event_id"])
        row = execute_run_unit(router, loader, event, unit["condition"], unit["repeat"], args.output_dir)
        trace.write({"event_id": unit["event_id"], "condition": unit["condition"], "repeat": unit["repeat"], "status": row["simulation_status"]})
        rows.append(row)
    write_event_results(rows, args.output_dir)
    write_summary(rows, summarize_condition_scores([r for r in rows if r["brier"] is not None]), args.output_dir)
```

- [ ] **Step 4: Update docs/config examples**

```bash
# .env.example additions
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_GRAPH_MODEL=nvidia/nemotron-3-super-120b-a12b:free
OPENROUTER_BENCHMARK_MODEL=minimax/minimax-m2.5:free
OPENROUTER_EVALUATOR_MODEL=google/gemma-4-31b-it:free
LLM_RETRY_JITTER_MAX=0.25
```

```markdown
<!-- README.md additions -->
python backend/scripts/run_ecnbench_protocol.py --events 30 --repeats 1
```

- [ ] **Step 5: Run full targeted benchmark test pack**

Run:  
`cd backend && .\.venv311\Scripts\python -m pytest tests\test_benchmark_role_router.py tests\test_benchmark_protocol.py tests\test_benchmark_evaluator_scoring.py tests\test_run_parallel_scheduled_events.py tests\test_run_ecnbench_protocol.py tests\test_llm_client_openrouter.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/run_ecnbench_protocol.py backend/tests/test_run_ecnbench_protocol.py README.md .env.example
git commit -m "feat: add end-to-end ecnbench protocol runner with clear per-event outputs" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Plan Self-Review

1. **Spec coverage:**  
   - A/B/C orchestration: Task 3 + Task 6  
   - 3000 agents and 60 steps hard enforcement: Task 3  
   - step-30 injection (B/C only): Task 3 + Task 4  
   - strict model-role split: Task 1  
   - evaluator workflow (Gemma) and Brier scoring: Task 5  
   - single command + per-event clear outputs: Task 6  
   - 429 exponential backoff with jitter: Task 2
2. **Placeholder scan:** No `TODO`/`TBD` placeholders remain.
3. **Type/signature consistency:** Role names are consistently `graph | benchmark | evaluator`; conditions consistently `A | B | C`; scoring helpers consume normalized probability dictionaries.
