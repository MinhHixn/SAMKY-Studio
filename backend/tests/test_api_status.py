from app import create_app


def test_api_status_reports_healthy_dependencies(monkeypatch):
    app = create_app()
    app.extensions["neo4j_storage"] = type("S", (), {"verify_connection": lambda self: True})()

    from app.api import system as system_api

    monkeypatch.setattr(
        system_api.requests,
        "get",
        lambda *args, **kwargs: type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: {"models": [{"name": "qwen2.5:32b"}]},
            },
        )(),
    )
    disk_usage_calls = []

    def fake_disk_usage(path):
        disk_usage_calls.append(path)
        return (1000, 400, 600)

    monkeypatch.setattr(system_api.shutil, "disk_usage", fake_disk_usage)

    client = app.test_client()
    response = client.get("/api/status")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["neo4j"]["connected"] is True
    assert payload["data"]["neo4j"]["error"] is None
    assert payload["data"]["ollama"]["reachable"] is True
    assert payload["data"]["ollama"]["model_configured"] == "qwen2.5:32b"
    assert payload["data"]["ollama"]["model_available"] is True
    assert payload["data"]["disk"]["path"] == app.config["OASIS_SIMULATION_DATA_DIR"]
    assert payload["data"]["disk"]["free_bytes"] == 600
    assert disk_usage_calls == [app.config["OASIS_SIMULATION_DATA_DIR"]]
    assert "timestamp_utc" in payload["data"]


def test_api_status_reports_degraded_subsystems(monkeypatch):
    app = create_app()
    app.extensions["neo4j_storage"] = object()

    from app.api import system as system_api

    def raise_ollama(*_args, **_kwargs):
        raise RuntimeError("connection refused at 127.0.0.1:11434")

    monkeypatch.setattr(system_api.requests, "get", raise_ollama)
    monkeypatch.setattr(system_api.shutil, "disk_usage", lambda _path: (1000, 900, 100))

    client = app.test_client()
    response = client.get("/api/status")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["data"]["neo4j"]["connected"] is False
    assert payload["data"]["neo4j"]["error"] == "Neo4j health check unavailable"
    assert payload["data"]["ollama"]["reachable"] is False
    assert payload["data"]["ollama"]["error"] == "Failed to reach Ollama service"
    assert "127.0.0.1:11434" not in payload["data"]["ollama"]["error"]


def test_api_status_reports_disk_check_error_without_failing_request(monkeypatch):
    app = create_app()
    app.extensions["neo4j_storage"] = type("S", (), {"verify_connection": lambda self: True})()

    from app.api import system as system_api

    monkeypatch.setattr(
        system_api.requests,
        "get",
        lambda *args, **kwargs: type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: {"models": [{"name": "qwen2.5:32b"}]},
            },
        )(),
    )

    def raise_disk_error(_path):
        raise FileNotFoundError("secret/internal/path")

    monkeypatch.setattr(system_api.shutil, "disk_usage", raise_disk_error)

    client = app.test_client()
    response = client.get("/api/status")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["neo4j"]["connected"] is True
    assert payload["data"]["neo4j"]["error"] is None
    assert payload["data"]["ollama"]["reachable"] is True
    assert payload["data"]["ollama"]["error"] is None
    assert payload["data"]["disk"]["path"] == app.config["OASIS_SIMULATION_DATA_DIR"]
    assert payload["data"]["disk"]["error"] == "Failed to determine disk usage"
    assert "secret/internal/path" not in payload["data"]["disk"]["error"]
