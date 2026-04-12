"""Scoring utilities for ECN-BENCH benchmark outputs."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List

from .evaluator import (
    MCQ_BUCKET_KEYS,
    MCQ_DIMENSION_KEYS,
    VALIDATED_SCALES_SCHEMA_VERSION,
    _validate_numeric_scores_mapping,
)


def brier_score(probabilities: Dict[str, float], truth: str) -> float:
    labels = set(probabilities)
    labels.add(truth)
    score = 0.0
    for outcome in labels:
        probability = probabilities.get(outcome, 0.0)
        if not isinstance(probability, (int, float)):
            raise ValueError(f"Invalid probability for outcome {outcome!r}: {probability!r}")
        observed = 1.0 if outcome == truth else 0.0
        score += (float(probability) - observed) ** 2
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


def summarize_rubric_artifacts(rows: List[Dict]) -> Dict:
    completed_rows = [row for row in rows if row.get("full_simulation_completed")]
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
