from types import SimpleNamespace

from app import create_app
from app.api import report as report_api
from app.api import simulation as simulation_api
from app import storage as storage_module
from app.models import task as task_module


class _FakeTask:
    def __init__(self, task_id):
        self.task_id = task_id
        self.error = None


class _FakeTaskManager:
    def __init__(self):
        self._tasks = {}

    def create_task(self, task_type, metadata=None):
        task_id = f"task-{len(self._tasks) + 1}"
        self._tasks[task_id] = _FakeTask(task_id)
        return task_id

    def update_task(self, task_id, **kwargs):
        task = self._tasks.get(task_id)
        if not task:
            return
        if "error" in kwargs:
            task.error = kwargs["error"]

    def complete_task(self, task_id, result):
        _ = result
        self.update_task(task_id)

    def fail_task(self, task_id, error):
        self.update_task(task_id, error=error)

    def get_task(self, task_id):
        return self._tasks.get(task_id)


def test_report_generate_runs_synchronously_in_headless_mode(monkeypatch):
    monkeypatch.setattr(storage_module, "Neo4jStorage", lambda: object())
    app = create_app()
    app.extensions["neo4j_storage"] = object()
    client = app.test_client()

    reports = {}

    class FakeSimulationManager:
        def get_simulation(self, simulation_id):
            return SimpleNamespace(project_id="proj-1", graph_id="graph-1")

    class FakeProjectManager:
        @staticmethod
        def get_project(project_id):
            _ = project_id
            return SimpleNamespace(graph_id="graph-1", simulation_requirement="Generate report")

    class FakeReportManager:
        @staticmethod
        def get_report_by_simulation(simulation_id):
            _ = simulation_id
            return None

        @staticmethod
        def save_report(report):
            reports[report.report_id] = report

        @staticmethod
        def get_report(report_id):
            return reports.get(report_id)

    class FakeReportAgent:
        def __init__(self, **kwargs):
            _ = kwargs

        def generate_report(self, progress_callback, report_id):
            _ = progress_callback
            return SimpleNamespace(
                report_id=report_id,
                status=report_api.ReportStatus.COMPLETED,
                error=None,
            )

    class FakeGraphToolsService:
        def __init__(self, storage):
            self.storage = storage

    monkeypatch.setattr(report_api.Config, "HEADLESS_MODE", True, raising=False)
    monkeypatch.setattr(report_api.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(report_api, "SimulationManager", FakeSimulationManager)
    monkeypatch.setattr(report_api, "ProjectManager", FakeProjectManager)
    monkeypatch.setattr(report_api, "ReportManager", FakeReportManager)
    monkeypatch.setattr(report_api, "ReportAgent", FakeReportAgent)
    monkeypatch.setattr(report_api, "TaskManager", _FakeTaskManager)
    monkeypatch.setattr(report_api, "GraphToolsService", FakeGraphToolsService)

    response = client.post("/api/report/generate", json={"simulation_id": "sim-1"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["already_generated"] is False


def test_simulation_prepare_runs_synchronously_in_headless_mode(monkeypatch):
    monkeypatch.setattr(storage_module, "Neo4jStorage", lambda: object())
    app = create_app()
    app.extensions["neo4j_storage"] = object()
    client = app.test_client()

    state = SimpleNamespace(
        simulation_id="sim-1",
        project_id="proj-1",
        graph_id="graph-1",
        status=simulation_api.SimulationStatus.CREATED,
        entities_count=0,
        entity_types=[],
        error=None,
        to_simple_dict=lambda: {"simulation_id": "sim-1", "status": "ready"},
    )

    class FakeSimulationManager:
        def __init__(self):
            self._state = state

        def get_simulation(self, simulation_id):
            _ = simulation_id
            return self._state

        def _save_simulation_state(self, new_state):
            self._state = new_state

        def prepare_simulation(self, **kwargs):
            _ = kwargs
            self._state.status = simulation_api.SimulationStatus.READY
            self._state.entities_count = 2
            self._state.entity_types = ["Person", "Organization"]
            return self._state

    class FakeProjectManager:
        @staticmethod
        def get_project(project_id):
            _ = project_id
            return SimpleNamespace(simulation_requirement="Run simulation")

        @staticmethod
        def get_extracted_text(project_id):
            _ = project_id
            return "doc"

    class FakeEntityReader:
        def __init__(self, storage):
            self.storage = storage

        def filter_defined_entities(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(filtered_count=2, entity_types=["Person", "Organization"])

    monkeypatch.setattr(simulation_api.Config, "HEADLESS_MODE", True, raising=False)
    monkeypatch.setattr(simulation_api.Config, "BENCHMARK_MODE", False, raising=False)
    monkeypatch.setattr(simulation_api, "SimulationManager", FakeSimulationManager)
    monkeypatch.setattr(simulation_api, "ProjectManager", FakeProjectManager)
    monkeypatch.setattr(task_module, "TaskManager", _FakeTaskManager)
    monkeypatch.setattr(simulation_api, "EntityReader", FakeEntityReader)

    response = client.post(
        "/api/simulation/prepare",
        json={"simulation_id": "sim-1", "force_regenerate": True},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["status"] == "ready"
    assert payload["data"]["already_prepared"] is False
    assert payload["data"]["expected_entities_count"] == 2
