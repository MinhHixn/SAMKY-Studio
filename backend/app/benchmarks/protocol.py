"""ECN-BENCH protocol primitives."""

from __future__ import annotations
from copy import deepcopy
import os
from typing import Any, Dict, List


def _as_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error


def _is_dev_minimal_mode_enabled() -> bool:
    return os.environ.get("DEV_MINIMAL_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _dev_minimal_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def enforce_protocol_constraints(config: Dict[str, Any]) -> None:
    """Validate the benchmark protocol invariants."""
    dev_minimal_mode = _is_dev_minimal_mode_enabled()
    required_agent_count = _dev_minimal_int("DEV_MINIMAL_AGENT_COUNT", 100) if dev_minimal_mode else 3000
    required_rounds = _dev_minimal_int("DEV_MINIMAL_MAX_STEPS", 30) if dev_minimal_mode else 60

    agent_configs = config.get("agent_configs")
    if not isinstance(agent_configs, list):
        raise ValueError("agent_configs must be a list")
    if len(agent_configs) != required_agent_count:
        if dev_minimal_mode:
            raise ValueError(
                f"DEV_MINIMAL_MODE requires exactly {required_agent_count} agents, got {len(agent_configs)}"
            )
        raise ValueError(f"Protocol requires exactly 3000 agents, got {len(agent_configs)}")

    time_config = config.get("time_config", {})
    total_simulation_hours = _as_int(time_config.get("total_simulation_hours"), "total_simulation_hours")
    minutes_per_round = _as_int(time_config.get("minutes_per_round"), "minutes_per_round")
    if minutes_per_round <= 0:
        raise ValueError("minutes_per_round must be greater than 0")

    total_rounds = (total_simulation_hours * 60) // minutes_per_round
    if total_rounds != required_rounds:
        if dev_minimal_mode:
            raise ValueError(
                f"DEV_MINIMAL_MODE requires exactly {required_rounds} rounds, got {total_rounds}"
            )
        raise ValueError(f"Protocol requires exactly 60 rounds, got {total_rounds}")


def expand_profiles_to_target(base_profiles: List[Dict[str, Any]], target_count: int = 3000) -> List[Dict[str, Any]]:
    """Expand a base profile set deterministically to the requested size."""
    if not base_profiles:
        raise ValueError("Cannot expand profiles from an empty base list")
    if target_count <= 0:
        raise ValueError("target_count must be greater than 0")

    expanded: List[Dict[str, Any]] = []

    for index in range(target_count):
        profile = deepcopy(base_profiles[index % len(base_profiles)])
        profile["user_id"] = index

        base_username = str(profile.get("username") or "agent")
        profile["username"] = f"{base_username}_{index}"
        expanded.append(profile)

    return expanded


def _extract_usable_text(payload: Dict[str, Any]) -> str:
    for key in ("body", "headline"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def build_step30_scheduled_event(
    payload: Dict[str, Any],
    poster_agent_id: int = 0,
    *,
    trigger_round: int = 30,
) -> Dict[str, Any]:
    """Create the scheduled event used for step-30 injections."""
    content = _extract_usable_text(payload)
    if not content:
        raise ValueError("Injection payload must include body/headline text")

    event: Dict[str, Any] = {
        "trigger_round": int(trigger_round),
        "posts": [{"poster_agent_id": poster_agent_id, "content": content}],
    }
    temporal_updates = payload.get("temporal_updates")
    if isinstance(temporal_updates, list):
        event["temporal_updates"] = deepcopy(temporal_updates)
    return event
