"""Strict role-based router for benchmark model selection."""

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
    ):
        self._api_key = api_key
        self._base_url = base_url
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
        return LLMClient(
            api_key=self._api_key,
            base_url=self._base_url,
            model=self.model_for(role),
        )

