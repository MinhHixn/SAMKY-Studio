import pytest

from app import config as config_module
from app.benchmarks import role_router as role_router_module


def test_explicit_constructor_routes_models_without_config_injection(monkeypatch):
    created_clients = []

    class FakeLLMClient:
        def __init__(self, api_key=None, base_url=None, model=None, timeout=300.0):
            created_clients.append((api_key, base_url, model, timeout))
            self.api_key = api_key
            self.base_url = base_url
            self.model = model

    monkeypatch.setattr(role_router_module, "LLMClient", FakeLLMClient)

    router = role_router_module.BenchmarkRoleRouter(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        graph_model="openrouter/graph-model",
        benchmark_model="openrouter/benchmark-model",
        evaluator_model="openrouter/evaluator-model",
    )

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


def test_missing_api_key_mentions_allowed_sources(monkeypatch):
    monkeypatch.setattr(config_module.Config, "OPENROUTER_API_KEY", None, raising=False)
    monkeypatch.setattr(config_module.Config, "LLM_API_KEY", None, raising=False)
    monkeypatch.setattr(
        config_module.Config,
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
        raising=False,
    )
    monkeypatch.setattr(config_module.Config, "OPENROUTER_GRAPH_MODEL", "openrouter/graph-model", raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_BENCHMARK_MODEL", "openrouter/benchmark-model", raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_EVALUATOR_MODEL", "openrouter/evaluator-model", raising=False)

    with pytest.raises(ValueError, match=r"api_key.*OPENROUTER_API_KEY.*LLM_API_KEY.*pass api_key explicitly"):
        role_router_module.BenchmarkRoleRouter.from_config(config_module.Config)


def test_missing_base_url_raises_value_error(monkeypatch):
    monkeypatch.setattr(config_module.Config, "OPENROUTER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(config_module.Config, "LLM_API_KEY", None, raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_BASE_URL", None, raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_GRAPH_MODEL", "openrouter/graph-model", raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_BENCHMARK_MODEL", "openrouter/benchmark-model", raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_EVALUATOR_MODEL", "openrouter/evaluator-model", raising=False)

    with pytest.raises(ValueError, match=r"base_url.*OPENROUTER_BASE_URL"):
        role_router_module.BenchmarkRoleRouter.from_config(config_module.Config)


def test_missing_single_role_model_raises_value_error(monkeypatch):
    monkeypatch.setattr(config_module.Config, "OPENROUTER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(config_module.Config, "LLM_API_KEY", None, raising=False)
    monkeypatch.setattr(
        config_module.Config,
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
        raising=False,
    )
    monkeypatch.setattr(config_module.Config, "OPENROUTER_GRAPH_MODEL", None, raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_BENCHMARK_MODEL", "openrouter/benchmark-model", raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_EVALUATOR_MODEL", "openrouter/evaluator-model", raising=False)

    with pytest.raises(ValueError, match=r"graph_model.*OPENROUTER_GRAPH_MODEL"):
        role_router_module.BenchmarkRoleRouter.from_config(config_module.Config)


def test_missing_multiple_role_models_raises_value_error(monkeypatch):
    monkeypatch.setattr(config_module.Config, "OPENROUTER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(config_module.Config, "LLM_API_KEY", None, raising=False)
    monkeypatch.setattr(
        config_module.Config,
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
        raising=False,
    )
    monkeypatch.setattr(config_module.Config, "OPENROUTER_GRAPH_MODEL", None, raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_BENCHMARK_MODEL", None, raising=False)
    monkeypatch.setattr(config_module.Config, "OPENROUTER_EVALUATOR_MODEL", "openrouter/evaluator-model", raising=False)

    with pytest.raises(ValueError, match=r"graph_model.*benchmark_model"):
        role_router_module.BenchmarkRoleRouter.from_config(config_module.Config)


def test_explicit_role_routing_returns_exact_model_per_role(monkeypatch):
    created_clients = []

    class FakeLLMClient:
        def __init__(self, api_key=None, base_url=None, model=None, timeout=300.0):
            created_clients.append((api_key, base_url, model, timeout))
            self.api_key = api_key
            self.base_url = base_url
            self.model = model

    monkeypatch.setattr(role_router_module, "LLMClient", FakeLLMClient)

    router = role_router_module.BenchmarkRoleRouter(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        graph_model="openrouter/graph-model",
        benchmark_model="openrouter/benchmark-model",
        evaluator_model="openrouter/evaluator-model",
    )

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


@pytest.mark.parametrize("role", ["unknown", "", "graph "])
def test_unknown_role_paths_raise_value_error(role):
    router = role_router_module.BenchmarkRoleRouter(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        graph_model="openrouter/graph-model",
        benchmark_model="openrouter/benchmark-model",
        evaluator_model="openrouter/evaluator-model",
    )

    with pytest.raises(ValueError, match=r"Unknown benchmark role"):
        router.model_for(role)

    with pytest.raises(ValueError, match=r"Unknown benchmark role"):
        router.client_for(role)
