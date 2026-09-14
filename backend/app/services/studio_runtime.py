"""In-memory model selection for a single SAMKY Studio server.

Credentials never enter project files, status responses, or browser storage.
The shared runtime cannot change while a request, task, or OASIS process uses it.
"""
import os
import threading
from urllib.parse import urlparse

import requests

from ..config import Config

lock = threading.RLock()
active_requests = 0
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "ollama", "host.docker.internal"}


def public_runtime():
    endpoint = Config.LLM_BASE_URL or ""
    return {
        "mode": os.environ.get("SAM_RUNTIME_MODE") or ("offline" if urlparse(endpoint).hostname in LOCAL_HOSTS else "online"),
        "base_url": endpoint,
        "model": Config.LLM_MODEL_NAME,
        "has_api_key": bool(Config.LLM_API_KEY and Config.LLM_API_KEY not in {"ollama", "sam-local"}),
    }


def validate_runtime(data, *, require_model=True):
    if not isinstance(data, dict):
        raise ValueError("Model settings must be an object.")
    mode = data.get("mode", "offline")
    endpoint = str(data.get("base_url", "")).strip().rstrip("/")
    model = str(data.get("model", "")).strip()
    parsed = urlparse(endpoint)
    if mode not in {"online", "offline"}:
        raise ValueError("Choose online or offline.")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Enter an HTTP(S) API endpoint without credentials, query, or fragment.")
    if mode == "online" and parsed.scheme != "https":
        raise ValueError("Online endpoints must use HTTPS.")
    if (require_model and not model) or len(model) > 200:
        raise ValueError("Enter a model ID (up to 200 characters).")
    # Omitted key retains it only at the same endpoint AND mode. An explicit
    # empty string removes it. Never forward a previous provider's secret.
    same = endpoint == (Config.LLM_BASE_URL or "").rstrip("/") and mode == public_runtime()["mode"]
    key = data.get("api_key", (Config.LLM_API_KEY or "") if same else "")
    if not isinstance(key, str) or len(key) > 4096 or any(c in key for c in "\r\n"):
        raise ValueError("Invalid API key.")
    return {"mode": mode, "base_url": endpoint, "model": model, "api_key": key.strip()}


def models_for(settings):
    headers = {"Authorization": f"Bearer {settings['api_key']}"} if settings["api_key"] else {}
    try:
        response = requests.get(f"{settings['base_url']}/models", headers=headers, timeout=10, allow_redirects=False)
        if response.status_code in {401, 403}:
            raise ValueError("The endpoint rejected the API key.")
        if response.status_code != 200:
            raise ValueError("Cannot list models at this endpoint. Check the API base URL.")
        items = response.json().get("data", [])
        return sorted({item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)})
    except (requests.RequestException, KeyError, TypeError) as exc:
        raise ValueError("Cannot reach the model endpoint. Check its address and connection.") from exc


def configure_runtime(settings, app):
    from ..models.task import TaskManager
    from .simulation_runner import SimulationRunner
    from ..utils.llm_client import LLMClient

    with lock:
        busy = active_requests or any(t["status"] in {"pending", "processing"} for t in TaskManager().list_tasks())
        busy = busy or any(p.poll() is None for p in list(SimulationRunner._processes.values()))
        if busy:
            raise RuntimeError("A simulation, interview environment, or preparation is active. Finish it before changing the model.")
        key = settings["api_key"] or "sam-local"
        # Construct before committing, so an invalid client leaves the runtime intact.
        client = LLMClient(api_key=key, base_url=settings["base_url"], model=settings["model"])
        values = {"LLM_API_KEY": key, "LLM_BASE_URL": settings["base_url"], "LLM_MODEL_NAME": settings["model"]}
        for name, value in values.items():
            setattr(Config, name, value)
            app.config[name] = value
            os.environ[name] = value
        os.environ["SAM_RUNTIME_MODE"] = settings["mode"]
        # CAMEL/OASIS subprocesses inherit the same selected endpoint.
        os.environ["OPENAI_API_KEY"] = key
        os.environ["OPENAI_API_BASE_URL"] = settings["base_url"]
        storage = app.extensions.get("neo4j_storage")
        if storage is not None and hasattr(storage, "_ner"):
            storage._ner.llm = client
        return public_runtime()
