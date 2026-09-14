"""Evaluator workflow for ECN-BENCH benchmark scoring."""

from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping

from .prompt_registry import build_evaluator_system_prompt, load_mcq_prompt_spec
from .role_router import BenchmarkRoleRouter
from ..utils.safe_parser import SafeParser

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
        options: list[str] | None = None,
        micro_questions: list[Dict[str, Any]] | None = None,
        event: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        client = self._router.client_for("evaluator")
        system_prompt = get_evaluator_system_prompt()
        
        # Resolve options: extract from event dict if positional 'options' is missing
        final_options = options
        if final_options is None and event is not None:
            final_options = event.get("options")
        
        if not final_options:
            # Emergency fallback: ensure evaluate never runs without valid keys
            final_options = ["YES", "NO"] if "YES/NO" in event_question.upper() else ["Option A", "Option B"]
        
        # TASK 3: Strict Key Enforcement & Comprehensive Analysis Instruction
        key_instruction = (
            "\n\nCRITICAL INSTRUCTION: The keys in your `probabilities` dictionary MUST EXACTLY MATCH the items in the following options list: "
            f"{', '.join(final_options)}. DO NOT hallucinate, summarize, or invent new keys. "
            "If you invent a key, the system will crash."
            "\n\nProvide a comprehensive analysis including:"
            "\n1. Probabilities for the specified options."
            "\n2. Micro-epistemic mapping for each provided question."
            "\n3. Rubric scores for the defined MCQ dimensions."
        )
        system_prompt += key_instruction

        if micro_questions:
            instruction = (
                "\n\nAs a Report Agent, based strictly on the provided discussion timeline, "
                "answer the following micro-questions to map the swarm's epistemic logic. "
                "Choose the dominant option the swarm believes, and provide a short rationale."
            )
            q_text = ""
            for q in micro_questions:
                q_id = q.get("id", "unknown")
                q_str = q.get("question", "")
                q_options = ", ".join(q.get("options", []))
                q_text += f"\n- {q_id}: {q_str} (Options: {q_options})"
            system_prompt += instruction + q_text

        # requirement 3: Output Schema Update (Refined for TASK 3)
        probabilities_properties = {opt: {"type": "number"} for opt in final_options}
        
        micro_mapping_properties = {}
        if micro_questions:
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

        # ARCHITECTURE v3.10: Comprehensive Hybrid JSON Schema
        json_schema = {
            "name": "evaluator_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "probabilities": {
                        "type": "object", 
                        "properties": probabilities_properties,
                        "required": final_options,
                        "additionalProperties": False
                    },
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
                    }
                },
                "required": [
                    "probabilities",
                    "mcq_dimensions",
                    "validated_scales",
                ],
                "additionalProperties": False,
            },
        }
        
        if micro_questions:
            json_schema["schema"]["properties"]["micro_epistemic_mapping"] = {
                "type": "object",
                "properties": micro_mapping_properties,
                "required": list(micro_mapping_properties.keys()),
                "additionalProperties": False,
            }
            json_schema["schema"]["required"].append("micro_epistemic_mapping")
        else:
            # Still require the key even if empty, to maintain structure consistency
            json_schema["schema"]["properties"]["micro_epistemic_mapping"] = {
                "type": "object",
                "additionalProperties": False
            }
            json_schema["schema"]["required"].append("micro_epistemic_mapping")

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
        current_messages = list(messages)
        last_error = ""
        normalized = None
        normalized_dimensions = None
        normalized_scales = None
        for attempt in range(EVALUATOR_JSON_MAX_ATTEMPTS):
            try:
                temp = 0.0
                if attempt > 0:
                    # Escape greedy decoding loop using temperature jitter and feedback instruction
                    temp = 0.1 if attempt == 1 else 0.2

                    # Add error context to guide recovery
                    error_feedback = (
                        f"Your previous output was invalid or incomplete. "
                        f"Ensure you return a valid JSON object matching the schema. "
                        f"Crucially, verify that the 'probabilities' key and all expected MCQ dimension keys are fully populated. "
                        f"Specifically, the evaluation failed with the following error: {last_error}"
                    )
                    current_messages.append({
                        "role": "user",
                        "content": f"[SYSTEM NOTICE: Retry {attempt}] {error_feedback}"
                    })

                response = client.chat_json(
                    current_messages,
                    temperature=temp,
                    # 4096 was observed too tight for reasoning-heavy models (e.g. OpenRouter
                    # deepseek/deepseek-v4-flash): finish_reason="length" with a null content,
                    # deterministically on every retry since BENCHMARK_MODE pins temperature to
                    # 0.0 regardless of what's requested here. The schema itself is also large
                    # (probabilities + 7 MCQ dimensions x 4 buckets + validated_scales + up to 3
                    # micro-question mappings), leaving little room for any reasoning tokens. Set
                    # generously high (this evaluator's model has a 1M-token context window, so
                    # this is nowhere near the input-side ceiling) -- the retry loop's own
                    # completeness checks, not this budget, are what should decide success.
                    max_tokens=65536,
                    repair_truncated_json=True,
                    json_schema=json_schema,
                )

                # Check response format completeness to determine if we should retry
                if not isinstance(response, dict):
                    raise ValueError("Evaluator response is not a dictionary")

                probs = response.get("probabilities", {})
                mcq = response.get("mcq_dimensions", {})

                if not isinstance(probs, dict) or not probs or not any(opt in probs for opt in final_options):
                    raise ValueError("Evaluator probabilities mapping is empty or invalid")

                if not isinstance(mcq, dict) or not mcq or len(mcq) < len(MCQ_DIMENSION_KEYS):
                    raise ValueError("Evaluator mcq_dimensions mapping is incomplete")

                # BUGFIX: this check was previously absent, so an incomplete/empty
                # micro_epistemic_mapping was silently accepted as "complete" and never
                # retried -- it was then backfilled with N/A/"Missing in LLM response" by
                # _validate_micro_mapping() with no error ever raised or surfaced. Require the
                # same completeness (all requested question ids present) that the schema asks for.
                if micro_questions:
                    micro_map = response.get("micro_epistemic_mapping", {})
                    expected_ids = {q.get("id") for q in micro_questions if q.get("id")}
                    present_ids = set(micro_map.keys()) if isinstance(micro_map, dict) else set()
                    if not isinstance(micro_map, dict) or not expected_ids.issubset(present_ids):
                        raise ValueError(
                            f"Evaluator micro_epistemic_mapping is incomplete: "
                            f"missing {sorted(expected_ids - present_ids)}"
                        )

                # BUGFIX: normalization used to happen *after* this loop, so a structurally
                # "complete" response (right keys present) with an invalid value inside it (a
                # non-numeric probability, a negative score, a NaN) would raise from
                # _normalize_probabilities()/_normalize_mcq_dimensions() on the very first
                # attempt, bypassing the retry-with-feedback mechanism entirely. Validating here,
                # inside the loop, means value-level errors get the same retry treatment as
                # structural ones, and a successful attempt leaves normalized results ready to use.
                normalized = self._normalize_probabilities(probs, final_options)
                normalized_dimensions = self._normalize_mcq_dimensions(mcq)
                normalized_scales = self._normalize_validated_scales(
                    response.get("validated_scales"), normalized_dimensions
                )

                # If everything is complete and valid, we succeed and break the retry loop
                break
            except Exception as error:
                last_error = str(error)
                if attempt == EVALUATOR_JSON_MAX_ATTEMPTS - 1:
                    # BUGFIX: this used to `break` here and let execution fall through to
                    # normalization with a known-incomplete `response`, which
                    # _normalize_probabilities()/_normalize_mcq_dimensions() would then paper
                    # over with defaults (uniform probabilities, 0.25-per-bucket dimensions)
                    # with no exception raised and no fallback flag set anywhere -- structurally
                    # indistinguishable from a real evaluator answer. Re-raise instead: the
                    # caller (run_ecnbench_protocol.py) already has a defined, visible fallback
                    # path for evaluator errors (evaluator_fallback_used/evaluator_fallback_reason),
                    # and that is where an unrecoverable failure belongs, not a silent default here.
                    raise
                time.sleep(0.2 * (attempt + 1))

        result = dict(response) if isinstance(response, dict) else {}
        result["probabilities"] = normalized
        result["normalized_probabilities"] = normalized
        result["mcq_dimensions"] = normalized_dimensions
        result["validated_scales"] = normalized_scales

        if micro_questions:
            # Ensure micro_epistemic_mapping always exists and is a dict
            mapping_data = result.get("micro_epistemic_mapping", {})
            result["micro_epistemic_mapping"] = self._validate_micro_mapping(
                mapping_data, micro_questions
            )
        else:
            result["micro_epistemic_mapping"] = {}

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
                validated[q_id] = {"dominant_tag": "N/A", "short_rationale": "Missing in LLM response"}
                continue
            
            dominant_tag = str(q_data.get("dominant_tag", "N/A"))
            short_rationale = str(q_data.get("short_rationale", "No rationale provided"))
            validated[q_id] = {
                "dominant_tag": dominant_tag,
                "short_rationale": short_rationale
            }
        return validated

    def _normalize_probabilities(self, probabilities: Any, fallback_options: list[str]) -> Dict[str, float]:
        # Restored strict validation (an earlier revision of this method silently coerced
        # non-numeric/negative/non-finite values to 0.0 and defaulted an all-zero response to a
        # uniform distribution -- indistinguishable from a real, evenly-weighted answer). Option
        # matching stays fuzzy (case/whitespace-insensitive, then substring) since that is a
        # genuine robustness need, not error-masking: a model naming an option slightly
        # differently from the exact seed-context string is not a data-quality defect.
        if not isinstance(probabilities, Mapping) or not probabilities:
            raise ValueError("Evaluator response must include a non-empty probabilities mapping")

        normalized: Dict[str, float] = {opt: 0.0 for opt in fallback_options}
        matched_any = False
        for label, value in probabilities.items():
            if not isinstance(label, str) or not label:
                raise ValueError(f"Evaluator probabilities must use non-empty string labels, got {label!r}")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"Invalid probability for outcome {label!r}: {value!r}")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"Probability for outcome {label!r} must be finite: {value!r}")
            if numeric < 0.0:
                raise ValueError(f"Probability for outcome {label!r} must be non-negative: {value!r}")

            # Check for matching option key (case-insensitive strip match)
            matched_opt = None
            for opt in fallback_options:
                if opt.strip().upper() == label.strip().upper():
                    matched_opt = opt
                    break
            if matched_opt is None:
                # Fuzzy match fallback
                for opt in fallback_options:
                    if label.strip().upper() in opt.strip().upper() or opt.strip().upper() in label.strip().upper():
                        matched_opt = opt
                        break
            if matched_opt is not None:
                normalized[matched_opt] = normalized.get(matched_opt, 0.0) + numeric
                matched_any = True

        total = sum(normalized.values())
        if not matched_any or total <= 0.0:
            raise ValueError(
                "Evaluator probabilities must have positive total mass over the expected options "
                f"{fallback_options}, got {dict(probabilities)!r}"
            )

        return {label: value / total for label, value in normalized.items()}

    def _normalize_mcq_dimensions(self, dimensions: Any) -> Dict[str, Dict[str, float]]:
        # Restored strict validation of *content* (a missing dimension, a bucket set missing a
        # key, or an all-zero/non-numeric bucket now raises) while keeping the *naming* leniency
        # (case/punctuation-insensitive key matching, and a bare bucket-label string as shorthand
        # for a one-hot mapping) that a prior revision added. An earlier version of this method
        # defaulted every one of these cases to a uniform {very_low..very_high: 0.25} placeholder
        # with no error raised, which is indistinguishable in the released data from a genuine
        # "the swarm was maximally uncertain on this dimension" reading and is exactly the
        # silent-placeholder pattern this benchmark's own audit flags elsewhere (JSD telemetry,
        # micro_epistemic_mapping).
        if not isinstance(dimensions, Mapping):
            raise ValueError("Evaluator response must include mcq_dimensions mapping")

        # Fuzzy dimension key matching to handle variations like prediction-accuracy or predictionaccuracy
        dimension_map = {d.replace("_", "").replace("-", "").casefold(): d for d in MCQ_DIMENSION_KEYS}

        raw_dimensions: Dict[str, Any] = {}
        for raw_k, raw_v in dimensions.items():
            if not isinstance(raw_k, str):
                continue
            clean_k = raw_k.replace("_", "").replace("-", "").casefold()
            if clean_k in dimension_map:
                canonical_k = dimension_map[clean_k]
                raw_dimensions[canonical_k] = raw_v

        missing_dimensions = [d for d in MCQ_DIMENSION_KEYS if d not in raw_dimensions]
        if missing_dimensions:
            raise ValueError(
                f"Evaluator response mcq_dimensions is missing required dimensions: {missing_dimensions}"
            )

        bucket_map = {b.replace("_", "").replace("-", "").casefold(): b for b in MCQ_BUCKET_KEYS}
        normalized: Dict[str, Dict[str, float]] = {}
        for dimension in MCQ_DIMENSION_KEYS:
            buckets = raw_dimensions[dimension]

            if isinstance(buckets, str):
                # A bare label is shorthand for a one-hot mapping -- a legitimate alternate
                # format, not an error, provided it names one of the four known buckets.
                bucket_label_clean = buckets.strip().replace("_", "").replace("-", "").casefold()
                if bucket_label_clean not in bucket_map:
                    raise ValueError(
                        f"mcq_dimensions.{dimension} label {buckets!r} is not one of {MCQ_BUCKET_KEYS}"
                    )
                normalized[dimension] = _one_hot_bucket_mapping(
                    bucket_map[bucket_label_clean],
                    context=f"mcq_dimensions.{dimension}",
                )
                continue

            if not isinstance(buckets, Mapping):
                raise ValueError(
                    f"mcq_dimensions.{dimension} must be a bucket mapping or bucket label string, "
                    f"got {type(buckets).__name__}"
                )

            # Standardize bucket mapping keys, stripping whitespace/casing/punctuation
            raw_buckets: Dict[str, Any] = {}
            for bk, bv in buckets.items():
                if not isinstance(bk, str):
                    continue
                clean_bk = bk.replace("_", "").replace("-", "").casefold()
                if clean_bk in bucket_map:
                    raw_buckets[bucket_map[clean_bk]] = bv

            missing_buckets = [b for b in MCQ_BUCKET_KEYS if b not in raw_buckets]
            if missing_buckets:
                raise ValueError(f"mcq_dimensions.{dimension} is missing bucket keys: {missing_buckets}")

            hydrated_buckets: Dict[str, float] = {}
            for b in MCQ_BUCKET_KEYS:
                val = raw_buckets[b]
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    raise ValueError(f"mcq_dimensions.{dimension}.{b} must be numeric, got {val!r}")
                numeric = float(val)
                if not math.isfinite(numeric) or numeric < 0.0:
                    raise ValueError(f"mcq_dimensions.{dimension}.{b} must be finite and non-negative: {val!r}")
                hydrated_buckets[b] = numeric

            total_mass = sum(hydrated_buckets.values())
            if total_mass <= 0.0:
                raise ValueError(f"mcq_dimensions.{dimension} bucket values must have positive total mass")

            normalized[dimension] = {b: v / total_mass for b, v in hydrated_buckets.items()}

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
