import sqlite3
from pathlib import Path

from scripts.run_parallel_simulation import (
    _build_telemetry_probe_rounds,
    _extract_interview_probability,
    fetch_new_actions_from_db,
)


def test_build_telemetry_probe_rounds_matches_phase1_defaults() -> None:
    assert _build_telemetry_probe_rounds(30) == [6, 12, 18, 24, 30]
    assert _build_telemetry_probe_rounds(60) == [12, 24, 36, 48, 60]


def test_extract_interview_probability_from_nested_response() -> None:
    payload = {
        "prompt": "Return probability",
        "response": {"analysis": "updated confidence", "yes_probability": 0.73},
    }
    assert _extract_interview_probability(payload) == 0.73


def test_fetch_new_actions_from_db_keeps_interview_probability(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE trace (user_id INTEGER, action TEXT, info TEXT)")
    cursor.execute(
        "INSERT INTO trace (user_id, action, info) VALUES (?, ?, ?)",
        (
            7,
            "interview",
            '{"prompt":"p","response":"{\\"yes_probability\\": 0.61}"}',
        ),
    )
    conn.commit()
    conn.close()

    actions, _ = fetch_new_actions_from_db(str(db_path), 0, {7: "Agent 7"})
    assert len(actions) == 1
    assert actions[0]["action_type"] == "INTERVIEW"
    assert actions[0]["action_args"]["yes_probability"] == 0.61
