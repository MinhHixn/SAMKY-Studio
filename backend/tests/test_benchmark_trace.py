import json
from datetime import datetime

from app.utils.benchmark_trace import BenchmarkTraceWriter


def test_trace_writer_appends_jsonl_with_iso_timestamps(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    writer = BenchmarkTraceWriter(trace_path)

    writer.write(
        {
            "event_id": "E1",
            "provider": "openrouter",
            "model": "openrouter/auto",
            "status": "ok",
        }
    )
    writer.write(
        {
            "event_id": "E2",
            "provider": "openrouter",
            "model": "openrouter/auto",
            "status": "error",
        }
    )

    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["event_id"] == "E1"
    assert rows[1]["event_id"] == "E2"

    for row in rows:
        assert row["provider"] == "openrouter"
        assert row["model"] == "openrouter/auto"
        assert "timestamp" in row
        assert datetime.fromisoformat(row["timestamp"])
