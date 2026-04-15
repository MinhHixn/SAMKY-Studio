import pytest

from app.benchmarks.statistics import (
    aggregate_calibration_counts,
    assign_probability_bracket,
    compute_cohens_d_with_ci,
    compute_power_analysis,
    ranked_probability_score,
    write_calibration_plot,
)


def test_ranked_probability_score_binary():
    score = ranked_probability_score({"A": 0.7, "B": 0.3}, "A", ["A", "B"])
    assert score == pytest.approx(0.09)


def test_ranked_probability_score_multiclass():
    score = ranked_probability_score({"A": 0.2, "B": 0.5, "C": 0.3}, "B", ["A", "B", "C"])
    assert score == pytest.approx(0.13)


def test_compute_cohens_d_with_ci_returns_range():
    result = compute_cohens_d_with_ci([1, 2, 3, 4, 5], [1, 1, 2, 2, 1])

    assert result["confidence"] == pytest.approx(0.95)
    assert result["ci_lower"] <= result["cohens_d"] <= result["ci_upper"]
    assert result["cohens_d"] > 0


def test_compute_power_analysis_outputs():
    result = compute_power_analysis(actual_n=30, delta_target=0.1, sigma_assumed=0.2, target_power=0.8)

    assert result["actual_n"] == 30
    assert result["required_n_for_target_power"] >= 2
    assert 0 <= result["apriori_power"] <= 1
    assert 0 <= result["achieved_power"] <= 1


def test_calibration_bucket_assignment_and_aggregation(tmp_path):
    assert assign_probability_bracket(0.1) == "0-0.25"
    assert assign_probability_bracket(0.25) == "0.25-0.5"
    assert assign_probability_bracket(0.5) == "0.5-0.75"
    assert assign_probability_bracket(0.75) == "0.75-1.0"
    assert assign_probability_bracket(1.0) == "0.75-1.0"

    buckets = aggregate_calibration_counts([(0.1, True), (0.2, False), (0.8, True)])
    low_bucket = buckets["0-0.25"]
    high_bucket = buckets["0.75-1.0"]

    assert low_bucket["count"] == 2
    assert low_bucket["hits"] == 1
    assert low_bucket["mean_predicted"] == pytest.approx(0.15)
    assert low_bucket["empirical_rate"] == pytest.approx(0.5)

    assert high_bucket["count"] == 1
    assert high_bucket["hits"] == 1
    assert high_bucket["mean_predicted"] == pytest.approx(0.8)
    assert high_bucket["empirical_rate"] == pytest.approx(1.0)

    output_path = tmp_path / "calibration.png"
    returned_path = write_calibration_plot(buckets, output_path)
    assert output_path.exists()
    assert returned_path == str(output_path)
