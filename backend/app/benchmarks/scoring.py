"""Scoring utilities for ECN-BENCH benchmark outputs."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List


def brier_score(probabilities: Dict[str, float], truth: str) -> float:
    if truth not in probabilities:
        raise ValueError(f"truth outcome {truth!r} missing from probabilities")

    score = 0.0
    for outcome, probability in probabilities.items():
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
