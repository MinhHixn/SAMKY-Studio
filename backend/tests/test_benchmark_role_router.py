import pytest

from app import config as config_module
from app.benchmarks import role_router as role_router_module


def test_missing_role_model_config_raises_value_error(monkeypatch):
    monkeypatch.setattr(config_module.Config, "OPENROUTER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(
        config_module.Config,
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
        raising=False,
    )
    monkeypatch.setattr(config_module.Config, "OPENROUTER_GRAPH_MODEL", None, raising=False)
    monkeypatch.setattr(
        config_module.Config,
        "OPENROUTER_BENCHMARK_MODEL",
        "openrouter/benchmark-model",
        raising=False,
    )
    monkeypatch.setattr(
        config_module.Config,
        "OPENROUTER_EVALUATOR_MODEL",
        "openrouter/evaluator-model",
        raising=False,
    )

    with pytest.raises(ValueError, match="OPENROUTER_GRAPH_MODEL"):
        role_router_module.BenchmarkRoleRouter(config=config_module.Config)


def test_explicit_role_routing_returns_exact_model_per_role(monkeypatch):
    class FakeConfig:
        OPENROUTER_API_KEY = "test-key"
        OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
        OPENROUTER_GRAPH_MODEL = "openrouter/graph-model"
        OPENROUTER_BENCHMARK_MODEL = "openrouter/benchmark-model"
        OPENROUTER_EVALUATOR_MODEL = "openrouter/evaluator-model"

    created_clients = []

    class FakeLLMClient:
        def __init__(self, api_key=None, base_url=None, model=None, timeout=300.0):
            created_clients.append((api_key, base_url, model, timeout))
            self.api_key = api_key
            self.base_url = base_url
            self.model = model

    monkeypatch.setattr(role_router_module, "LLMClient", FakeLLMClient)

    router = role_router_module.BenchmarkRoleRouter(config=FakeConfig)

    assert router.model_for("graph") == "openrouter/graph-model"
    assert router.model_for("benchmark") == "openrouter/benchmark-model"
    assert router.model_for("evaluator") == "openrouter/evaluator-model"

    graph_client = router.client_for("graph")
    benchmark_client = router.client_for("benchmark")
    evaluator_client = router.client_for("evaluator")

    assert graph_client.model == "openrouter/graph-model"
    assert benchmark_client.model == "openrouter/benchmark-model"
    assert evaluator_client.model == "openrouter/evaluator-model"
    assert created_clients == [
        ("test-key", "https://openrouter.ai/api/v1", "openrouter/graph-model", 300.0),
        ("test-key", "https://openrouter.ai/api/v1", "openrouter/benchmark-model", 300.0),
        ("test-key", "https://openrouter.ai/api/v1", "openrouter/evaluator-model", 300.0),
    ]
