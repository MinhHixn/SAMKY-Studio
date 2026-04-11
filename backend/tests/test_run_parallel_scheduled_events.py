from scripts import run_parallel_simulation as parallel_script


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
