from __future__ import annotations

import re

import pytest

from app.benchmarks.leakage import validate_event_leakage, validate_leakage_preflight


def _layer23_config(*, pattern: str = r"resolved|closed", min_days: int = 7) -> dict[str, object]:
    return {
        "leakage_outcome_regex": pattern,
        "leakage_min_days_before_resolution": min_days,
    }


def test_validate_leakage_preflight_passes_with_minimum_gap_and_no_keyword(tmp_path):
    seed_file = tmp_path / "seed.txt"
    seed_file.write_text("Neutral background text only.", encoding="utf-8")
    event = {
        "event_id": "E1",
        "seed_date": "2024-01-01",
        "resolution_date": "2024-01-08",
    }

    validate_leakage_preflight([event], [seed_file], _layer23_config())


def test_validate_leakage_preflight_rejects_gap_under_effective_seven_day_minimum(tmp_path):
    seed_file = tmp_path / "seed.txt"
    seed_file.write_text("Neutral background text only.", encoding="utf-8")
    event = {
        "event_id": "E1b",
        "seed_date": "2024-01-01",
        "resolution_date": "2024-01-07",
    }

    with pytest.raises(ValueError, match=r"E1b.*minimum 7"):
        validate_leakage_preflight([event], [seed_file], _layer23_config(min_days=1))


def test_validate_event_leakage_passes_with_datetime_strings():
    event = {
        "event_id": "E2",
        "published_at": "2024-01-01T08:00:00Z",
        "resolved_at": "2024-01-08T09:30:00Z",
    }
    pattern = re.compile(r"resolved|closed", re.IGNORECASE)

    validate_event_leakage(event, "Neutral text.", pattern, 7)


def test_validate_leakage_preflight_fails_for_gap_under_seven_days(tmp_path):
    seed_file = tmp_path / "seed.txt"
    seed_file.write_text("Neutral background text only.", encoding="utf-8")
    event = {
        "event_id": "E3",
        "seed_document_date": "2024-01-01",
        "market_resolution_date": "2024-01-06",
    }

    with pytest.raises(ValueError, match=r"E3.*only 5 day"):
        validate_leakage_preflight([event], [seed_file], _layer23_config())


def test_validate_leakage_preflight_fails_for_keyword_match(tmp_path):
    seed_file = tmp_path / "seed.txt"
    seed_file.write_text("The market was resolved early.", encoding="utf-8")
    event = {
        "event_id": "E4",
        "seed_date": "2024-01-01",
        "resolution_date": "2024-01-12",
    }

    with pytest.raises(ValueError, match=r"E4.*outcome-revealing leakage pattern"):
        validate_leakage_preflight([event], [seed_file], _layer23_config())


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (
            {"event_id": "E5", "resolution_date": "2024-01-08"},
            r"E5: missing seed date",
        ),
        (
            {"event_id": "E6", "seed_date": "2024-01-01"},
            r"E6: missing resolution date",
        ),
        (
            {"event_id": "E7", "seed_date": "not-a-date", "resolution_date": "2024-01-08"},
            r"E7: unable to parse seed_date value 'not-a-date'",
        ),
        (
            {"event_id": "E8", "seed_date": "2024-01-01", "resolution_date": "not-a-date"},
            r"E8: unable to parse resolution_date value 'not-a-date'",
        ),
    ],
)
def test_validate_leakage_preflight_fails_for_missing_or_unparseable_dates(tmp_path, event, message):
    seed_file = tmp_path / "seed.txt"
    seed_file.write_text("Neutral background text only.", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_leakage_preflight([event], [seed_file], _layer23_config())

