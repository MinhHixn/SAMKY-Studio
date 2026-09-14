"""System status API routes."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask import current_app, jsonify, request

from . import system_bp
from ..config import Config


@system_bp.route("/runtime", methods=["GET", "POST"])
def studio_runtime():
    from ..services.studio_runtime import public_runtime, validate_runtime, configure_runtime
    if request.method == "GET":
        return jsonify(success=True, data=public_runtime())
    try:
        settings = validate_runtime(request.get_json(silent=True))
        return jsonify(success=True, data=configure_runtime(settings, current_app))
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(success=False, error=str(exc)), 409


@system_bp.route("/runtime/models", methods=["POST"])
def studio_models():
    from ..services.studio_runtime import validate_runtime, models_for
    try:
        settings = validate_runtime(request.get_json(silent=True), require_model=False)
        return jsonify(success=True, data={"models": models_for(settings)})
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400


def _check_neo4j():
    storage = current_app.extensions.get("neo4j_storage")
    if storage is None:
        return {"connected": False, "error": "Neo4j storage is not initialized"}

    try:
        verify_connection = getattr(storage, "verify_connection", None)
        if callable(verify_connection):
            connected = bool(verify_connection())
        else:
            driver = getattr(storage, "_driver", None)
            if driver is None or not callable(getattr(driver, "verify_connectivity", None)):
                return {"connected": False, "error": "Neo4j health check unavailable"}
            driver.verify_connectivity()
            connected = True
        return {
            "connected": connected,
            "error": None if connected else "Neo4j verification failed",
        }
    except Exception as exc:
        current_app.logger.exception("Neo4j status check failed: %s", exc)
        return {"connected": False, "error": "Failed to verify Neo4j connectivity"}


def _check_ollama():
    """Legacy Ollama health payload kept for backwards-compatible clients."""
    model = Config.LLM_MODEL_NAME
    base_url = Config.LLM_BASE_URL
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
        model_names = {
            item.get("name")
            for item in response.json().get("models", [])
            if isinstance(item, dict)
        }
        return {
            "reachable": True,
            "model_configured": model,
            "model_available": model in model_names,
            "error": None,
        }
    except Exception as exc:
        current_app.logger.exception("Ollama status check failed: %s", exc)
        return {
            "reachable": False,
            "model_configured": model,
            "model_available": False,
            "error": "Failed to reach Ollama service",
        }


def _check_runtime(ollama_status):
    """Report the active model runtime without exposing credentials or full URLs."""
    base_url = (Config.LLM_BASE_URL or "").rstrip("/")
    parsed = urlparse(base_url)
    local_hosts = {"localhost", "127.0.0.1", "::1", "ollama", "host.docker.internal"}
    is_local = parsed.hostname in local_hosts

    if is_local:
        return {
            "mode": "offline",
            "provider": "Ollama / local OpenAI-compatible",
            "model": Config.LLM_MODEL_NAME,
            "reachable": bool(ollama_status.get("reachable")),
            "model_available": bool(ollama_status.get("model_available")),
            "host": parsed.hostname or "local",
            "error": ollama_status.get("error"),
        }

    if not parsed.scheme or not parsed.hostname:
        return {
            "mode": "online",
            "provider": "OpenAI-compatible",
            "model": Config.LLM_MODEL_NAME,
            "reachable": False,
            "model_available": False,
            "host": None,
            "error": "Invalid model endpoint configuration",
        }

    headers = {}
    if Config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {Config.LLM_API_KEY}"

    try:
        response = requests.get(f"{base_url}/models", headers=headers, timeout=5)
        response.raise_for_status()
        return {
            "mode": "online",
            "provider": "OpenAI-compatible",
            "model": Config.LLM_MODEL_NAME,
            "reachable": True,
            "model_available": True,
            "host": parsed.hostname,
            "error": None,
        }
    except Exception as exc:
        current_app.logger.warning("Online model status check failed: %s", exc)
        return {
            "mode": "online",
            "provider": "OpenAI-compatible",
            "model": Config.LLM_MODEL_NAME,
            "reachable": False,
            "model_available": False,
            "host": parsed.hostname,
            "error": "Failed to reach configured model service",
        }


@system_bp.route("/status", methods=["GET"])
def get_status():
    disk_path = Config.OASIS_SIMULATION_DATA_DIR or Config.UPLOAD_FOLDER or "."
    disk = {"path": disk_path, "error": None}
    try:
        total, used, free = shutil.disk_usage(disk_path)
        disk.update(
            {
                "total_bytes": int(total),
                "used_bytes": int(used),
                "free_bytes": int(free),
            }
        )
    except Exception as exc:
        current_app.logger.exception("Disk status check failed: %s", exc)
        disk.update(
            {
                "total_bytes": None,
                "used_bytes": None,
                "free_bytes": None,
                "error": "Failed to determine disk usage",
            }
        )

    ollama_status = _check_ollama()
    return jsonify(
        {
            "success": True,
            "data": {
                "neo4j": _check_neo4j(),
                "ollama": ollama_status,
                "runtime": _check_runtime(ollama_status),
                "disk": disk,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },
        }
    )
