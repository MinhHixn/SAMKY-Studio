"""Strict role-based router for benchmark model selection."""

from ..config import Config
from ..utils.llm_client import LLMClient

BENCHMARK_ROLES = ("graph", "benchmark", "evaluator")


class BenchmarkRoleRouter:
    """Route benchmark roles to explicit OpenRouter model configuration."""

    def __init__(self, config=Config):
        self._api_key = getattr(config, "OPENROUTER_API_KEY", None) or getattr(config, "LLM_API_KEY", None)
        self._base_url = getattr(config, "OPENROUTER_BASE_URL", None)
        self._role_models = {
            "graph": getattr(config, "OPENROUTER_GRAPH_MODEL", None),
            "benchmark": getattr(config, "OPENROUTER_BENCHMARK_MODEL", None),
            "evaluator": getattr(config, "OPENROUTER_EVALUATOR_MODEL", None),
        }
        self._validate()

    def _validate(self) -> None:
        missing = []
        if not self._api_key:
            missing.append("OPENROUTER_API_KEY")
        if not self._base_url:
            missing.append("OPENROUTER_BASE_URL")
        for role in BENCHMARK_ROLES:
            if not self._role_models.get(role):
                missing.append(f"OPENROUTER_{role.upper()}_MODEL")
        if missing:
            raise ValueError("Missing benchmark router config: " + ", ".join(missing))

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

