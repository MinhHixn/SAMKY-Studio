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
    monkeypatch.setattr(system_api.shutil, "disk_usage", lambda _path: (1000, 400, 600))

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
    assert payload["data"]["disk"]["free_bytes"] == 600
    assert "timestamp_utc" in payload["data"]


def test_api_status_reports_degraded_subsystems(monkeypatch):
    app = create_app()
    app.extensions["neo4j_storage"] = None

    from app.api import system as system_api

    def raise_ollama(*_args, **_kwargs):
        raise RuntimeError("ollama unavailable")

    monkeypatch.setattr(system_api.requests, "get", raise_ollama)
    monkeypatch.setattr(system_api.shutil, "disk_usage", lambda _path: (1000, 900, 100))

    client = app.test_client()
    response = client.get("/api/status")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["data"]["neo4j"]["connected"] is False
    assert payload["data"]["ollama"]["reachable"] is False
    assert "error" in payload["data"]["ollama"]
