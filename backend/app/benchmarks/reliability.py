"""Reliability helpers for evaluator agreement analysis."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .evaluator import MCQ_BUCKET_KEYS


def dominant_bucket_label(mcq_dimension_buckets: Mapping[str, Any]) -> str:
    if not isinstance(mcq_dimension_buckets, Mapping) or not mcq_dimension_buckets:
        raise ValueError("mcq_dimension_buckets must be a non-empty mapping")

    normalized: Dict[str, float] = {}
    for bucket in MCQ_BUCKET_KEYS:
        value = mcq_dimension_buckets.get(bucket)
        if not isinstance(value, (int, float)):
            raise ValueError(f"mcq_dimension_buckets[{bucket!r}] must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"mcq_dimension_buckets[{bucket!r}] must be finite")
        normalized[bucket] = numeric

    return max(normalized.items(), key=lambda item: (item[1], item[0]))[0]


def cohens_kappa(labels_a: Sequence[str], labels_b: Sequence[str], categories: Sequence[str]) -> float:
    if len(labels_a) != len(labels_b):
        raise ValueError("labels_a and labels_b must have identical lengths")
    if not categories:
        raise ValueError("categories must be non-empty")
    if not labels_a:
        return 1.0

    categories_list = [str(category) for category in categories if str(category)]
    if not categories_list:
        raise ValueError("categories must include at least one non-empty label")
    category_set = set(categories_list)
    for label in labels_a:
        if label not in category_set:
            raise ValueError(f"labels_a contains unknown category: {label!r}")
    for label in labels_b:
        if label not in category_set:
            raise ValueError(f"labels_b contains unknown category: {label!r}")

    total = float(len(labels_a))
    row_totals = {category: 0 for category in categories_list}
    col_totals = {category: 0 for category in categories_list}
    agreements = 0.0

    for left, right in zip(labels_a, labels_b):
        row_totals[left] += 1
        col_totals[right] += 1
        if left == right:
            agreements += 1.0

    observed = agreements / total
    expected = sum((row_totals[category] / total) * (col_totals[category] / total) for category in categories_list)
    denominator = 1.0 - expected
    if denominator <= 0.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / denominator


def kappa_by_dimension(rows: Iterable[Mapping[str, Any]]) -> Dict[str, float]:
    labels_by_dimension: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: {"run1": [], "run2": []})
    valid_categories = set(MCQ_BUCKET_KEYS)
    for row in rows:
        if str(row.get("simulation_status", "")) not in ("", "completed"):
            continue
        dimension_labels = row.get("evaluator_dimension_labels")
        if not isinstance(dimension_labels, Mapping):
            continue
        for raw_dimension, pair in dimension_labels.items():
            if not isinstance(pair, Mapping):
                continue
            run1 = pair.get("run1")
            run2 = pair.get("run2")
            if not isinstance(run1, str) or not isinstance(run2, str):
                continue
            run1_label = run1.strip()
            run2_label = run2.strip()
            if run1_label not in valid_categories or run2_label not in valid_categories:
                continue
            dimension = str(raw_dimension).strip()
            if not dimension:
                continue
            labels_by_dimension[dimension]["run1"].append(run1_label)
            labels_by_dimension[dimension]["run2"].append(run2_label)

    kappas: Dict[str, float] = {}
    for dimension in sorted(labels_by_dimension):
        labels = labels_by_dimension[dimension]
        if not labels["run1"]:
            continue
        kappas[dimension] = round(
            cohens_kappa(labels["run1"], labels["run2"], categories=MCQ_BUCKET_KEYS),
            6,
        )
    return kappas
