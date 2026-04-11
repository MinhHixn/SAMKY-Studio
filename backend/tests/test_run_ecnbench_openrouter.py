from scripts.run_ecnbench_openrouter import (
    PENDING_OUTPUT,
    load_answers,
    partition_events,
    summarize_variance,
)
from scripts import (
    run_parallel_simulation as parallel_script,
    run_reddit_simulation as reddit_script,
    run_twitter_simulation as twitter_script,
)

import pytest


def test_partition_events_30_into_three_batches():
    events = [f"E{i}" for i in range(30)]
    batches = partition_events(events, 10)
    assert [len(batch) for batch in batches] == [10, 10, 10]


def test_load_answers_reads_events_raw(tmp_path):
    events_raw = tmp_path / "events_raw.json"
    events_raw.write_text(
        '[{"event_id":"E1","answer":"YES"},{"event_id":"E2","answer":"NO"}]',
        encoding="utf-8",
    )

    answers = load_answers(events_raw)

    assert answers["E1"] == "YES"
    assert answers["E2"] == "NO"


def test_summarize_variance_flags_divergent_events():
    event_runs = {
        "E1": ["YES", "YES", "YES"],
        "E2": ["YES", "NO", "YES"],
    }

    summary = summarize_variance(event_runs)

    assert summary["E1"]["disagreement_ratio"] == 0.0
    assert summary["E1"]["is_high_variance"] is False
    assert summary["E2"]["disagreement_ratio"] > 0.0
    assert summary["E2"]["is_high_variance"] is True


def test_summarize_variance_marks_pending_outputs_as_pending_state():
    summary = summarize_variance({"E1": [PENDING_OUTPUT, PENDING_OUTPUT]})

    assert summary["E1"]["runs"] == 2
    assert summary["E1"]["pending_runs"] == 2
    assert summary["E1"]["completed_runs"] == 0
    assert summary["E1"]["variance_state"] == "pending"
    assert summary["E1"]["baseline_output"] is None
    assert summary["E1"]["disagreement_ratio"] is None
    assert summary["E1"]["is_high_variance"] is None


@pytest.mark.parametrize("module", [reddit_script, twitter_script, parallel_script])
@pytest.mark.parametrize("benchmark_mode", [None, "false"])
def test_apply_benchmark_env_does_not_force_benchmark_mode(monkeypatch, module, benchmark_mode):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("BENCHMARK_TEMPERATURE", raising=False)
    monkeypatch.delenv("BENCHMARK_SEED", raising=False)
    if benchmark_mode is None:
        monkeypatch.delenv("BENCHMARK_MODE", raising=False)
    else:
        monkeypatch.setenv("BENCHMARK_MODE", benchmark_mode)

    seed_calls = []
    monkeypatch.setattr(module.random, "seed", seed_calls.append)

    module._apply_benchmark_env(config={"llm_model": "openrouter/test-model"})

    assert "BENCHMARK_TEMPERATURE" not in module.os.environ
    assert "BENCHMARK_SEED" not in module.os.environ
    assert module.os.environ.get("BENCHMARK_MODE") == benchmark_mode
    assert seed_calls == []


@pytest.mark.parametrize("module", [reddit_script, twitter_script, parallel_script])
def test_apply_benchmark_env_sets_deterministic_defaults_when_enabled(monkeypatch, module):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("BENCHMARK_MODE", "true")
    monkeypatch.delenv("BENCHMARK_TEMPERATURE", raising=False)
    monkeypatch.delenv("BENCHMARK_SEED", raising=False)

    seed_calls = []
    monkeypatch.setattr(module.random, "seed", seed_calls.append)

    module._apply_benchmark_env(config={"llm_model": "openrouter/test-model"})

    assert module.os.environ["BENCHMARK_MODE"] == "true"
    assert module.os.environ["BENCHMARK_TEMPERATURE"] == "0"
    assert module.os.environ["BENCHMARK_SEED"] == "42"
    assert seed_calls == [42]


@pytest.mark.parametrize("module", [reddit_script, twitter_script, parallel_script])
def test_apply_benchmark_env_does_not_require_llm_base_url(monkeypatch, module):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("BENCHMARK_MODE", "false")

    module._apply_benchmark_env(config={"llm_model": "openrouter/test-model"})

    assert module.os.environ["OPENAI_API_KEY"] == "test-key"
    assert "OPENAI_API_BASE_URL" not in module.os.environ
