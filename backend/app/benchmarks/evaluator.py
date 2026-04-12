"""Evaluator workflow for ECN-BENCH benchmark scoring."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping

from .role_router import BenchmarkRoleRouter

MCQ_DIMENSION_KEYS = (
    "prediction_accuracy",
    "polarization",
    "herd_effect",
    "deliberation_quality",
    "susceptibility",
    "convergence",
    "information_diversity",
)
MCQ_BUCKET_KEYS = ("very_low", "low", "high", "very_high")
VALIDATED_SCALES_SCHEMA_VERSION = "v1"


def _normalize_probability_mapping(mapping: Any, context: str) -> Dict[str, float]:
    if not isinstance(mapping, Mapping) or not mapping:
        raise ValueError(f"{context} must be a non-empty mapping")

    normalized: Dict[str, float] = {}
    total = 0.0
    for label, value in mapping.items():
        if not isinstance(label, str) or not label:
            raise ValueError(f"{context} must use non-empty string keys")
        if not isinstance(value, (int, float)):
            raise ValueError(f"{context} has invalid value for {label!r}: {value!r}")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0.0:
            raise ValueError(
                f"{context} has invalid value for {label!r}: {value!r} (must be finite and non-negative)"
            )
        normalized[label] = numeric
        total += numeric

    if total <= 0.0:
        raise ValueError(f"{context} must have positive total mass")

    return {label: value / total for label, value in normalized.items()}


def _validate_numeric_scores_mapping(mapping: Any, context: str) -> Dict[str, float]:
    if not isinstance(mapping, Mapping) or not mapping:
        raise ValueError(f"{context} must be a non-empty mapping")

    validated: Dict[str, float] = {}
    for label, value in mapping.items():
        if not isinstance(label, str) or not label:
            raise ValueError(f"{context} must use non-empty string keys")
        if not isinstance(value, (int, float)):
            raise ValueError(f"{context} has invalid value for {label!r}: {value!r}")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{context} has invalid value for {label!r}: {value!r} (must be finite)")
        validated[label] = numeric

    return validated


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
        mcq_dimensions = response.get("mcq_dimensions") if isinstance(response, dict) else None
        validated_scales = response.get("validated_scales") if isinstance(response, dict) else None
        normalized = self._normalize_probabilities(probabilities)
        normalized_dimensions = self._normalize_mcq_dimensions(mcq_dimensions)
        normalized_scales = self._normalize_validated_scales(validated_scales)

        result = dict(response) if isinstance(response, dict) else {}
        result["probabilities"] = normalized
        result["normalized_probabilities"] = normalized
        result["mcq_dimensions"] = normalized_dimensions
        result["validated_scales"] = normalized_scales
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

    def _normalize_mcq_dimensions(self, dimensions: Any) -> Dict[str, Dict[str, float]]:
        if not isinstance(dimensions, Mapping):
            raise ValueError("Evaluator response must include mcq_dimensions mapping")

        expected_dimensions = set(MCQ_DIMENSION_KEYS)
        provided_dimensions = set(dimensions.keys())
        if provided_dimensions != expected_dimensions:
            raise ValueError("Evaluator response mcq_dimensions must include all required dimensions")

        normalized: Dict[str, Dict[str, float]] = {}
        for dimension in MCQ_DIMENSION_KEYS:
            buckets = dimensions.get(dimension)
            if not isinstance(buckets, Mapping):
                raise ValueError("Evaluator response mcq_dimensions must map to bucket mappings")
            bucket_keys = set(buckets.keys())
            if bucket_keys != set(MCQ_BUCKET_KEYS):
                raise ValueError("Evaluator response mcq_dimensions must include all bucket keys")
            normalized[dimension] = _normalize_probability_mapping(
                buckets,
                f"mcq_dimensions.{dimension}",
            )

        return normalized

    def _normalize_validated_scales(self, validated_scales: Any) -> Dict[str, Any]:
        if not isinstance(validated_scales, Mapping):
            raise ValueError("Evaluator response must include validated_scales mapping")

        schema_version = validated_scales.get("schema_version")
        if not isinstance(schema_version, str) or not schema_version:
            raise ValueError("validated_scales.schema_version must be a non-empty string")
        if schema_version != VALIDATED_SCALES_SCHEMA_VERSION:
            raise ValueError(
                f"validated_scales.schema_version must be {VALIDATED_SCALES_SCHEMA_VERSION!r}"
            )

        scores = _validate_numeric_scores_mapping(
            validated_scales.get("scores"),
            "validated_scales.scores",
        )

        return {"schema_version": schema_version, "scores": scores}
