import asyncio
from types import SimpleNamespace

import pytest

from scripts import run_parallel_simulation as parallel_script


class _FakeAgentGraph:
    def __init__(self):
        self.scheduled_agent = object()
        self.llm_agent = object()

    def get_agent(self, agent_id):
        if agent_id == 7:
            return self.scheduled_agent
        if agent_id == 1:
            return self.llm_agent
        raise KeyError(agent_id)

    def get_agents(self):
        return [(1, SimpleNamespace(name='Agent_1'))]


class _FakeEnv:
    def __init__(self):
        self.agent_graph = _FakeAgentGraph()
        self.step_calls = []

    async def step(self, actions):
        self.step_calls.append(actions)

    async def reset(self):
        return None


def test_collect_scheduled_posts_for_round_30_returns_scheduled_post():
    event_config = {
        "scheduled_events": [
            {
                "trigger_round": 30,
                "posts": [
                    {"poster_agent_id": 7, "content": "Injected update"},
                ],
            }
        ]
    }

    assert parallel_script.collect_scheduled_posts_for_round(event_config, 30) == [
        {"poster_agent_id": 7, "content": "Injected update"}
    ]


def test_collect_scheduled_posts_for_round_non_matching_round_returns_empty_list():
    event_config = {
        "scheduled_events": [
            {
                "trigger_round": 29,
                "posts": [
                    {"poster_agent_id": 7, "content": "Injected update"},
                ],
            }
        ]
    }

    assert parallel_script.collect_scheduled_posts_for_round(event_config, 30) == []


def test_collect_scheduled_posts_for_round_non_dict_event_config_returns_empty_list():
    assert parallel_script.collect_scheduled_posts_for_round(None, 30) == []
    assert parallel_script.collect_scheduled_posts_for_round(["not", "a", "dict"], 30) == []


def test_collect_scheduled_posts_for_round_ignores_malformed_trigger_round_values():
    event_config = {
        "scheduled_events": [
            {"trigger_round": True, "posts": [{"poster_agent_id": 1, "content": "ignored"}]},
            {"trigger_round": 30.0, "posts": [{"poster_agent_id": 1, "content": "ignored"}]},
            {"trigger_round": "30", "posts": [{"poster_agent_id": 1, "content": "ignored"}]},
            {"trigger_round": 30, "posts": [{"poster_agent_id": 9, "content": "Valid"}]},
        ]
    }

    assert parallel_script.collect_scheduled_posts_for_round(event_config, 30) == [
        {"poster_agent_id": 9, "content": "Valid"}
    ]


def test_collect_scheduled_posts_for_round_ignores_malformed_poster_and_content_values():
    event_config = {
        "scheduled_events": [
            {"trigger_round": 30, "posts": [
                {"poster_agent_id": True, "content": "ignored"},
                {"poster_agent_id": 7.0, "content": "ignored"},
                {"poster_agent_id": 7, "content": ""},
                {"poster_agent_id": 7, "content": "   "},
                {"poster_agent_id": 7, "content": None},
                {"poster_agent_id": 7, "content": "Valid"},
            ]},
        ]
    }

    assert parallel_script.collect_scheduled_posts_for_round(event_config, 30) == [
        {"poster_agent_id": 7, "content": "Valid"}
    ]


def test_collect_scheduled_posts_for_round_ignores_malformed_entries_safely():
    event_config = {
        "scheduled_events": [
            None,
            "bad-entry",
            {"trigger_round": 30, "posts": "not-a-list"},
            {"trigger_round": 30, "posts": [None, {"poster_agent_id": 1}, {"content": "missing-agent"}]},
            {"trigger_round": 30, "posts": [{"poster_agent_id": 8, "content": "Valid"}]},
        ]
    }

    assert parallel_script.collect_scheduled_posts_for_round(event_config, 30) == [
        {"poster_agent_id": 8, "content": "Valid"}
    ]


def test_apply_scheduled_posts_for_round_executes_matching_posts_once():
    env = _FakeEnv()
    event_config = {
        "scheduled_events": [
            {
                "trigger_round": 30,
                "posts": [
                    {"poster_agent_id": 7, "content": "Injected update"},
                ],
            }
        ]
    }

    count = asyncio.run(parallel_script.apply_scheduled_posts_for_round(env, event_config, 30))

    assert count == 1
    assert len(env.step_calls) == 1
    scheduled_actions = env.step_calls[0]
    assert list(scheduled_actions.keys()) == [env.agent_graph.scheduled_agent]
    scheduled_action = scheduled_actions[env.agent_graph.scheduled_agent]
    assert scheduled_action.action_type == parallel_script.ActionType.CREATE_POST
    assert scheduled_action.action_args == {"content": "Injected update"}


def test_apply_scheduled_posts_for_round_groups_multiple_posts_for_same_agent():
    env = _FakeEnv()
    event_config = {
        "scheduled_events": [
            {
                "trigger_round": 30,
                "posts": [
                    {"poster_agent_id": 7, "content": "First"},
                    {"poster_agent_id": 7, "content": "Second"},
                ],
            }
        ]
    }

    count = asyncio.run(parallel_script.apply_scheduled_posts_for_round(env, event_config, 30))

    assert count == 2
    assert len(env.step_calls) == 1
    scheduled_actions = env.step_calls[0]
    assert list(scheduled_actions.keys()) == [env.agent_graph.scheduled_agent]
    scheduled_action = scheduled_actions[env.agent_graph.scheduled_agent]
    assert isinstance(scheduled_action, list)
    assert [action.action_args for action in scheduled_action] == [
        {"content": "First"},
        {"content": "Second"},
    ]


def test_apply_scheduled_posts_for_round_skips_when_no_matching_posts():
    env = _FakeEnv()

    count = asyncio.run(parallel_script.apply_scheduled_posts_for_round(env, {}, 30))

    assert count == 0
    assert env.step_calls == []


def test_apply_scheduled_posts_for_round_fails_fast_in_benchmark_mode_on_bad_agent_resolution(monkeypatch):
    env = _FakeEnv()
    event_config = {
        "scheduled_events": [
            {
                "trigger_round": 30,
                "posts": [
                    {"poster_agent_id": 999, "content": "Injected update"},
                ],
            }
        ]
    }

    monkeypatch.setenv("BENCHMARK_MODE", "true")

    with pytest.raises(KeyError):
        asyncio.run(parallel_script.apply_scheduled_posts_for_round(env, event_config, 30))

    assert env.step_calls == []


@pytest.mark.parametrize(
    "platform, profile_name, graph_attr, run_fn",
    [
        ("twitter", "twitter_profiles.csv", "generate_twitter_agent_graph", parallel_script.run_twitter_simulation),
        ("reddit", "reddit_profiles.json", "generate_reddit_agent_graph", parallel_script.run_reddit_simulation),
    ],
)
def test_scheduled_posts_run_before_llm_actions(monkeypatch, tmp_path, platform, profile_name, graph_attr, run_fn):
    env = _FakeEnv()
    step_order = []

    async def fake_generate_agent_graph(*args, **kwargs):
        return env.agent_graph

    def fake_make(*args, **kwargs):
        return env

    def fake_get_active_agents_for_round(*args, **kwargs):
        return [(1, env.agent_graph.llm_agent)]

    def fake_fetch_new_actions_from_db(*args, **kwargs):
        return [], 0

    async def recording_step(actions):
        first_action = next(iter(actions.values()))
        if isinstance(first_action, list):
            first_action = first_action[0]
        if isinstance(first_action, parallel_script.ManualAction):
            step_order.append("scheduled")
        elif isinstance(first_action, parallel_script.LLMAction):
            step_order.append("llm")
        else:
            step_order.append(type(first_action).__name__)
        return None

    env.step = recording_step

    monkeypatch.setattr(parallel_script, "create_model", lambda *args, **kwargs: object())
    monkeypatch.setattr(parallel_script, graph_attr, fake_generate_agent_graph)
    monkeypatch.setattr(parallel_script.oasis, "make", fake_make)
    monkeypatch.setattr(parallel_script, "get_active_agents_for_round", fake_get_active_agents_for_round)
    monkeypatch.setattr(parallel_script, "fetch_new_actions_from_db", fake_fetch_new_actions_from_db)

    profile_path = tmp_path / profile_name
    profile_path.write_text("id,name\n1,Agent_1\n", encoding="utf-8")

    config = {
        "event_config": {
            "scheduled_events": [
                {
                    "trigger_round": 1,
                    "posts": [
                        {"poster_agent_id": 7, "content": "Injected update"},
                    ],
                }
            ]
        },
        "time_config": {
            "total_simulation_hours": 1,
            "minutes_per_round": 30,
        },
    }

    asyncio.run(run_fn(config, str(tmp_path), max_rounds=1))

    assert step_order == ["scheduled", "llm"]


def test_scheduled_posts_run_even_without_active_agents(monkeypatch, tmp_path):
    env = _FakeEnv()
    step_order = []

    async def fake_generate_twitter_agent_graph(*args, **kwargs):
        return env.agent_graph

    def fake_make(*args, **kwargs):
        return env

    def fake_get_active_agents_for_round(*args, **kwargs):
        return []

    def fake_fetch_new_actions_from_db(*args, **kwargs):
        return [], 0

    async def recording_step(actions):
        first_action = next(iter(actions.values()))
        if isinstance(first_action, list):
            first_action = first_action[0]
        if isinstance(first_action, parallel_script.ManualAction):
            step_order.append("scheduled")
        elif isinstance(first_action, parallel_script.LLMAction):
            step_order.append("llm")
        else:
            step_order.append(type(first_action).__name__)
        return None

    env.step = recording_step

    monkeypatch.setattr(parallel_script, "create_model", lambda *args, **kwargs: object())
    monkeypatch.setattr(parallel_script, "generate_twitter_agent_graph", fake_generate_twitter_agent_graph)
    monkeypatch.setattr(parallel_script.oasis, "make", fake_make)
    monkeypatch.setattr(parallel_script, "get_active_agents_for_round", fake_get_active_agents_for_round)
    monkeypatch.setattr(parallel_script, "fetch_new_actions_from_db", fake_fetch_new_actions_from_db)

    profile_path = tmp_path / "twitter_profiles.csv"
    profile_path.write_text("id,name\n1,Agent_1\n", encoding="utf-8")

    config = {
        "event_config": {
            "scheduled_events": [
                {
                    "trigger_round": 1,
                    "posts": [
                        {"poster_agent_id": 7, "content": "Injected update"},
                    ],
                }
            ]
        },
        "time_config": {
            "total_simulation_hours": 1,
            "minutes_per_round": 30,
        },
    }

    asyncio.run(parallel_script.run_twitter_simulation(config, str(tmp_path), max_rounds=1))

    assert step_order == ["scheduled"]
