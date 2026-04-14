"""Phase 1 baseline validation and scoring."""

from __future__ import annotations

from typing import Any, Dict, Mapping
import math

from .scoring import brier_score


def validate_polymarket_opening_prior(
    event: Mapping[str, Any], *, prior_sum_tolerance: float
) -> Dict[str, float]:
    event_id = str(event.get("event_id", "unknown_event"))
    options = [str(option) for option in event.get("options", [])]
    prior = event.get("polymarket_opening_prior")
    if not isinstance(prior, Mapping):
        raise ValueError(f"{event_id}: polymarket_opening_prior missing or invalid")

    normalized: Dict[str, float] = {}
    for label in options:
        if label not in prior:
            raise ValueError(f"{event_id}: missing required outcome labels in polymarket_opening_prior")
        raw = prior[label]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{event_id}: prior {label!r} must be numeric")
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"{event_id}: prior {label!r} must be finite")
        if value < 0.0 or value > 1.0:
            raise ValueError(f"{event_id}: prior {label!r} out of range [0,1]")
        normalized[label] = value

    if abs(sum(normalized.values()) - 1.0) > float(prior_sum_tolerance):
        raise ValueError(f"{event_id}: polymarket_opening_prior must sum to 1.0")
    return normalized


def build_baseline_scores(event: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    outcome = str(event.get("outcome") or event.get("answer") or "")
    options = [str(option) for option in event.get("options", [])]
    n = len(options)
    uniform = {label: 1.0 / n for label in options}
    market_prior = validate_polymarket_opening_prior(event, prior_sum_tolerance=1e-6)
    return {
        "uniform_random": {"probabilities": uniform, "brier": brier_score(uniform, outcome)},
        "market_prior": {"probabilities": market_prior, "brier": brier_score(market_prior, outcome)},
    }
