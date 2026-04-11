"""Evaluator workflow for ECN-BENCH benchmark scoring."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping

from .role_router import BenchmarkRoleRouter


class ProbabilityEvaluator:
    """Query the evaluator role and normalize outcome probabilities."""

    def __init__(self, router: BenchmarkRoleRouter):
        self._router = router

    def evaluate(self, event_question: str, condition: str, evidence_text: str) -> Dict[str, Any]:
        client = self._router.client_for("evaluator")
        response = client.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an ECN-BENCH evaluator. Return a JSON object with a "
                        "'probabilities' mapping from outcome label to numeric probability."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {event_question}\n"
                        f"Condition: {condition}\n"
                        f"Evidence: {evidence_text}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=512,
        )

        probabilities = response.get("probabilities") if isinstance(response, dict) else None
        normalized = self._normalize_probabilities(probabilities)

        result = dict(response) if isinstance(response, dict) else {}
        result["probabilities"] = normalized
        result["normalized_probabilities"] = normalized
        return result

    def _normalize_probabilities(self, probabilities: Any) -> Dict[str, float]:
        if not isinstance(probabilities, Mapping) or not probabilities:
            raise ValueError("Evaluator response must include a non-empty probabilities mapping")

        normalized: Dict[str, float] = {}
        total = 0.0
        for label, value in probabilities.items():
            if not isinstance(label, str) or not label:
                raise ValueError("Evaluator probabilities must use non-empty string labels")
            if not isinstance(value, (int, float)):
                raise ValueError(f"Invalid probability for outcome {label!r}: {value!r}")
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < 0.0:
                raise ValueError(
                    f"Invalid probability for outcome {label!r}: {value!r} (must be finite and non-negative)"
                )
            normalized[label] = numeric
            total += numeric

        if total <= 0.0:
            raise ValueError("Evaluator probabilities must have positive total mass")

        return {label: value / total for label, value in normalized.items()}
