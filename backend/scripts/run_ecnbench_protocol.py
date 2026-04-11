import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.benchmarks.evaluator import ProbabilityEvaluator
from app.benchmarks.injection_loader import Step30InjectionLoader
from app.benchmarks.protocol import build_step30_scheduled_event, enforce_protocol_constraints, expand_profiles_to_target
from app.benchmarks.role_router import BenchmarkRoleRouter
from app.benchmarks.scoring import brier_score, summarize_condition_scores
from app.utils.benchmark_trace import BenchmarkTraceWriter


def _script_parent(level: int) -> Path | None:
    parents = _SCRIPTS_DIR.parents
    if level < len(parents):
        return parents[level]
    return None


def _default_injection_bank_candidates() -> List[Path]:
    candidates: List[Path] = []
    workspace_root = _script_parent(4)
    if workspace_root is not None:
        candidates.append(workspace_root / "data" / "injections" / "step30_injection_bank.json")
    candidates.append(_PROJECT_ROOT / "data" / "injections" / "step30_injection_bank.json")
    return candidates


def _resolve_default_injection_bank() -> str:
    candidates = _default_injection_bank_candidates()
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


DEFAULT_INJECTION_BANK = _resolve_default_injection_bank()
DEFAULT_OUTPUT_DIR = "backend/logs/benchmark_runs"
CONDITIONS = ("A", "B", "C")
TARGET_AGENT_COUNT = 3000
TOTAL_SIMULATION_HOURS = 60
MINUTES_PER_ROUND = 60


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("ecnbench_%Y%m%dT%H%M%S%fZ")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_text(mapping: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _looks_like_event(record: Mapping[str, Any]) -> bool:
    has_id = any(key in record for key in ("event_id", "id"))
    has_question = any(key in record for key in ("question", "prompt", "text", "title"))
    has_outcome = any(key in record for key in ("outcome", "answer", "label", "ground_truth", "target"))
    return has_id or (has_question and has_outcome)


def _normalize_event_record(record: Mapping[str, Any], fallback_index: int) -> Dict[str, Any]:
    event_id = record.get("event_id") or record.get("id") or f"event-{fallback_index}"
    question = _first_text(record, ("question", "prompt", "text", "title"))
    outcome = _first_text(record, ("outcome", "answer", "label", "ground_truth", "target", "correct_answer"))
    options = record.get("options")
    if options is None:
        options = record.get("choices")
    if options is None:
        options = record.get("answers")
    if isinstance(options, dict):
        options = list(options.values())
    elif isinstance(options, tuple):
        options = list(options)
    elif options is not None and not isinstance(options, list):
        options = [options]

    normalized = dict(record)
    normalized["event_id"] = str(event_id)
    normalized["question"] = question or str(record.get("question") or "")
    normalized["outcome"] = outcome or str(record.get("outcome") or record.get("answer") or "")
    normalized["answer"] = normalized["outcome"]
    if options is not None:
        normalized["options"] = options
    elif "options" not in normalized:
        normalized["options"] = []
    return normalized


def _collect_events(payload: Any, *, _fallback_index: List[int] | None = None) -> List[Dict[str, Any]]:
    if _fallback_index is None:
        _fallback_index = [0]

    events: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            events.extend(_collect_events(item, _fallback_index=_fallback_index))
        return events

    if isinstance(payload, dict):
        if _looks_like_event(payload):
            _fallback_index[0] += 1
            events.append(_normalize_event_record(payload, _fallback_index[0]))
            return events

        if payload and all(not isinstance(value, (dict, list, tuple)) for value in payload.values()):
            for key, value in payload.items():
                _fallback_index[0] += 1
                events.append(
                    _normalize_event_record(
                        {
                            "event_id": key,
                            "answer": value,
                        },
                        _fallback_index[0],
                    )
                )
            return events

        for value in payload.values():
            events.extend(_collect_events(value, _fallback_index=_fallback_index))
        return events

    return events


def load_events_from_raw(events_raw_path: Path | str, limit: int | None = None) -> List[Dict[str, Any]]:
    raw_path = Path(events_raw_path)
    payload = _read_json(raw_path)
    events = _collect_events(payload)
    if limit is not None:
        return events[:limit]
    return events


def build_condition_matrix(events: List[Mapping[str, Any]], repeats: int) -> List[Dict[str, Any]]:
    if repeats <= 0:
        raise ValueError("repeats must be > 0")

    matrix: List[Dict[str, Any]] = []
    for event in events:
        event_id = str(event["event_id"])
        for condition, repeat in product(CONDITIONS, range(1, repeats + 1)):
            matrix.append(
                {
                    "event_id": event_id,
                    "condition": condition,
                    "repeat": repeat,
                }
            )
    return matrix


def load_seed_files(seeds_dir: Path | str) -> List[Path]:
    directory = Path(seeds_dir)
    if not directory.exists():
        raise FileNotFoundError(f"seeds-dir does not exist: {directory}")
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"No seed files found in {directory}")
    return files


def _sanitize_identifier(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.lower())
    cleaned = cleaned.strip("_") or "seed"
    if cleaned[0].isdigit():
        cleaned = f"seed_{cleaned}"
    return cleaned


def _seed_text_excerpt(seed_path: Path, max_chars: int = 2000) -> str:
    return seed_path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def _seed_preview(seed_path: Path, max_chars: int = 600) -> str:
    text = _seed_text_excerpt(seed_path, max_chars=max_chars)
    preview = " ".join(text.split())
    return preview[:max_chars]


def build_base_profile(seed_path: Path, index: int) -> Dict[str, Any]:
    stem = seed_path.stem or f"seed-{index}"
    title = stem.replace("_", " ").replace("-", " ").strip().title() or f"Seed {index}"
    preview = _seed_preview(seed_path)
    username = _sanitize_identifier(stem)
    persona = _seed_text_excerpt(seed_path, max_chars=4000).strip() or preview or f"Seed profile derived from {seed_path.name}"
    if not preview:
        preview = persona[:200]

    return {
        "user_id": index,
        "username": f"{username}_{index}",
        "name": title,
        "realname": title,
        "bio": preview or title,
        "persona": persona,
        "age": 30,
        "gender": "other",
        "mbti": "ISTJ",
        "country": "US",
        "profession": "Participant",
        "interested_topics": [],
        "karma": 1000,
        "friend_count": 100,
        "follower_count": 150,
        "statuses_count": 500,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "entity_name": title,
        "entity_uuid": f"{_sanitize_identifier(stem)}-{index}",
        "entity_type": "person",
        "activity_level": 0.5,
        "source_seed_file": str(seed_path),
    }


def build_profiles(seeds_dir: Path | str, target_count: int = TARGET_AGENT_COUNT) -> List[Dict[str, Any]]:
    seed_files = load_seed_files(seeds_dir)
    base_profiles = [build_base_profile(seed_path, index) for index, seed_path in enumerate(seed_files)]
    expanded_profiles = expand_profiles_to_target(base_profiles, target_count=target_count)

    for index, profile in enumerate(expanded_profiles):
        base_profile = base_profiles[index % len(base_profiles)]
        profile["agent_id"] = profile["user_id"]
        profile["entity_name"] = f"{base_profile['name']} #{profile['user_id']}"
        profile["entity_uuid"] = f"{base_profile['entity_uuid']}-{profile['user_id']}"
        profile["activity_level"] = base_profile.get("activity_level", 0.5)
        profile["source_seed_file"] = base_profile["source_seed_file"]
    return expanded_profiles


def write_profiles(profile_dir: Path, profiles: List[Dict[str, Any]]) -> tuple[Path, Path]:
    twitter_path = profile_dir / "twitter_profiles.csv"
    reddit_path = profile_dir / "reddit_profiles.json"

    twitter_fields = ["user_id", "name", "username", "user_char", "description"]
    with twitter_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=twitter_fields)
        writer.writeheader()
        for profile in profiles:
            user_char = f"{profile.get('bio', '')} {profile.get('persona', '')}".strip()
            user_char = " ".join(user_char.split())
            description = " ".join(str(profile.get("bio", "")).split())
            writer.writerow(
                {
                    "user_id": profile["user_id"],
                    "name": profile["name"],
                    "username": profile["username"],
                    "user_char": user_char,
                    "description": description,
                }
            )

    reddit_profiles = []
    for profile in profiles:
        reddit_profiles.append(
            {
                "user_id": profile["user_id"],
                "username": profile["username"],
                "name": profile["realname"],
                "bio": profile.get("bio", ""),
                "persona": profile.get("persona", ""),
                "karma": profile.get("karma", 1000),
                "created_at": profile.get("created_at"),
                "age": profile.get("age", 30),
                "gender": profile.get("gender", "other"),
                "mbti": profile.get("mbti", "ISTJ"),
                "country": profile.get("country", "US"),
                "profession": profile.get("profession", "Participant"),
                "interested_topics": profile.get("interested_topics", []),
            }
        )

    reddit_path.write_text(json.dumps(reddit_profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    return twitter_path, reddit_path


def build_simulation_config(event: Mapping[str, Any], condition: str, profiles: List[Dict[str, Any]], injection_loader: Step30InjectionLoader) -> Dict[str, Any]:
    scheduled_events: List[Dict[str, Any]] = []
    if condition in ("B", "C"):
        payload = injection_loader.get_payload(str(event["event_id"]), condition)
        scheduled_events.append(build_step30_scheduled_event(payload, poster_agent_id=0))

    config = {
        "event_id": str(event["event_id"]),
        "event_question": event.get("question", ""),
        "truth": event.get("outcome") or event.get("answer", ""),
        "time_config": {
            "total_simulation_hours": TOTAL_SIMULATION_HOURS,
            "minutes_per_round": MINUTES_PER_ROUND,
        },
        "agent_configs": [
            {
                "agent_id": profile["agent_id"],
                "entity_name": profile["entity_name"],
                "entity_uuid": profile["entity_uuid"],
                "entity_type": profile["entity_type"],
                "activity_level": profile["activity_level"],
                "name": profile["name"],
                "username": profile["username"],
                "bio": profile["bio"],
                "persona": profile["persona"],
                "source_seed_file": profile["source_seed_file"],
            }
            for profile in profiles
        ],
        "event_config": {
            "initial_posts": [],
            "scheduled_events": scheduled_events,
            "hot_topics": [],
            "narrative_direction": "",
        },
    }
    enforce_protocol_constraints(config)
    return config


def write_simulation_config(run_dir: Path, config: Dict[str, Any]) -> Path:
    config_path = run_dir / "simulation_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def _extract_tail_text(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def build_evidence_text(simulation_log_path: Path, seed_path: Path) -> str:
    log_excerpt = _extract_tail_text(simulation_log_path)
    seed_excerpt = _seed_text_excerpt(seed_path)
    parts = []
    if log_excerpt:
        parts.append(f"Simulation log excerpt:\n{log_excerpt}")
    if seed_excerpt:
        parts.append(f"Seed excerpt ({seed_path.name}):\n{seed_excerpt}")
    return "\n\n".join(parts)


def build_event_result_row(
    event: Mapping[str, Any],
    condition: str,
    repeat: int,
    *,
    simulation_status: str,
    simulation_completed: bool,
    evaluation_completed: bool,
    probabilities: Mapping[str, float] | None,
    brier: float | None,
    error: str | None = None,
    seed_file: str | None = None,
    evidence_text: str | None = None,
) -> Dict[str, Any]:
    full_simulation_completed = bool(simulation_completed and evaluation_completed and not error)
    return {
        "event_id": str(event["event_id"]),
        "question": event.get("question", ""),
        "ground_truth": event.get("outcome") or event.get("answer", ""),
        "options": event.get("options", []),
        "condition": condition,
        "repeat": repeat,
        "seed_file": seed_file,
        "simulation_status": simulation_status,
        "full_simulation_completed": full_simulation_completed,
        "probabilities": dict(probabilities) if isinstance(probabilities, Mapping) else None,
        "brier": brier,
        "error": error,
        "evidence_text": evidence_text,
    }


def _format_exception(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _run_simulation_subprocess(python_exe: str, config_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            python_exe,
            "scripts/run_parallel_simulation.py",
            "--config",
            str(config_path),
            "--max-rounds",
            str(TOTAL_SIMULATION_HOURS),
            "--no-wait",
        ],
        cwd=str(_BACKEND_DIR),
        capture_output=True,
        text=True,
    )


def _evaluate_row(
    event: Mapping[str, Any],
    condition: str,
    evidence_text: str,
) -> tuple[Dict[str, float], float]:
    router = BenchmarkRoleRouter.from_config()
    evaluator = ProbabilityEvaluator(router)
    evaluation = evaluator.evaluate(event.get("question", ""), condition, evidence_text)
    probabilities = evaluation.get("normalized_probabilities") or evaluation.get("probabilities")
    if not isinstance(probabilities, Mapping):
        raise ValueError("Evaluator did not return probabilities")

    ground_truth = event.get("outcome") or event.get("answer", "")
    if not isinstance(ground_truth, str) or not ground_truth.strip():
        raise ValueError("Event is missing a ground-truth outcome")

    normalized_probabilities = {str(label): float(value) for label, value in probabilities.items()}
    return normalized_probabilities, brier_score(normalized_probabilities, ground_truth)


def summarize_event_results(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    completed_rows = [row for row in rows if row.get("full_simulation_completed")]
    simulation_failed_count = sum(1 for row in rows if row.get("simulation_status") == "simulation_failed")
    evaluation_failed_count = sum(1 for row in rows if row.get("simulation_status") == "evaluation_failed")
    summary = summarize_condition_scores([row for row in completed_rows if row.get("brier") is not None])
    summary.update(
        {
            "total_rows": len(rows),
            "full_simulation_completed_count": len(completed_rows),
            "full_simulation_failed_count": len(rows) - len(completed_rows),
            "simulation_success_count": len(rows) - simulation_failed_count,
            "simulation_failure_count": simulation_failed_count,
            "evaluation_success_count": len(completed_rows),
            "evaluation_failure_count": evaluation_failed_count,
        }
    )
    return summary


def write_summary(run_dir: Path, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = summarize_event_results(rows)
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ECN-BENCH protocol benchmark end-to-end")
    parser.add_argument("--seeds-dir", required=True)
    parser.add_argument("--events-raw", required=True)
    parser.add_argument("--injection-bank", default=DEFAULT_INJECTION_BANK)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--events", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--python-exe", default=sys.executable)
    args = parser.parse_args()

    if args.events <= 0:
        raise ValueError("--events must be > 0")
    if args.repeats <= 0:
        raise ValueError("--repeats must be > 0")

    events = load_events_from_raw(args.events_raw, limit=args.events)
    seed_files = load_seed_files(args.seeds_dir)
    profiles = build_profiles(args.seeds_dir, target_count=TARGET_AGENT_COUNT)
    injection_loader = Step30InjectionLoader(args.injection_bank)

    output_root = Path(args.output_dir)
    run_id = _utc_run_id()
    run_dir = output_root / run_id
    traces_dir = run_dir / "traces"
    run_dir.mkdir(parents=True, exist_ok=True)
    traces_dir.mkdir(parents=True, exist_ok=True)

    trace_writer = BenchmarkTraceWriter(traces_dir / "execution.jsonl")
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seeds_dir": str(Path(args.seeds_dir)),
        "events_raw": str(Path(args.events_raw)),
        "injection_bank": str(Path(args.injection_bank)),
        "output_dir": str(run_dir),
        "events_requested": args.events,
        "events_loaded": len(events),
        "repeats": args.repeats,
        "conditions": list(CONDITIONS),
        "python_exe": args.python_exe,
        "total_agents": TARGET_AGENT_COUNT,
        "total_simulation_hours": TOTAL_SIMULATION_HOURS,
        "minutes_per_round": MINUTES_PER_ROUND,
        "seed_files": [str(path) for path in seed_files],
        "event_ids": [str(event["event_id"]) for event in events],
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    event_results: List[Dict[str, Any]] = []
    condition_matrix = build_condition_matrix(events, args.repeats)
    event_lookup = {str(event["event_id"]): event for event in events}
    event_index_lookup = {str(event["event_id"]): index for index, event in enumerate(events)}

    for matrix_row in condition_matrix:
        event = event_lookup[matrix_row["event_id"]]
        condition = matrix_row["condition"]
        repeat = matrix_row["repeat"]
        seed_path = seed_files[event_index_lookup[matrix_row["event_id"]] % len(seed_files)]
        unit_id = f"{event['event_id']}_{condition}_r{repeat}"
        unit_dir = run_dir / unit_id
        unit_dir.mkdir(parents=True, exist_ok=True)

        trace_writer.write(
            {
                "event_id": event["event_id"],
                "condition": condition,
                "repeat": repeat,
                "unit_id": unit_id,
                "status": "starting",
            }
        )

        row_error: str | None = None
        probabilities: Dict[str, float] | None = None
        brier: float | None = None
        simulation_status = "simulation_failed"
        simulation_completed = False
        evaluation_completed = False
        evidence_text = ""

        try:
            config = build_simulation_config(event, condition, profiles, injection_loader)
            config["run_unit"] = {
                "run_id": run_id,
                "unit_id": unit_id,
                "seed_file": str(seed_path),
            }
            config_path = write_simulation_config(unit_dir, config)
            write_profiles(unit_dir, profiles)

            completed = _run_simulation_subprocess(args.python_exe, config_path)
            simulation_completed = completed.returncode == 0
            if not simulation_completed:
                row_error = completed.stderr.strip() or completed.stdout.strip() or f"run_parallel_simulation.py exited with {completed.returncode}"
                simulation_status = "simulation_failed"
                trace_writer.write(
                    {
                        "event_id": event["event_id"],
                        "condition": condition,
                        "repeat": repeat,
                        "unit_id": unit_id,
                        "status": simulation_status,
                        "returncode": completed.returncode,
                        "stderr": completed.stderr[-2000:],
                    }
                )
            else:
                simulation_status = "completed"
                simulation_log_path = unit_dir / "simulation.log"
                evidence_text = build_evidence_text(simulation_log_path, seed_path)
                try:
                    probabilities, brier = _evaluate_row(event, condition, evidence_text)
                    evaluation_completed = True
                    trace_writer.write(
                        {
                            "event_id": event["event_id"],
                            "condition": condition,
                            "repeat": repeat,
                            "unit_id": unit_id,
                            "status": "completed",
                            "probabilities": probabilities,
                            "brier": brier,
                        }
                    )
                except Exception as exc:
                    simulation_status = "evaluation_failed"
                    row_error = _format_exception(exc)
                    trace_writer.write(
                        {
                            "event_id": event["event_id"],
                            "condition": condition,
                            "repeat": repeat,
                            "unit_id": unit_id,
                            "status": simulation_status,
                            "error": row_error,
                        }
                    )
        except Exception as exc:
            row_error = _format_exception(exc)
            trace_writer.write(
                {
                    "event_id": event["event_id"],
                    "condition": condition,
                    "repeat": repeat,
                    "unit_id": unit_id,
                    "status": "failed",
                    "error": row_error,
                }
            )

        event_results.append(
            build_event_result_row(
                event,
                condition,
                repeat,
                simulation_status=simulation_status,
                simulation_completed=simulation_completed,
                evaluation_completed=evaluation_completed,
                probabilities=probabilities,
                brier=brier,
                error=row_error,
                seed_file=str(seed_path),
                evidence_text=evidence_text or None,
            )
        )

    (run_dir / "event_results.json").write_text(json.dumps(event_results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary(run_dir, event_results)


if __name__ == "__main__":
    main()
