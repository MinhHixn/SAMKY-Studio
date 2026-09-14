"""Contracts used by the minimal studio, with no real model or database calls."""
import json
import os
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import simulation_bp, system_bp, report_bp, graph_bp
from app.api import simulation as simulation_api
from app.config import Config
from app.models.task import TaskManager
from app.services import studio_runtime as runtime
from app.services.simulation_manager import SimulationStatus
from app.services.simulation_runner import SimulationRunner


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    app.register_blueprint(report_bp, url_prefix="/api/report")
    app.register_blueprint(graph_bp, url_prefix="/api/graph")
    app.extensions["neo4j_storage"] = SimpleNamespace(_ner=SimpleNamespace(llm=None))
    monkeypatch.setattr(runtime, "active_requests", 0)
    monkeypatch.setattr(TaskManager, "list_tasks", lambda self, **kwargs: [])
    monkeypatch.setattr(SimulationRunner, "_processes", {})
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "test-model")
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-secret")
    monkeypatch.delenv("SAM_RUNTIME_MODE", raising=False)
    for name in ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_NAME", "OPENAI_API_KEY", "OPENAI_API_BASE_URL"]:
        monkeypatch.setenv(name, "before")
    from app.utils import llm_client
    monkeypatch.setattr(llm_client, "LLMClient", lambda **kwargs: SimpleNamespace(**kwargs))
    return app.test_client()


def settings(**overrides):
    return {"mode": "online", "base_url": "https://provider.example/v1", "model": "selected-model", **overrides}


def test_status_never_returns_key(client):
    response = client.get("/api/runtime")
    assert response.status_code == 200
    assert response.json["data"]["has_api_key"] is True
    assert "test-secret" not in response.text


def test_online_model_and_key_reach_ner_and_child_process_environment(client):
    response = client.post("/api/runtime", json=settings(api_key="new-secret"))
    assert response.status_code == 200
    assert "new-secret" not in response.text
    assert Config.LLM_MODEL_NAME == "selected-model"
    assert os.environ["LLM_API_KEY"] == os.environ["OPENAI_API_KEY"] == "new-secret"
    assert os.environ["LLM_BASE_URL"] == os.environ["OPENAI_API_BASE_URL"] == "https://provider.example/v1"
    assert client.application.extensions["neo4j_storage"]._ner.llm.model == "selected-model"


def test_omitting_key_only_retains_it_for_same_endpoint_and_mode(client):
    assert runtime.validate_runtime(settings())["api_key"] == "test-secret"
    assert runtime.validate_runtime(settings(base_url="https://other.example/v1"))["api_key"] == ""
    assert runtime.validate_runtime(settings(mode="offline"))["api_key"] == ""


def test_explicit_remove_key_and_local_mode_do_not_reuse_online_secret(client):
    response = client.post("/api/runtime", json=settings(mode="offline", base_url="http://localhost:11434/v1", api_key=""))
    assert response.status_code == 200
    assert response.json["data"]["has_api_key"] is False
    assert Config.LLM_API_KEY == "sam-local"
    assert os.environ["OPENAI_API_KEY"] == "sam-local"


@pytest.mark.parametrize("payload", [None, [], settings(base_url="https://secret@provider.example/v1"), settings(base_url="http://provider.example/v1"), settings(base_url="https://provider.example/v1?key=secret"), settings(model=""), settings(mode="invalid"), settings(api_key="a\nb")])
def test_invalid_runtime_does_not_change_configuration(client, payload):
    response = client.post("/api/runtime", json=payload)
    assert response.status_code == 400
    assert Config.LLM_API_KEY == "test-secret"


@pytest.mark.parametrize("busy", ["request", "task", "process"])
def test_active_work_locks_runtime(client, monkeypatch, busy):
    if busy == "request":
        monkeypatch.setattr(runtime, "active_requests", 1)
    elif busy == "task":
        monkeypatch.setattr(TaskManager, "list_tasks", lambda self: [{"status": "processing"}])
    else:
        monkeypatch.setattr(SimulationRunner, "_processes", {"simulation": SimpleNamespace(poll=lambda: None)})
    response = client.post("/api/runtime", json=settings(api_key="new"))
    assert response.status_code == 409
    assert Config.LLM_API_KEY == "test-secret"


def test_model_discovery_uses_selected_provider_and_does_not_follow_redirects(client, monkeypatch):
    calls = []
    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "local-a"}, {"id": "local-b"}]})
    monkeypatch.setattr(runtime.requests, "get", fake_get)
    response = client.post("/api/runtime/models", json=settings(base_url="https://other.example/v1"))
    assert response.json["data"]["models"] == ["local-a", "local-b"]
    assert calls[0][1]["headers"] == {}
    assert calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("rounds", [0, -1, 1.5, "60", True, 1001])
def test_round_validation_happens_before_start(client, rounds):
    response = client.post("/api/simulation/start", json={"simulation_id": "not-a-real-run", "rounds": rounds})
    assert response.status_code == 400
    assert "rounds" in response.json["error"]


def test_exact_rounds_extend_generated_duration_and_pass_graph_storage(client, monkeypatch, tmp_path):
    config_path = tmp_path / "simulation_config.json"
    config_path.write_text(json.dumps({"time_config": {"minutes_per_round": 30, "total_simulation_hours": 20}}))
    state = SimpleNamespace(status=SimulationStatus.READY, graph_id="graph-test")
    manager = SimpleNamespace(get_simulation=lambda _: state, _get_simulation_dir=lambda _: str(tmp_path), _save_simulation_state=lambda _: None)
    monkeypatch.setattr(simulation_api, "SimulationManager", lambda: manager)
    monkeypatch.setattr(SimulationRunner, "has_live_process", lambda _: False)
    calls = []
    def start(**kwargs):
        calls.append(kwargs)
        config = json.loads(config_path.read_text())
        assert config["time_config"]["total_rounds"] == 60
        assert config["time_config"]["total_simulation_hours"] == 30
        return SimpleNamespace(to_dict=lambda: {"runner_status": "running", "total_rounds": 60})
    monkeypatch.setattr(SimulationRunner, "start_simulation", start)
    response = client.post("/api/simulation/start", json={"simulation_id": "sim-test", "rounds": 60, "enable_graph_memory_update": True, "interactive": True})
    assert response.status_code == 200, response.json
    assert response.json["data"]["total_rounds"] == 60
    assert calls[0]["storage"] is client.application.extensions["neo4j_storage"]
    assert calls[0]["max_rounds"] is None
    assert calls[0]["interactive"] is True


def test_legacy_max_rounds_remains_a_truncation_option(client, monkeypatch):
    state = SimpleNamespace(status=SimulationStatus.READY, graph_id="graph-test")
    monkeypatch.setattr(simulation_api, "SimulationManager", lambda: SimpleNamespace(get_simulation=lambda _: state, _save_simulation_state=lambda _: None))
    monkeypatch.setattr(SimulationRunner, "has_live_process", lambda _: False)
    calls = []
    monkeypatch.setattr(SimulationRunner, "start_simulation", lambda **kwargs: (calls.append(kwargs) or SimpleNamespace(to_dict=lambda: {"runner_status": "running"})))
    response = client.post("/api/simulation/start", json={"simulation_id": "sim-test", "max_rounds": 8})
    assert response.status_code == 200
    assert calls[0]["max_rounds"] == 8
    assert calls[0]["interactive"] is False


def test_studio_report_starts_asynchronously_even_with_benchmark_mode(client, monkeypatch):
    from app.api import report as report_api
    from app.services.report_agent import ReportManager

    monkeypatch.setattr(report_api, '_is_headless_mode_enabled', lambda: True)
    monkeypatch.setattr(report_api, 'SimulationManager', lambda: SimpleNamespace(get_simulation=lambda _: SimpleNamespace(project_id='project', graph_id='graph')))
    monkeypatch.setattr(report_api.ProjectManager, 'get_project', lambda _: SimpleNamespace(graph_id='graph', simulation_requirement='Scenario'))
    monkeypatch.setattr(ReportManager, 'get_report_by_simulation', lambda _: None)
    monkeypatch.setattr(TaskManager, 'create_task', lambda *args, **kwargs: 'task-test')
    monkeypatch.setattr(report_api, 'GraphToolsService', lambda **kwargs: object())
    started = []
    monkeypatch.setattr(report_api.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: started.append(True)))

    response = client.post('/api/report/generate', json={'simulation_id': 'sim-test', 'run_async': True})
    assert response.status_code == 200, response.json
    assert response.json['data']['status'] == 'generating'
    assert started == [True]


def test_discovery_does_not_require_knowing_the_model_id(client, monkeypatch):
    monkeypatch.setattr(runtime.requests, "get", lambda *a, **kw: SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "discoverable-model"}]}))
    response = client.post("/api/runtime/models", json=settings(model=""))
    assert response.status_code == 200
    assert response.json["data"]["models"] == ["discoverable-model"]


def test_profile_concurrency_increases_only_for_online_runtime(client, monkeypatch):
    monkeypatch.setenv("SAM_RUNTIME_MODE", "online")
    assert simulation_api._profile_concurrency({}) == 12
    monkeypatch.setenv("SAM_RUNTIME_MODE", "offline")
    assert simulation_api._profile_concurrency({}) == 5
    assert simulation_api._profile_concurrency({"parallel_profile_count": 8}) == 8


@pytest.mark.parametrize("count", [0, 33, True, "12", 2.5])
def test_profile_concurrency_rejects_invalid_overrides(client, count):
    with pytest.raises(ValueError, match="parallel_profile_count"):
        simulation_api._profile_concurrency({"parallel_profile_count": count})


def test_project_rounds_survive_server_serialization():
    from app.models.project import Project
    data = {"project_id": "test", "name": "Example", "studio_settings": {"rounds": 85, "platform": "reddit"}}
    restored = Project.from_dict(Project.from_dict(data).to_dict())
    assert restored.studio_settings == {"rounds": 85, "platform": "reddit"}
    assert Project.from_dict({"project_id": "legacy"}).studio_settings == {}


def test_invalid_initial_rounds_rejected_before_upload_or_llm(client):
    response = client.post("/api/graph/ontology/generate", data={"simulation_requirement": "A fictional test", "rounds": "1.5"})
    assert response.status_code == 400
    assert "rounds" in response.json["error"]


@pytest.mark.parametrize("kind,path", [("simulation_prepare", "/api/simulation/prepare"), ("report_generate", "/api/report/generate")])
def test_reloading_attaches_to_existing_task(client, monkeypatch, kind, path):
    monkeypatch.setattr(TaskManager, "list_tasks", lambda self, **kwargs: [{"task_id": "existing-task", "status": "processing", "progress": 25, "metadata": {"simulation_id": "sim-test", "report_id": "existing-report"}}])
    monkeypatch.setattr(simulation_api, "SimulationManager", lambda: SimpleNamespace(get_simulation=lambda _: SimpleNamespace(status=SimulationStatus.PREPARING)))
    response = client.post(path, json={"simulation_id": "sim-test"})
    assert response.status_code == 200, response.json
    assert response.json["data"]["task_id"] == "existing-task"
