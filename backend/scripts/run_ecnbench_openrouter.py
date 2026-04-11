import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.utils.benchmark_trace import BenchmarkTraceWriter

HIGH_VARIANCE_THRESHOLD = 0.2
PENDING_OUTPUT = "PENDING_OUTPUT"


def partition_events(events: list[Any], batch_size: int) -> list[list[Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    return [events[i : i + batch_size] for i in range(0, len(events), batch_size)]


def load_answers(events_raw_path: Path | str) -> dict[str, Any]:
    raw_path = Path(events_raw_path)
    data = json.loads(raw_path.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        return data

    if not isinstance(data, list):
        raise ValueError("events_raw.json must contain a list or dict payload")

    answers: dict[str, Any] = {}
    for item in data:
        if not isinstance(item, dict) or "event_id" not in item:
            raise ValueError("Each events_raw.json entry must include event_id")
        answers[str(item["event_id"])] = item.get("answer")
    return answers


def summarize_variance(event_runs: dict[str, list[Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}

    for event_id, outputs in event_runs.items():
        completed_outputs = [output for output in outputs if output != PENDING_OUTPUT]
        pending_runs = len(outputs) - len(completed_outputs)

        if not outputs:
            summary[event_id] = {
                "runs": 0,
                "completed_runs": 0,
                "pending_runs": 0,
                "variance_state": "no_runs",
                "baseline_output": None,
                "disagreement_ratio": 0.0,
                "is_high_variance": False,
            }
            continue

        if not completed_outputs:
            summary[event_id] = {
                "runs": len(outputs),
                "completed_runs": 0,
                "pending_runs": pending_runs,
                "variance_state": "pending",
                "baseline_output": None,
                "disagreement_ratio": None,
                "is_high_variance": None,
            }
            continue

        counts = Counter(completed_outputs)
        majority_count = max(counts.values())
        denominator = max(1, len(completed_outputs) - 1)
        disagreement_ratio = (len(completed_outputs) - majority_count) / denominator

        summary[event_id] = {
            "runs": len(outputs),
            "completed_runs": len(completed_outputs),
            "pending_runs": pending_runs,
            "variance_state": "computed",
            "baseline_output": completed_outputs[0],
            "disagreement_ratio": disagreement_ratio,
            "is_high_variance": disagreement_ratio > HIGH_VARIANCE_THRESHOLD,
        }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue ECN-BENCH OpenRouter benchmark events")
    parser.add_argument("--seeds-dir", required=True)
    parser.add_argument("--events-raw", required=True)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--trace-out", default="backend/logs/ecnbench_trace.jsonl")
    parser.add_argument("--variance-out", default="backend/logs/variance_summary.json")
    parser.add_argument("--repeat-runs", type=int, default=2)
    args = parser.parse_args()

    if args.repeat_runs <= 0:
        raise ValueError("repeat-runs must be > 0")

    seeds = sorted(Path(args.seeds_dir).glob("*.md"))
    if len(seeds) != 30:
        raise ValueError(f"Expected exactly 30 seed files (.md), got {len(seeds)}")

    answers = load_answers(args.events_raw)
    trace_writer = BenchmarkTraceWriter(args.trace_out)
    event_runs: dict[str, list[str]] = {}

    for batch_index, batch in enumerate(partition_events(seeds, args.batch_size), start=1):
        for seed_path in batch:
            event_id = seed_path.stem
            expected_answer = answers.get(event_id)
            event_runs.setdefault(event_id, [])

            for run_index in range(1, args.repeat_runs + 1):
                event_runs[event_id].append(PENDING_OUTPUT)
                trace_writer.write(
                    {
                        "event_id": event_id,
                        "seed_file": str(seed_path),
                        "batch_index": batch_index,
                        "run_index": run_index,
                        "run_repeats": args.repeat_runs,
                        "expected_answer": expected_answer,
                        "output": PENDING_OUTPUT,
                        "status": "queued",
                    }
                )

    variance_summary = summarize_variance(event_runs)
    variance_out = Path(args.variance_out)
    variance_out.parent.mkdir(parents=True, exist_ok=True)
    variance_out.write_text(
        json.dumps(variance_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
