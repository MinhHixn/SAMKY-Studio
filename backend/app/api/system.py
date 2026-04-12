"""
System status API routes.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone

import requests
from flask import current_app, jsonify

from . import system_bp
from ..config import Config


def _check_neo4j():
    storage = current_app.extensions.get("neo4j_storage")
    if storage is None:
        return {"connected": False, "error": "Neo4j storage is not initialized"}

    try:
        verify_connection = getattr(storage, "verify_connection", None)
        if not callable(verify_connection):
            return {"connected": False, "error": "Neo4j health check unavailable"}

        connected = bool(verify_connection())
        return {
            "connected": connected,
            "error": None if connected else "Neo4j verification failed",
        }
    except Exception as exc:
        current_app.logger.exception("Neo4j status check failed: %s", exc)
        return {"connected": False, "error": "Failed to verify Neo4j connectivity"}


def _check_ollama():
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


@system_bp.route("/status", methods=["GET"])
def get_status():
    disk_path = Config.OASIS_SIMULATION_DATA_DIR or Config.UPLOAD_FOLDER or "."
    total, used, free = shutil.disk_usage(disk_path)

    return jsonify(
        {
            "success": True,
            "data": {
                "neo4j": _check_neo4j(),
                "ollama": _check_ollama(),
                "disk": {
                    "path": disk_path,
                    "total_bytes": int(total),
                    "used_bytes": int(used),
                    "free_bytes": int(free),
                },
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },
        }
    )
