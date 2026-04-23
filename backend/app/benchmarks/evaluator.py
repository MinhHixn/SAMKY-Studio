"""Evaluator workflow for ECN-BENCH benchmark scoring."""

from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping

from .prompt_registry import build_evaluator_system_prompt, load_mcq_prompt_spec
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
MCQ_BUCKET_SCORE_ANCHORS = {
    "very_low": 0.0,
    "low": 1.0 / 3.0,
    "high": 2.0 / 3.0,
    "very_high": 1.0,
}
MCQ_DIMENSION_WEIGHTS = {
    "prediction_accuracy": 0.25,
    "polarization": 0.125,
    "herd_effect": 0.125,
    "deliberation_quality": 0.125,
    "susceptibility": 0.125,
    "convergence": 0.125,
    "information_diversity": 0.125,
}
CANONICAL_VALIDATED_SCALE_KEYS = (
    "prediction_accuracy_score",
    "polarization_score",
    "herd_effect_score",
    "deliberation_quality_score",
    "susceptibility_score",
    "convergence_score",
    "information_diversity_score",
    "weighted_rubric_score",
)
# Phase 1 MVP uses placeholder weights (prediction_accuracy=0.25, others=0.125)
# for pipeline validation. Empirical weight optimization will be applied to pilot
# data prior to Phase 2 per KB §2.9.
VALIDATED_SCALES_SCHEMA_VERSION = "v1"
INVALID_JSON_ERROR_PREFIX = "Invalid JSON format from LLM:"
EVALUATOR_JSON_MAX_ATTEMPTS = 3
_EVALUATOR_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "ecnbench_mcq_v1.yaml"


@lru_cache(maxsize=1)
def get_evaluator_system_prompt() -> str:
    try:
        return build_evaluator_system_prompt(load_mcq_prompt_spec(_EVALUATOR_PROMPT_PATH))
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load evaluator prompt contract from {_EVALUATOR_PROMPT_PATH}"
        ) from exc


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


def _validate_numeric_scores_mapping(
    mapping: Any,
    context: str,
    *,
    allow_empty: bool = False,
) -> Dict[str, float]:
    if not isinstance(mapping, Mapping):
        requirement = "a mapping" if allow_empty else "a non-empty mapping"
        raise ValueError(f"{context} must be {requirement}")
    if not mapping and not allow_empty:
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


def _compute_canonical_validated_scales(mcq_dimensions: Mapping[str, Mapping[str, float]]) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for dimension in MCQ_DIMENSION_KEYS:
        buckets = mcq_dimensions[dimension]
        value = sum(
            float(buckets[bucket]) * float(MCQ_BUCKET_SCORE_ANCHORS[bucket])
            for bucket in MCQ_BUCKET_KEYS
        )
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise ValueError(f"Computed canonical scale out of range for {dimension!r}")
        scores[f"{dimension}_score"] = round(value, 6)

    weighted = sum(
        scores[f"{dimension}_score"] * float(MCQ_DIMENSION_WEIGHTS[dimension])
        for dimension in MCQ_DIMENSION_KEYS
    )
    if not math.isfinite(weighted) or weighted < 0.0 or weighted > 1.0:
        raise ValueError("Computed canonical weighted_rubric_score out of range")
    scores["weighted_rubric_score"] = round(weighted, 6)
    return scores


def _one_hot_bucket_mapping(bucket_label: str, *, context: str) -> Dict[str, float]:
    normalized_label = bucket_label.strip()
    if normalized_label not in MCQ_BUCKET_KEYS:
        allowed = ", ".join(MCQ_BUCKET_KEYS)
        raise ValueError(f"{context} label must be one of: {allowed}")
    return {bucket: (1.0 if bucket == normalized_label else 0.0) for bucket in MCQ_BUCKET_KEYS}


class ProbabilityEvaluator:
    """Query the evaluator role and normalize outcome probabilities."""

    def __init__(self, router: BenchmarkRoleRouter):
        self._router = router

    def evaluate(
        self,
        event_question: str,
        condition: str,
        evidence_text: str,
        micro_questions: list[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        client = self._router.client_for("evaluator")
        system_prompt = get_evaluator_system_prompt()
        json_schema: Dict[str, Any] | None = None

        if micro_questions:
            # requirement 2: Dynamic Prompt Injection
            instruction = (
                "\n\nAs a Report Agent, based strictly on the provided discussion timeline, "
                "answer the following 3 micro-questions to map the swarm's epistemic logic. "
                "Choose the dominant option the swarm believes, and provide a short rationale."
            )
            q_text = ""
            for q in micro_questions:
                q_id = q.get("id", "unknown")
                q_str = q.get("question", "")
                q_options = ", ".join(q.get("options", []))
                q_text += f"\n- {q_id}: {q_str} (Options: {q_options})"
            system_prompt += instruction + q_text

            # requirement 3: Output Schema Update
            micro_mapping_properties = {}
            for q in micro_questions:
                q_id = q.get("id")
                if q_id:
                    micro_mapping_properties[q_id] = {
                        "type": "object",
                        "properties": {
                            "dominant_tag": {"type": "string"},
                            "short_rationale": {"type": "string"},
                        },
                        "required": ["dominant_tag", "short_rationale"],
                        "additionalProperties": False,
                    }

            # Build full JSON schema for strict validation if micro_questions are present
            # This incorporates existing keys (probabilities, mcq_dimensions, validated_scales)
            json_schema = {
                "name": "evaluator_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "probabilities": {"type": "object", "additionalProperties": {"type": "number"}},
                        "mcq_dimensions": {
                            "type": "object",
                            "properties": {
                                k: {
                                    "type": "object",
                                    "properties": {
                                        b: {"type": "number"} for b in MCQ_BUCKET_KEYS
                                    },
                                    "required": list(MCQ_BUCKET_KEYS),
                                    "additionalProperties": False,
                                }
                                for k in MCQ_DIMENSION_KEYS
                            },
                            "required": list(MCQ_DIMENSION_KEYS),
                            "additionalProperties": False,
                        },
                        "validated_scales": {
                            "type": "object",
                            "properties": {
                                "schema_version": {"type": "string"},
                                "scores": {"type": "object", "additionalProperties": {"type": "number"}},
                            },
                            "required": ["schema_version", "scores"],
                            "additionalProperties": False,
                        },
                        "micro_epistemic_mapping": {
                            "type": "object",
                            "properties": micro_mapping_properties,
                            "required": list(micro_mapping_properties.keys()),
                            "additionalProperties": False,
                        },
                    },
                    "required": [
                        "probabilities",
                        "mcq_dimensions",
                        "validated_scales",
                        "micro_epistemic_mapping",
                    ],
                    "additionalProperties": False,
                },
            }

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": (
                    f"Question: {event_question}\n"
                    f"Condition: {condition}\n"
                    f"Evidence: {evidence_text}"
                ),
            },
        ]
        response = None
        for attempt in range(EVALUATOR_JSON_MAX_ATTEMPTS):
            try:
                response = client.chat_json(
                    messages,
                    temperature=0.0,
                    max_tokens=1024 if micro_questions else 512,
                    repair_truncated_json=True,
                    json_schema=json_schema,
                )
                break
            except ValueError as error:
                if not str(error).startswith(INVALID_JSON_ERROR_PREFIX):
                    raise
                if attempt == EVALUATOR_JSON_MAX_ATTEMPTS - 1:
                    raise
                time.sleep(0.1 * (attempt + 1))

        probabilities = response.get("probabilities") if isinstance(response, dict) else None
        mcq_dimensions = response.get("mcq_dimensions") if isinstance(response, dict) else None
        validated_scales = response.get("validated_scales") if isinstance(response, dict) else None
        normalized = self._normalize_probabilities(probabilities)
        normalized_dimensions = self._normalize_mcq_dimensions(mcq_dimensions)
        normalized_scales = self._normalize_validated_scales(validated_scales, normalized_dimensions)

        result = dict(response) if isinstance(response, dict) else {}
        result["probabilities"] = normalized
        result["normalized_probabilities"] = normalized
        result["mcq_dimensions"] = normalized_dimensions
        result["validated_scales"] = normalized_scales

        # requirement 3: Epistemic mapping persistence
        if micro_questions and "micro_epistemic_mapping" in result:
            result["micro_epistemic_mapping"] = self._validate_micro_mapping(
                result["micro_epistemic_mapping"], micro_questions
            )

        return result

    def _validate_micro_mapping(
        self, mapping: Any, micro_questions: list[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not isinstance(mapping, Mapping):
            raise ValueError("micro_epistemic_mapping must be a mapping")
        
        validated = {}
        for q in micro_questions:
            q_id = q.get("id")
            if not q_id:
                continue
            q_data = mapping.get(q_id)
            if not isinstance(q_data, Mapping):
                # Fallback to placeholder if missing to avoid breaking macro metrics
                validated[q_id] = {"dominant_tag": "N/A", "short_rationale": "Missing in LLM response"}
                continue
            
            dominant_tag = str(q_data.get("dominant_tag", "N/A"))
            short_rationale = str(q_data.get("short_rationale", "No rationale provided"))
            validated[q_id] = {
                "dominant_tag": dominant_tag,
                "short_rationale": short_rationale
            }
        return validated

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
            num_keys = len(normalized)
            if num_keys == 0:
                raise ValueError("Evaluator probabilities must have positive total mass")
            return {label: 1.0 / num_keys for label in normalized.keys()}

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
            if isinstance(buckets, Mapping):
                bucket_keys = set(buckets.keys())
                if bucket_keys != set(MCQ_BUCKET_KEYS):
                    raise ValueError("Evaluator response mcq_dimensions must include all bucket keys")
                normalized[dimension] = _normalize_probability_mapping(
                    buckets,
                    f"mcq_dimensions.{dimension}",
                )
                continue
            if isinstance(buckets, str):
                normalized[dimension] = _one_hot_bucket_mapping(
                    buckets,
                    context=f"mcq_dimensions.{dimension}",
                )
                continue
            raise ValueError(
                "Evaluator response mcq_dimensions must map dimensions to bucket mappings or bucket labels"
            )

        return normalized

    def _normalize_validated_scales(
        self,
        validated_scales: Any,
        mcq_dimensions: Mapping[str, Mapping[str, float]],
    ) -> Dict[str, Any]:
        canonical_scores = _compute_canonical_validated_scales(mcq_dimensions)
        if set(canonical_scores.keys()) != set(CANONICAL_VALIDATED_SCALE_KEYS):
            raise ValueError("Canonical validated_scales key set mismatch")
        return {"schema_version": VALIDATED_SCALES_SCHEMA_VERSION, "scores": canonical_scores}
