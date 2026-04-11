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


def test_collect_scheduled_posts_for_round_ignores_malformed_entries_safely():
    event_config = {
        "scheduled_events": [
            None,
            "bad-entry",
            {"trigger_round": "thirty", "posts": [{"poster_agent_id": 1, "content": "ignored"}]},
            {"trigger_round": 30, "posts": "not-a-list"},
            {"trigger_round": 30, "posts": [None, {"poster_agent_id": 1}, {"content": "missing-agent"}]},
            {"trigger_round": 30, "posts": [{"poster_agent_id": 8, "content": "Valid"}]},
        ]
    }

    assert parallel_script.collect_scheduled_posts_for_round(event_config, 30) == [
        {"poster_agent_id": 8, "content": "Valid"}
    ]
