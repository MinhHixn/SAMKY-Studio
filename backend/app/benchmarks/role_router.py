"""Strict role-based router for benchmark model selection."""

import os
from ..config import Config
from ..utils.llm_client import LLMClient

BENCHMARK_ROLES = ("graph", "benchmark", "evaluator")


class BenchmarkRoleRouter:
    """Route benchmark roles to explicit OpenRouter model configuration."""

    def __init__(
        self,
        api_key,
        base_url,
        graph_model,
        benchmark_model,
        evaluator_model,
        evaluator_base_url=None,
        graph_base_url=None,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._evaluator_base_url = evaluator_base_url
        self._graph_base_url = graph_base_url
        self._role_models = {
            "graph": graph_model,
            "benchmark": benchmark_model,
            "evaluator": evaluator_model,
        }
        self._validate()

    @property
    def api_key(self):
        return self._api_key

    @property
    def base_url(self):
        return self._base_url

    @classmethod
    def from_config(cls, config=Config):
        """Build a router from application config values."""
        return cls(
            api_key=getattr(config, "OPENROUTER_API_KEY", None)
            or getattr(config, "LLM_API_KEY", None),
            base_url=getattr(config, "OPENROUTER_BASE_URL", None),
            graph_model=getattr(config, "OPENROUTER_GRAPH_MODEL", None),
            benchmark_model=getattr(config, "OPENROUTER_BENCHMARK_MODEL", None),
            evaluator_model=getattr(config, "OPENROUTER_EVALUATOR_MODEL", None),
            evaluator_base_url=getattr(config, "EVALUATOR_LLM_BASE_URL", None),
            graph_base_url=getattr(config, "GRAPH_LLM_BASE_URL", None),
        )

    def _validate(self) -> None:
        missing = []
        if not self._api_key:
            missing.append(
                "api_key (prefer OPENROUTER_API_KEY, fall back to LLM_API_KEY, or pass api_key explicitly)"
            )
        if not self._base_url:
            missing.append("base_url (set OPENROUTER_BASE_URL, or pass base_url explicitly)")
        for role in BENCHMARK_ROLES:
            if not self._role_models.get(role):
                missing.append(
                    f"{role}_model (set OPENROUTER_{role.upper()}_MODEL, or pass {role}_model explicitly)"
                )
        if missing:
            raise ValueError("Missing benchmark router config: " + "; ".join(missing))

    def model_for(self, role: str) -> str:
        try:
            return self._role_models[role]
        except KeyError as error:
            raise ValueError(f"Unknown benchmark role: {role}") from error

    def client_for(self, role: str) -> LLMClient:
        # Resolve base URL: prioritize role-specific base URLs
        base_url = self._base_url
        if role == "graph" and self._graph_base_url:
            base_url = self._graph_base_url
        elif role == "evaluator" and self._evaluator_base_url:
            base_url = self._evaluator_base_url
        elif role == "benchmark" and getattr(Config, "LLM_BASE_URL", None) and os.environ.get("LLM_BASE_URL"):
            base_url = Config.LLM_BASE_URL
        elif role == "benchmark" and self._evaluator_base_url:
            base_url = self._evaluator_base_url
        elif role == "graph" and self._evaluator_base_url:
            # Backward compatibility fallback
            base_url = self._evaluator_base_url

        return LLMClient(
            api_key=self._api_key,
            base_url=base_url,
            model=self.model_for(role),
        )

