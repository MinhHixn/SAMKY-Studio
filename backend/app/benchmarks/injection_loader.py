"""Load ECN-BENCH step-30 injection payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Literal

Condition = Literal["A", "B", "C"]


class Step30InjectionLoader:
    """Load and resolve injection payloads by event id."""

    def __init__(self, path: Path | str):
        self._path = Path(path)
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        events = raw.get("events") if isinstance(raw, dict) else raw

        if not isinstance(events, list):
            raise ValueError("Injection bank must contain an events list")

        self._events: Dict[str, Dict[str, Any]] = {}
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("Each injection event must be an object")
            event_id = event.get("event_id")
            if not event_id:
                raise ValueError("Each injection event must include event_id")
            self._events[str(event_id)] = event

    def get_payload(self, event_id: str, condition: Condition) -> Dict[str, Any] | None:
        """Return the payload for a condition-specific event."""
        if condition not in ("A", "B", "C"):
            raise ValueError("condition must be one of A, B, or C")

        if condition == "A":
            return None

        event = self._events.get(str(event_id))
        if event is None:
            raise KeyError(f"Missing injection event_id: {event_id}")

        payload_key = "relevant_update" if condition == "B" else "null_update"
        payload = event.get(payload_key)
        if payload is None:
            raise KeyError(f"Missing '{payload_key}' payload for event_id: {event_id}")
        if not isinstance(payload, dict):
            raise KeyError(f"Invalid '{payload_key}' payload for event_id: {event_id}")
        return payload
