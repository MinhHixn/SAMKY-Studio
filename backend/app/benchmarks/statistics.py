"""Statistical utilities for ECN-BENCH benchmark analysis."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import matplotlib
from scipy import stats

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

_CALIBRATION_BRACKETS = [
    (0.0, 0.25, "0-0.25"),
    (0.25, 0.5, "0.25-0.5"),
    (0.5, 0.75, "0.5-0.75"),
    (0.75, 1.0, "0.75-1.0"),
]


def _format_calibration_label(lower: float, upper: float) -> str:
    return f"{lower:g}-{upper:g}"


def _resolve_calibration_brackets(
    brackets: Sequence[Sequence[float]] | None = None,
) -> list[tuple[float, float, str]]:
    if brackets is None:
        return list(_CALIBRATION_BRACKETS)
    if not isinstance(brackets, Sequence) or not brackets:
        raise ValueError("calibration brackets must be a non-empty sequence of [lower, upper] pairs")

    expected_left = 0.0
    resolved: list[tuple[float, float, str]] = []
    for bracket in brackets:
        if not isinstance(bracket, Sequence) or len(bracket) != 2:
            raise ValueError("calibration brackets must be [lower, upper] pairs")
        lower_raw, upper_raw = bracket
        if not isinstance(lower_raw, (int, float)) or not isinstance(upper_raw, (int, float)):
            raise ValueError("calibration brackets must be numeric")
        lower = float(lower_raw)
        upper = float(upper_raw)
        if not math.isfinite(lower) or not math.isfinite(upper):
            raise ValueError("calibration brackets must be finite")
        if lower != expected_left or upper <= lower:
            raise ValueError("calibration brackets must be contiguous and strictly increasing")
        resolved.append((lower, upper, _format_calibration_label(lower, upper)))
        expected_left = upper

    if resolved[0][0] != 0.0 or resolved[-1][1] != 1.0:
        raise ValueError("calibration brackets must span [0, 1]")
    return resolved


def ranked_probability_score(
    probabilities: Mapping[str, float],
    truth_label: str,
    ordered_labels: Iterable[str],
) -> float:
    if not isinstance(probabilities, Mapping):
        raise ValueError("probabilities must be a mapping")

    labels = [str(label) for label in ordered_labels]
    if len(labels) < 2:
        raise ValueError("ordered_labels must include at least two labels")
    if len(set(labels)) != len(labels):
        raise ValueError("ordered_labels must be unique")

    truth = str(truth_label)
    if truth not in labels:
        raise ValueError("truth_label must be present in ordered_labels")

    normalized: dict[str, float] = {}
    for label, raw_value in probabilities.items():
        key = str(label)
        if key not in labels:
            raise ValueError(f"Probability label {key!r} is not present in ordered_labels")
        if not isinstance(raw_value, (int, float)):
            raise ValueError(f"Invalid probability for outcome {key!r}: {raw_value!r}")
        value = float(raw_value)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid probability for outcome {key!r}: {raw_value!r}")
        normalized[key] = value

    total = sum(normalized.get(label, 0.0) for label in labels)
    if total <= 0:
        raise ValueError("probabilities must sum to a positive value")

    if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
        normalized = {label: value / total for label, value in normalized.items()}

    cumulative = 0.0
    rps = 0.0
    truth_index = labels.index(truth)
    for idx, label in enumerate(labels[:-1]):
        cumulative += normalized.get(label, 0.0)
        observed = 1.0 if idx >= truth_index else 0.0
        rps += (cumulative - observed) ** 2
    return rps


def _validate_sample(sample: Iterable[float], name: str) -> list[float]:
    if not isinstance(sample, Iterable):
        raise ValueError(f"{name} must be an iterable of numbers")
    values: list[float] = []
    for value in sample:
        if not isinstance(value, (int, float)):
            raise ValueError(f"{name} must contain numeric values")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{name} contains non-finite values")
        values.append(numeric)
    if len(values) < 2:
        raise ValueError(f"{name} must include at least two values")
    return values


def _mean_and_std(values: list[float]) -> tuple[float, float]:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def compute_cohens_d_with_ci(
    sample_a: Iterable[float],
    sample_b: Iterable[float],
    confidence: float = 0.95,
) -> dict[str, float]:
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")

    values_a = _validate_sample(sample_a, "sample_a")
    values_b = _validate_sample(sample_b, "sample_b")

    mean_a, std_a = _mean_and_std(values_a)
    mean_b, std_b = _mean_and_std(values_b)
    n_a = len(values_a)
    n_b = len(values_b)
    pooled_var = ((n_a - 1) * std_a**2 + (n_b - 1) * std_b**2) / (n_a + n_b - 2)
    if pooled_var <= 0:
        raise ValueError("pooled standard deviation must be positive")
    pooled_std = math.sqrt(pooled_var)

    diff = mean_a - mean_b
    cohens_d = diff / pooled_std
    df = n_a + n_b - 2
    alpha = 1 - confidence
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    se_diff = pooled_std * math.sqrt(1 / n_a + 1 / n_b)
    diff_lower = diff - t_crit * se_diff
    diff_upper = diff + t_crit * se_diff

    return {
        "cohens_d": round(cohens_d, 6),
        "ci_lower": round(diff_lower / pooled_std, 6),
        "ci_upper": round(diff_upper / pooled_std, 6),
        "confidence": confidence,
        "mean_difference": round(diff, 6),
        "pooled_std": round(pooled_std, 6),
        "n_a": float(n_a),
        "n_b": float(n_b),
    }


def _power_two_sample_t(n_per_group: int, effect_size: float, alpha: float = 0.05) -> float:
    if n_per_group < 2:
        raise ValueError("n_per_group must be at least 2")
    if effect_size <= 0:
        raise ValueError("effect_size must be positive")
    df = 2 * n_per_group - 2
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    ncp = effect_size * math.sqrt(n_per_group / 2)
    cdf_upper = stats.nct.cdf(t_crit, df, ncp)
    cdf_lower = stats.nct.cdf(-t_crit, df, ncp)
    return 1 - (cdf_upper - cdf_lower)


def _required_n_for_power(effect_size: float, target_power: float, alpha: float = 0.05) -> int:
    if target_power <= 0 or target_power >= 1:
        raise ValueError("target_power must be between 0 and 1")
    for n in range(2, 10001):
        if _power_two_sample_t(n, effect_size, alpha) >= target_power:
            return n
    raise ValueError("Failed to find required sample size for target power")


def compute_power_analysis(
    actual_n: int,
    delta_target: float = 0.05,
    sigma_assumed: float = 0.12,
    target_power: float = 0.80,
    observed_sigma: float | None = None,
) -> dict[str, float | int | None]:
    if not isinstance(actual_n, int) or actual_n <= 0:
        raise ValueError("actual_n must be a positive integer")
    if delta_target <= 0:
        raise ValueError("delta_target must be positive")
    if sigma_assumed <= 0:
        raise ValueError("sigma_assumed must be positive")

    effect_size_assumed = abs(delta_target) / sigma_assumed
    required_n = _required_n_for_power(effect_size_assumed, target_power)
    apriori_power = (
        _power_two_sample_t(actual_n, effect_size_assumed) if actual_n >= 2 else None
    )

    resolved_sigma = sigma_assumed if observed_sigma is None else float(observed_sigma)
    if resolved_sigma <= 0:
        raise ValueError("observed_sigma must be positive")
    effect_size_observed = abs(delta_target) / resolved_sigma
    achieved_power = (
        _power_two_sample_t(actual_n, effect_size_observed) if actual_n >= 2 else None
    )

    return {
        "required_n_for_target_power": required_n,
        "actual_n": actual_n,
        "apriori_power": round(apriori_power, 6) if apriori_power is not None else None,
        "achieved_power": round(achieved_power, 6) if achieved_power is not None else None,
    }


def assign_probability_bracket(
    probability: float,
    *,
    brackets: Sequence[Sequence[float]] | None = None,
) -> str:
    if not isinstance(probability, (int, float)):
        raise ValueError("probability must be numeric")
    value = float(probability)
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError("probability must be within [0, 1]")
    resolved_brackets = _resolve_calibration_brackets(brackets)
    for lower, upper, label in resolved_brackets[:-1]:
        if lower <= value < upper:
            return label
    return resolved_brackets[-1][2]


def _init_calibration_buckets(
    *,
    brackets: Sequence[Sequence[float]] | None = None,
) -> dict[str, dict[str, float | int]]:
    resolved_brackets = _resolve_calibration_brackets(brackets)
    return {
        label: {"count": 0, "hits": 0, "predicted_sum": 0.0}
        for _, _, label in resolved_brackets
    }


def aggregate_calibration_counts(
    items: Iterable[tuple[float, bool | int]],
    *,
    brackets: Sequence[Sequence[float]] | None = None,
) -> dict[str, dict[str, float | int]]:
    buckets = _init_calibration_buckets(brackets=brackets)
    for probability, hit in items:
        if not isinstance(hit, (bool, int)):
            raise ValueError("calibration hits must be boolean or integer")
        bucket_label = assign_probability_bracket(probability, brackets=brackets)
        bucket = buckets[bucket_label]
        bucket["count"] += 1
        bucket["hits"] += int(hit)
        bucket["predicted_sum"] += float(probability)

    for bucket in buckets.values():
        count = int(bucket["count"])
        if count:
            bucket["mean_predicted"] = round(bucket["predicted_sum"] / count, 6)
            bucket["empirical_rate"] = round(bucket["hits"] / count, 6)
        else:
            bucket["mean_predicted"] = 0.0
            bucket["empirical_rate"] = 0.0
        bucket.pop("predicted_sum", None)
    return buckets


def write_calibration_plot(
    buckets: Mapping[str, Mapping[str, float | int]],
    output_path: Path | str,
    *,
    brackets: Sequence[Sequence[float]] | None = None,
) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ordered_labels = [label for _, _, label in _resolve_calibration_brackets(brackets)]
    x_values: list[float] = []
    y_values: list[float] = []
    for label in ordered_labels:
        bucket = buckets.get(label)
        if not isinstance(bucket, Mapping):
            continue
        count = bucket.get("count")
        mean_predicted = bucket.get("mean_predicted")
        empirical_rate = bucket.get("empirical_rate")
        if isinstance(count, int) and count > 0 and isinstance(mean_predicted, (int, float)) and isinstance(
            empirical_rate, (int, float)
        ):
            x_values.append(float(mean_predicted))
            y_values.append(float(empirical_rate))

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect")
    if x_values:
        ax.plot(x_values, y_values, marker="o", color="tab:blue", label="Empirical")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Empirical frequency")
    ax.set_title("Calibration Curve")
    ax.grid(True, linestyle=":", linewidth=0.5)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, format="png")
    plt.close(fig)
    return str(path)
