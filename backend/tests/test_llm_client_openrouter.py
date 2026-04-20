import importlib
from types import SimpleNamespace

import pytest

from app.utils import llm_client as llm_client_module


def _install_fake_openai(monkeypatch, store):
    class FakeCompletions:
        def create(self, **kwargs):
            store["create_kwargs"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            store["init_kwargs"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)


def _create_test_client(monkeypatch):
    store = {}
    _install_fake_openai(monkeypatch, store)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_HTTP_REFERER", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_X_TITLE", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", False, raising=False)
    return llm_client_module.LLMClient()


def test_config_reads_openrouter_and_benchmark_flags(monkeypatch):
    import dotenv
    import app.config as config_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.test")
    monkeypatch.setenv("OPENROUTER_X_TITLE", "MiroFish Benchmark")
    monkeypatch.setenv("BENCHMARK_MODE", "true")
    monkeypatch.setenv("BENCHMARK_TEMPERATURE", "0.0")
    monkeypatch.setenv("BENCHMARK_SEED", "2025")
    monkeypatch.setenv("LLM_RETRY_MAX_RETRIES", "4")
    monkeypatch.setenv("LLM_RETRY_INITIAL_DELAY", "0.25")
    monkeypatch.setenv("LLM_RETRY_MAX_DELAY", "2.0")

    config_module = importlib.reload(config_module)
    cfg = config_module.Config

    assert cfg.OPENROUTER_HTTP_REFERER == "https://example.test"
    assert cfg.OPENROUTER_X_TITLE == "MiroFish Benchmark"
    assert cfg.BENCHMARK_MODE is True
    assert cfg.BENCHMARK_TEMPERATURE == 0.0
    assert cfg.BENCHMARK_SEED == 2025
    assert cfg.LLM_RETRY_MAX_RETRIES == 4
    assert cfg.LLM_RETRY_INITIAL_DELAY == 0.25
    assert cfg.LLM_RETRY_MAX_DELAY == 2.0


def test_invalid_retry_env_values_do_not_crash_config_import(monkeypatch):
    import dotenv
    import app.config as config_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("LLM_RETRY_MAX_RETRIES", "invalid-int")
    monkeypatch.setenv("LLM_RETRY_INITIAL_DELAY", "invalid-float-1")
    monkeypatch.setenv("LLM_RETRY_MAX_DELAY", "invalid-float-2")

    config_module = importlib.reload(config_module)

    assert config_module.Config.LLM_RETRY_MAX_RETRIES == "invalid-int"
    assert config_module.Config.LLM_RETRY_INITIAL_DELAY == "invalid-float-1"
    assert config_module.Config.LLM_RETRY_MAX_DELAY == "invalid-float-2"


def test_invalid_benchmark_env_values_do_not_crash_config_import(monkeypatch):
    import dotenv
    import app.config as config_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("BENCHMARK_TEMPERATURE", "invalid-temp")
    monkeypatch.setenv("BENCHMARK_SEED", "invalid-seed")

    config_module = importlib.reload(config_module)

    assert config_module.Config.BENCHMARK_TEMPERATURE == "invalid-temp"
    assert config_module.Config.BENCHMARK_SEED == "invalid-seed"


def test_openrouter_headers_are_attached(monkeypatch):
    store = {}
    _install_fake_openai(monkeypatch, store)

    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(
        llm_client_module.Config,
        "OPENROUTER_HTTP_REFERER",
        "https://example.test",
        raising=False,
    )
    monkeypatch.setattr(
        llm_client_module.Config,
        "OPENROUTER_X_TITLE",
        "MiroFish Offline",
        raising=False,
    )
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", False, raising=False)

    client = llm_client_module.LLMClient()
    client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.4)

    assert store["create_kwargs"]["extra_headers"] == {
        "HTTP-Referer": "https://example.test",
        "X-Title": "MiroFish Offline",
    }


def test_benchmark_mode_forces_temperature_seed(monkeypatch):
    store = {}
    _install_fake_openai(monkeypatch, store)

    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", True, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_SEED", 2025, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_HTTP_REFERER", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_X_TITLE", None, raising=False)

    client = llm_client_module.LLMClient()
    client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.9)

    assert store["create_kwargs"]["temperature"] == 0.0
    assert store["create_kwargs"]["seed"] == 42


def test_benchmark_mode_logs_warning_when_call_temperature_conflicts(monkeypatch):
    store = {}
    warnings = []
    _install_fake_openai(monkeypatch, store)

    def capture_warning(message, *args, **kwargs):
        warnings.append(message % args if args else message)

    monkeypatch.setattr(llm_client_module.logger, "warning", capture_warning)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", True, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_SEED", 42, raising=False)

    client = llm_client_module.LLMClient()
    client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.9)

    assert any("overriding requested temperature=0.9" in warning for warning in warnings)


def test_benchmark_mode_enforces_dispatch_kwargs_even_on_internal_calls(monkeypatch):
    store = {}
    warnings = []
    _install_fake_openai(monkeypatch, store)

    def capture_warning(message, *args, **kwargs):
        warnings.append(message % args if args else message)

    monkeypatch.setattr(llm_client_module.logger, "warning", capture_warning)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", True, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_SEED", 42, raising=False)

    client = llm_client_module.LLMClient()
    client._chat_create_with_retry(
        {
            "model": "openrouter/test-model",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.9,
            "seed": 999,
            "max_tokens": 64,
        }
    )

    assert store["create_kwargs"]["temperature"] == 0.0
    assert store["create_kwargs"]["seed"] == 42
    assert any("overriding requested temperature=0.9" in warning for warning in warnings)
    assert any("overriding requested seed=999" in warning for warning in warnings)


def test_negative_retry_max_retries_is_clamped(monkeypatch):
    store = {"calls": 0}

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            store["create_kwargs"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_HTTP_REFERER", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_X_TITLE", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", -7, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_INITIAL_DELAY", 0.1, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_DELAY", 1.0, raising=False)

    client = llm_client_module.LLMClient()
    response = client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.4)

    assert response == "ok"
    assert store["calls"] == 1


def test_negative_retry_max_delay_is_clamped(monkeypatch):
    store = {"calls": 0, "sleep_calls": []}

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            if store["calls"] == 1:
                raise TimeoutError("temporary timeout")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module.time, "sleep", store["sleep_calls"].append)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_HTTP_REFERER", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_X_TITLE", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", 2, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_INITIAL_DELAY", 0.2, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_DELAY", -5.0, raising=False)

    client = llm_client_module.LLMClient()
    response = client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.4)

    assert response == "ok"
    assert store["calls"] == 2
    assert store["sleep_calls"] == [0.0]


def test_retry_backoff_applies_deterministic_jitter(monkeypatch):
    store = {"calls": 0, "sleep_calls": []}

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            if store["calls"] < 3:
                raise TimeoutError(f"temporary timeout {store['calls']}")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    jitter_values = iter([0.125, 0.25])

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module.time, "sleep", store["sleep_calls"].append)
    monkeypatch.setattr(llm_client_module.random, "uniform", lambda a, b: next(jitter_values))
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_HTTP_REFERER", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_X_TITLE", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", 3, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_INITIAL_DELAY", 0.5, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_DELAY", 2.0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_JITTER_MAX", 0.25, raising=False)

    client = llm_client_module.LLMClient()
    response = client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.4)

    assert response == "ok"
    assert store["calls"] == 3
    assert store["sleep_calls"] == [0.625, 1.25]


def test_rate_limit_retries_even_when_max_retries_zero(monkeypatch):
    store = {"calls": 0, "sleep_calls": []}

    class FakeRateLimitError(Exception):
        def __init__(self):
            self.body = {
                "error": {
                    "metadata": {
                        "headers": {
                            "X-RateLimit-Reset": "4102444800000",
                        }
                    }
                }
            }

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            if store["calls"] == 1:
                raise FakeRateLimitError()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

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
    assert store["sleep_calls"] == [300.0]


def test_rate_limit_reset_wait_zero_uses_min_positive_sleep(monkeypatch):
    store = {"calls": 0, "sleep_calls": []}

    class FakeRateLimitError(Exception):
        def __init__(self):
            self.body = {
                "error": {
                    "metadata": {
                        "headers": {
                            "X-RateLimit-Reset": "100",
                        }
                    }
                }
            }

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            if store["calls"] == 1:
                raise FakeRateLimitError()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(llm_client_module.time, "sleep", store["sleep_calls"].append)
    monkeypatch.setattr(llm_client_module.time, "time", lambda: 100.0)
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
    assert store["sleep_calls"] == [0.1]


def test_rate_limit_without_reset_uses_backoff_sleep(monkeypatch):
    store = {"calls": 0, "sleep_calls": []}

    class FakeRateLimitError(Exception):
        body = {"error": {"message": "slow down"}}

    class FakeCompletions:
        def create(self, **kwargs):
            store["calls"] += 1
            if store["calls"] == 1:
                raise FakeRateLimitError()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_client_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client_module, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(llm_client_module.time, "sleep", store["sleep_calls"].append)
    monkeypatch.setattr(llm_client_module.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_HTTP_REFERER", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "OPENROUTER_X_TITLE", None, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", 0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_INITIAL_DELAY", 0.2, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_DELAY", 1.0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_JITTER_MAX", 0.25, raising=False)

    client = llm_client_module.LLMClient()
    response = client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.4)

    assert response == "ok"
    assert store["calls"] == 2
    assert store["sleep_calls"] == [0.2]


def test_invalid_retry_config_raises_clear_error(monkeypatch):
    store = {}
    _install_fake_openai(monkeypatch, store)

    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", "invalid", raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_INITIAL_DELAY", 0.1, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_DELAY", 1.0, raising=False)

    with pytest.raises(ValueError, match="LLM_RETRY_MAX_RETRIES must be an integer >= 0"):
        llm_client_module.LLMClient()


def test_invalid_jitter_config_raises_clear_error(monkeypatch):
    store = {}
    _install_fake_openai(monkeypatch, store)

    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_RETRIES", 3, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_INITIAL_DELAY", 0.1, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_MAX_DELAY", 1.0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "LLM_RETRY_JITTER_MAX", "invalid-jitter", raising=False)

    with pytest.raises(ValueError, match="LLM_RETRY_JITTER_MAX must be a number >= 0"):
        llm_client_module.LLMClient()


def test_invalid_benchmark_config_is_overridden_with_enforced_defaults(monkeypatch):
    store = {}
    warnings = []
    _install_fake_openai(monkeypatch, store)

    def capture_warning(message, *args, **kwargs):
        warnings.append(message % args if args else message)

    monkeypatch.setattr(llm_client_module.logger, "warning", capture_warning)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", True, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_TEMPERATURE", "invalid", raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_SEED", 2025, raising=False)

    client = llm_client_module.LLMClient()
    client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.1)

    assert store["create_kwargs"]["temperature"] == 0.0
    assert store["create_kwargs"]["seed"] == 42
    assert any("overriding BENCHMARK_TEMPERATURE='invalid'" in warning for warning in warnings)
    assert any("overriding BENCHMARK_SEED=2025" in warning for warning in warnings)


def test_invalid_benchmark_seed_is_overridden_with_enforced_defaults(monkeypatch):
    store = {}
    warnings = []
    _install_fake_openai(monkeypatch, store)

    def capture_warning(message, *args, **kwargs):
        warnings.append(message % args if args else message)

    monkeypatch.setattr(llm_client_module.logger, "warning", capture_warning)
    monkeypatch.setattr(llm_client_module.Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_client_module.Config, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_client_module.Config, "LLM_MODEL_NAME", "openrouter/test-model")
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_MODE", True, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(llm_client_module.Config, "BENCHMARK_SEED", "invalid-seed", raising=False)

    client = llm_client_module.LLMClient()
    client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.1)

    assert store["create_kwargs"]["temperature"] == 0.0
    assert store["create_kwargs"]["seed"] == 42
    assert any("overriding BENCHMARK_SEED='invalid-seed'" in warning for warning in warnings)


def test_chat_json_repairs_truncated_payload_when_opted_in(monkeypatch):
    client = _create_test_client(monkeypatch)
    monkeypatch.setattr(
        client,
        "chat",
        lambda **kwargs: "```json\n{\"items\": [1, 2\n```",
    )

    parsed = client.chat_json(
        messages=[{"role": "user", "content": "return json"}],
        repair_truncated_json=True,
    )

    assert parsed == {"items": [1, 2]}


def test_chat_json_repairs_unterminated_string_at_eof_when_opted_in(monkeypatch):
    client = _create_test_client(monkeypatch)
    monkeypatch.setattr(
        client,
        "chat",
        lambda **kwargs: "```json\n{\"a\":\"abc\n```",
    )

    parsed = client.chat_json(
        messages=[{"role": "user", "content": "return json"}],
        repair_truncated_json=True,
    )

    assert parsed == {"a": "abc"}


def test_chat_json_truncation_repair_is_opt_in(monkeypatch):
    client = _create_test_client(monkeypatch)
    monkeypatch.setattr(
        client,
        "chat",
        lambda **kwargs: "```json\n{\"items\": [1, 2\n```",
    )

    with pytest.raises(ValueError, match="Invalid JSON format from LLM:"):
        client.chat_json(messages=[{"role": "user", "content": "return json"}])


def test_chat_json_repair_keeps_error_for_non_truncated_payload(monkeypatch):
    client = _create_test_client(monkeypatch)
    monkeypatch.setattr(
        client,
        "chat",
        lambda **kwargs: "{\"items\": [1,, 2]}",
    )

    with pytest.raises(ValueError, match="Invalid JSON format from LLM:"):
        client.chat_json(
            messages=[{"role": "user", "content": "return json"}],
            repair_truncated_json=True,
        )
