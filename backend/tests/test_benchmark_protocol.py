import pytest

from app.benchmarks.injection_loader import Step30InjectionLoader
from app.benchmarks.protocol import (
    build_step30_scheduled_event,
    enforce_protocol_constraints,
    expand_profiles_to_target,
)


def test_enforce_protocol_requires_exact_60_rounds(monkeypatch):
    monkeypatch.setenv("DEV_MINIMAL_MODE", "False")
    config = {
        "time_config": {"total_simulation_hours": 72, "minutes_per_round": 60},
        "agent_configs": [{}] * 3000,
    }

    with pytest.raises(ValueError, match=r"exactly 60"):
        enforce_protocol_constraints(config)


@pytest.mark.parametrize("agent_configs", [None, {}])
def test_enforce_protocol_rejects_missing_or_wrong_agent_configs_type(agent_configs, monkeypatch):
    monkeypatch.setenv("DEV_MINIMAL_MODE", "False")
    config = {
        "time_config": {"total_simulation_hours": 60, "minutes_per_round": 60},
        "agent_configs": agent_configs,
    }

    with pytest.raises(ValueError, match=r"agent_configs must be a list"):
        enforce_protocol_constraints(config)


def test_enforce_protocol_accepts_exact_3000_agents_and_60_rounds(monkeypatch):
    monkeypatch.setenv("DEV_MINIMAL_MODE", "False")
    config = {
        "time_config": {"total_simulation_hours": 60, "minutes_per_round": 60},
        "agent_configs": [{}] * 3000,
    }

    enforce_protocol_constraints(config)


def test_expand_profiles_reaches_exact_target_size_and_user_ids():
    base_profiles = [
        {"user_id": 10, "username": "agent", "name": "Agent 0", "persona": "x", "bio": "x"},
        {"user_id": 11, "username": "agent", "name": "Agent 1", "persona": "y", "bio": "y"},
    ]

    expanded = expand_profiles_to_target(base_profiles, target_count=3000)

    assert len(expanded) == 3000
    assert [profile["user_id"] for profile in expanded[:5]] == [0, 1, 2, 3, 4]
    assert expanded[-1]["user_id"] == 2999
    assert len({profile["username"] for profile in expanded}) == 3000


def test_injection_loader_missing_event_raises_key_error(tmp_path):
    path = tmp_path / "bank.json"
    path.write_text(
        '{"events":[{"event_id":"E1","relevant_update":{"body":"x"},"null_update":{"body":"y"}}]}',
        encoding="utf-8",
    )

    loader = Step30InjectionLoader(path)

    with pytest.raises(KeyError, match=r"E2"):
        loader.get_payload("E2", "B")


def test_injection_loader_selects_condition_b_and_c_payloads(tmp_path):
    path = tmp_path / "bank.json"
    path.write_text(
        '{"events":[{"event_id":"E1","relevant_update":{"body":"relevant"},"null_update":{"headline":"null"}}]}',
        encoding="utf-8",
    )

    loader = Step30InjectionLoader(path)

    assert loader.get_payload("E1", "B") == {"body": "relevant"}
    assert loader.get_payload("E1", "C") == {"headline": "null"}
    assert loader.get_payload("E1", "A") is None


@pytest.mark.parametrize("condition", ["D", "", "a"])
def test_injection_loader_rejects_invalid_condition(tmp_path, condition):
    path = tmp_path / "bank.json"
    path.write_text(
        '{"events":[{"event_id":"E1","relevant_update":{"body":"relevant"},"null_update":{"headline":"null"}}]}',
        encoding="utf-8",
    )

    loader = Step30InjectionLoader(path)

    with pytest.raises(ValueError, match=r"condition must be one of A, B, or C"):
        loader.get_payload("E1", condition)


def test_build_step30_scheduled_event_uses_body_or_headline():
    event = build_step30_scheduled_event({"body": "Injected update"}, poster_agent_id=7)

    assert event == {
        "trigger_round": 30,
        "posts": [{"poster_agent_id": 7, "content": "Injected update"}],
    }


def test_build_step30_scheduled_event_rejects_empty_payload():
    with pytest.raises(ValueError, match=r"body/headline"):
        build_step30_scheduled_event({"body": "   "})


def test_build_step30_scheduled_event_preserves_temporal_updates_when_present():
    event = build_step30_scheduled_event(
        {
            "body": "Injected update",
            "temporal_updates": [
                {
                    "fact_id": "fact-1",
                    "status": "superseded",
                    "replacement_fact": {"graph_id": "g-1"},
                }
            ],
        }
    )

    assert event["trigger_round"] == 30
    assert event["temporal_updates"] == [
        {
            "fact_id": "fact-1",
            "status": "superseded",
            "replacement_fact": {"graph_id": "g-1"},
        }
    ]
