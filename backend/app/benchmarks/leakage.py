from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SEED_DATE_KEYS: tuple[str, ...] = ("seed_date", "seed_document_date", "document_date", "published_at")
RESOLUTION_DATE_KEYS: tuple[str, ...] = (
    "resolution_date",
    "resolved_at",
    "end_date",
    "market_resolution_date",
)
SEED_PATH_KEYS: tuple[str, ...] = ("seed_file", "source_seed_file", "seed_path")


def _resolve_event_id(event: Mapping[str, Any], fallback_index: int) -> str:
    event_id = event.get("event_id") or event.get("id")
    if isinstance(event_id, str) and event_id.strip():
        return event_id.strip()
    if event_id is not None:
        return str(event_id)
    return f"event-{fallback_index + 1}"


def _first_present_value(event: Mapping[str, Any], keys: Sequence[str]) -> tuple[str | None, Any]:
    for key in keys:
        if key in event:
            return key, event.get(key)
    return None, None


def _parse_iso_date(value: Any, *, field_name: str, event_id: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{event_id}: {field_name} must be an ISO date or datetime string")

    raw = value.strip()
    if not raw:
        raise ValueError(f"{event_id}: {field_name} must be an ISO date or datetime string")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw

    try:
        return date.fromisoformat(normalized)
    except ValueError:
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError as exc:
            raise ValueError(f"{event_id}: unable to parse {field_name} value {value!r} as ISO date") from exc


def _resolve_seed_path(event: Mapping[str, Any], seed_files: Sequence[Path], event_index: int) -> Path:
    for key in SEED_PATH_KEYS:
        raw_path = event.get(key)
        if isinstance(raw_path, str) and raw_path.strip():
            return Path(raw_path)
    if not seed_files:
        raise ValueError(f"{_resolve_event_id(event, event_index)}: no seed files available for leakage preflight")
    return Path(seed_files[event_index % len(seed_files)])


def validate_event_leakage(
    event: Mapping[str, Any],
    seed_text: str,
    leakage_outcome_pattern: re.Pattern[str],
    minimum_days_before_resolution: int,
    *,
    event_index: int = 0,
) -> None:
    event_id = _resolve_event_id(event, event_index)
    seed_key, seed_value = _first_present_value(event, SEED_DATE_KEYS)
    resolution_key, resolution_value = _first_present_value(event, RESOLUTION_DATE_KEYS)

    if seed_key is None:
        raise ValueError(
            f"{event_id}: missing seed date (looked for {', '.join(SEED_DATE_KEYS)})"
        )
    if resolution_key is None:
        raise ValueError(
            f"{event_id}: missing resolution date (looked for {', '.join(RESOLUTION_DATE_KEYS)})"
        )

    seed_date = _parse_iso_date(seed_value, field_name=seed_key, event_id=event_id)
    resolution_date = _parse_iso_date(resolution_value, field_name=resolution_key, event_id=event_id)
    gap_days = (resolution_date - seed_date).days
    if gap_days < minimum_days_before_resolution:
        raise ValueError(
            f"{event_id}: leakage preflight failed; resolution date {resolution_date.isoformat()} is only "
            f"{gap_days} day(s) after seed date {seed_date.isoformat()} (minimum {minimum_days_before_resolution})"
        )

    if leakage_outcome_pattern.search(seed_text):
        raise ValueError(
            f"{event_id}: leakage preflight failed; seed text matches outcome-revealing leakage pattern"
        )


def validate_leakage_preflight(
    events: Iterable[Mapping[str, Any]],
    seed_files: Sequence[Path],
    layer23_config: Mapping[str, Any],
) -> None:
    pattern_raw = layer23_config.get("leakage_outcome_regex")
    if not isinstance(pattern_raw, str) or not pattern_raw.strip():
        raise ValueError("layer23 leakage_outcome_regex must be a non-empty string")

    minimum_days_raw = layer23_config.get("leakage_min_days_before_resolution")
    if isinstance(minimum_days_raw, bool) or not isinstance(minimum_days_raw, int):
        raise ValueError("layer23 leakage_min_days_before_resolution must be an integer")

    leakage_outcome_pattern = re.compile(pattern_raw, re.IGNORECASE)
    failures: list[str] = []

    for event_index, event in enumerate(events):
        event_id = _resolve_event_id(event, event_index)
        seed_path = _resolve_seed_path(event, seed_files, event_index)
        try:
            seed_text = seed_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            failures.append(f"{event_id}: unable to read seed file {seed_path}: {exc}")
            continue

        try:
            validate_event_leakage(
                event,
                seed_text,
                leakage_outcome_pattern,
                minimum_days_raw,
                event_index=event_index,
            )
        except ValueError as exc:
            failures.append(str(exc))

    if failures:
        raise ValueError("Leakage preflight failed:\n- " + "\n- ".join(failures))

