"""Scoring utilities for ECN-BENCH benchmark outputs."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping

from .evaluator import (
    MCQ_BUCKET_KEYS,
    MCQ_BUCKET_SCORE_ANCHORS,
    MCQ_DIMENSION_KEYS,
    MCQ_DIMENSION_WEIGHTS,
    VALIDATED_SCALES_SCHEMA_VERSION,
    _validate_numeric_scores_mapping,
)

# Phase 1 MVP uses placeholder weights (prediction_accuracy=0.25, others=0.125)
# for pipeline validation. Empirical weight optimization will be applied to pilot
# data prior to Phase 2 per KB §2.9.
RUBRIC_PLACEHOLDER_WEIGHTS: Dict[str, float] = dict(MCQ_DIMENSION_WEIGHTS)


def brier_score(probabilities: Dict[str, float], truth: str) -> float:
    import re
    
    def normalize(s: str) -> str:
        s = str(s).replace('_', ' ').replace('-', ' ').strip().upper()
        return ' '.join(s.split())

    truth_norm = normalize(truth)
    
    # Create normalized probs
    normalized_probs = {}
    for k, v in probabilities.items():
        k_norm = normalize(k)
        normalized_probs[k_norm] = normalized_probs.get(k_norm, 0.0) + float(v)
        
    # If the truth_norm is not in normalized_probs, try to resolve it (e.g. '4' vs 'Category 4')
    if truth_norm not in normalized_probs:
        truth_digits = re.findall(r'\d+', truth_norm)
        if truth_digits:
            for digit in truth_digits:
                if digit in normalized_probs:
                    normalized_probs[truth_norm] = normalized_probs.pop(digit)
                    break
                for k in list(normalized_probs.keys()):
                    k_digits = re.findall(r'\d+', k)
                    if k_digits and digit in k_digits:
                        normalized_probs[truth_norm] = normalized_probs.pop(k)
                        break

    labels = set(normalized_probs.keys())
    labels.add(truth_norm)
    
    score = 0.0
    for outcome in labels:
        probability = normalized_probs.get(outcome, 0.0)
        observed = 1.0 if outcome == truth_norm else 0.0
        score += (probability - observed) ** 2
    return score


def summarize_condition_scores(rows: List[Dict]) -> Dict:
    bucket = defaultdict(list)
    for row in rows:
        bucket[row["condition"]].append(float(row["brier"]))

    means = {condition: round(sum(values) / len(values), 6) for condition, values in bucket.items() if values}

    return {
        "condition_mean_brier": means,
        "lift": {
            "A_to_B": round(means.get("A", 0.0) - means.get("B", 0.0), 6),
            "A_to_C": round(means.get("A", 0.0) - means.get("C", 0.0), 6),
            "B_to_C": round(means.get("B", 0.0) - means.get("C", 0.0), 6),
        },
    }


def _finite_float_or_none(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return numeric


def _is_completed_row(row: Dict) -> bool:
    status = row.get("simulation_status")
    if isinstance(status, str):
        return status == "completed"
    return bool(row.get("full_simulation_completed"))


def _aggregate_metric(rows: List[Dict], metric_getter: Any) -> Dict[str, Any]:
    per_condition: Dict[str, List[float]] = {"A": [], "B": [], "C": []}
    overall_values: List[float] = []
    for row in rows:
        if not _is_completed_row(row):
            continue
        value = metric_getter(row)
        if value is None:
            continue
        numeric = _finite_float_or_none(value)
        if numeric is None:
            continue
        overall_values.append(numeric)
        condition = str(row.get("condition", ""))
        if condition in per_condition:
            per_condition[condition].append(numeric)

    by_condition = {
        condition: round(sum(values) / len(values), 6) if values else 0.0
        for condition, values in per_condition.items()
    }
    overall = round(sum(overall_values) / len(overall_values), 6) if overall_values else 0.0
    return {
        "overall": overall,
        "by_condition": by_condition,
        "delta": {
            "A_to_B": round(by_condition["B"] - by_condition["A"], 6),
            "A_to_C": round(by_condition["C"] - by_condition["A"], 6),
            "B_to_C": round(by_condition["C"] - by_condition["B"], 6),
        },
    }


def summarize_directional_accuracy(rows: List[Dict]) -> Dict:
    def _metric_getter(row: Dict) -> float | None:
        directional_accuracy = _finite_float_or_none(row.get("directional_accuracy"))
        if directional_accuracy is not None:
            return directional_accuracy
        directional_correct = row.get("directional_correct")
        if directional_correct in (0, 1):
            return float(directional_correct)
        return None

    return _aggregate_metric(rows, _metric_getter)


def summarize_weighted_rubric_score(rows: List[Dict]) -> Dict:
    return _aggregate_metric(rows, lambda row: row.get("weighted_rubric_score"))


def compute_composite_score(
    dimension_scores: Mapping[str, Any],
    weights: Mapping[str, Any],
    noisy_dimensions: Iterable[str] | None = None,
) -> Dict[str, Any]:
    noisy_set = {str(dimension) for dimension in (noisy_dimensions or []) if str(dimension)}

    included_dimensions: List[str] = []
    excluded_dimensions: List[str] = []
    stable_scores: Dict[str, float] = {}
    stable_weights: Dict[str, float] = {}

    for dimension, weight in weights.items():
        dimension_key = str(dimension)
        if dimension_key in noisy_set:
            excluded_dimensions.append(dimension_key)
            continue

        numeric_weight = _finite_float_or_none(weight)
        if numeric_weight is None or numeric_weight < 0.0:
            continue
        raw_score = dimension_scores.get(dimension_key)
        score = _finite_float_or_none(raw_score)
        if score is None:
            if dimension_key in dimension_scores:
                continue
            score = 0.0

        included_dimensions.append(dimension_key)
        stable_scores[dimension_key] = score
        stable_weights[dimension_key] = numeric_weight

    if not included_dimensions:
        raise ValueError("No stable dimensions remain for composite score")

    total_weight = sum(stable_weights.values())
    if total_weight <= 0.0:
        raise ValueError("No stable dimensions remain for composite score")

    renormalized_weights = {
        dimension: stable_weights[dimension] / total_weight for dimension in included_dimensions
    }
    composite_score = sum(
        stable_scores[dimension] * renormalized_weights[dimension] for dimension in included_dimensions
    )

    return {
        "composite_score": round(composite_score, 6),
        "renormalized_weights": renormalized_weights,
        "excluded_dimensions": excluded_dimensions,
        "included_dimensions": included_dimensions,
    }


def summarize_yes_probability(rows: List[Dict]) -> Dict:
    return _aggregate_metric(rows, lambda row: row.get("yes_probability"))


def summarize_strict_contract(rows: List[Dict]) -> Dict[str, Any]:
    completed_rows = [row for row in rows if _is_completed_row(row)]
    strict_contract_completed_count = 0
    legacy_contract_completed_count = 0
    unknown_contract_completed_count = 0

    for row in completed_rows:
        strict_contract = row.get("strict_contract")
        if strict_contract is True:
            strict_contract_completed_count += 1
        elif strict_contract is False:
            legacy_contract_completed_count += 1
        else:
            unknown_contract_completed_count += 1

    completed_count = len(completed_rows)
    strict_contract_ratio = (
        round(strict_contract_completed_count / completed_count, 6) if completed_count else 0.0
    )
    return {
        "strict_contract_completed_count": strict_contract_completed_count,
        "legacy_contract_completed_count": legacy_contract_completed_count,
        "unknown_contract_completed_count": unknown_contract_completed_count,
        "strict_contract_ratio": strict_contract_ratio,
    }


def compute_weighted_rubric_score(mcq_dimensions: Mapping[str, Any] | None) -> float | None:
    if not isinstance(mcq_dimensions, Mapping):
        return None

    weighted_sum = 0.0
    for dimension, weight in RUBRIC_PLACEHOLDER_WEIGHTS.items():
        buckets = mcq_dimensions.get(dimension)
        if not isinstance(buckets, Mapping):
            return None

        bucket_values: Dict[str, float] = {}
        for bucket_key in MCQ_BUCKET_KEYS:
            numeric = _finite_float_or_none(buckets.get(bucket_key))
            if numeric is None or numeric < 0.0:
                return None
            bucket_values[bucket_key] = numeric

        total = sum(bucket_values.values())
        if total <= 0.0:
            return None
        normalized_score = sum(
            (bucket_values[bucket_key] / total) * float(MCQ_BUCKET_SCORE_ANCHORS[bucket_key])
            for bucket_key in MCQ_BUCKET_KEYS
        )
        weighted_sum += weight * normalized_score

    return round(weighted_sum, 6)


def summarize_rubric_artifacts(rows: List[Dict]) -> Dict:
    completed_rows = [row for row in rows if _is_completed_row(row)]
    validated_scale_keys = set()
    rubric_ready_count = 0

    for row in completed_rows:
        mcq_dimensions = row.get("mcq_dimensions")
        validated_scales = row.get("validated_scales")
        if not _is_valid_rubric_artifact(mcq_dimensions, validated_scales):
            continue
        rubric_ready_count += 1

        scores = validated_scales.get("scores")
        if isinstance(scores, dict):
            validated_scale_keys.update(str(key) for key in scores.keys())

    return {
        "rubric_completed_count": rubric_ready_count,
        "rubric_missing_count": len(completed_rows) - rubric_ready_count,
        "validated_scale_keys": sorted(validated_scale_keys),
    }


def _is_valid_rubric_artifact(mcq_dimensions: object, validated_scales: object) -> bool:
    if not isinstance(mcq_dimensions, dict) or not isinstance(validated_scales, dict):
        return False

    if set(mcq_dimensions.keys()) != set(MCQ_DIMENSION_KEYS):
        return False

    expected_buckets = set(MCQ_BUCKET_KEYS)
    for dimension in MCQ_DIMENSION_KEYS:
        buckets = mcq_dimensions.get(dimension)
        if not isinstance(buckets, dict) or set(buckets.keys()) != expected_buckets:
            return False
        total = 0.0
        for value in buckets.values():
            if not isinstance(value, (int, float)):
                return False
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < 0.0:
                return False
            total += numeric
        if total <= 0.0:
            return False

    if validated_scales.get("schema_version") != VALIDATED_SCALES_SCHEMA_VERSION:
        return False
    try:
        _validate_numeric_scores_mapping(validated_scales.get("scores"), "validated_scales.scores")
    except ValueError:
        return False
    return True
