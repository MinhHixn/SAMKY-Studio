import argparse
import csv
import json
import math
import os
import subprocess
import sys
from functools import lru_cache
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Protocol

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.benchmarks.evaluator import ProbabilityEvaluator
from app.benchmarks.injection_loader import Step30InjectionLoader
from app.benchmarks.leakage import validate_leakage_preflight
from app.benchmarks.orchestrator import BenchmarkRunOrchestrator, ProtocolConditionExecutor
from app.benchmarks.protocol import build_step30_scheduled_event, enforce_protocol_constraints, expand_profiles_to_target
from app.benchmarks.layer23_registry import load_layer23_config
from app.benchmarks.seed_metadata import load_seed_metadata
from app.benchmarks.role_router import BenchmarkRoleRouter
from app.config import Config
from app.benchmarks.weight_registry import load_benchmark_weights
from app.benchmarks.scoring import (
    brier_score,
    compute_composite_score,
    compute_weighted_rubric_score,
    summarize_condition_scores,
    summarize_yes_probability,
    summarize_directional_accuracy,
    summarize_strict_contract,
    summarize_weighted_rubric_score,
    summarize_rubric_artifacts,
)
from app.benchmarks.statistics import (
    aggregate_calibration_counts,
    assign_probability_bracket,
    compute_cohens_d_with_ci,
    compute_power_analysis,
    ranked_probability_score,
    write_calibration_plot,
)
from app.benchmarks.phase1_baselines import (
    BASELINE_AGENT_IDS,
    build_baseline_scores,
    validate_polymarket_opening_prior,
)
from app.benchmarks.phase1_registry import load_phase1_config
from app.benchmarks.phase1_telemetry import (
    compute_round_jsd_trace,
    is_monotonic_nonincreasing_with_epsilon,
)
from app.utils.benchmark_trace import BenchmarkTraceWriter


def _default_injection_bank_candidates() -> List[Path]:
    candidates: List[Path] = []
    seen: set[str] = set()
    for ancestor in (_SCRIPTS_DIR, *_SCRIPTS_DIR.parents):
        candidate = (ancestor / "data" / "injections" / "step30_injection_bank.json").resolve(strict=False)
        candidate_key = str(candidate).lower()
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        candidates.append(candidate)
    return candidates


def _resolve_default_injection_bank() -> str:
    candidates = _default_injection_bank_candidates()
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


DEFAULT_INJECTION_BANK = _resolve_default_injection_bank()
DEFAULT_OUTPUT_DIR = _BACKEND_DIR / "logs" / "benchmark_runs"
DEFAULT_BENCHMARK_WEIGHTS_PATH = _BACKEND_DIR / "config" / "benchmark_weights_v1.json"
DEFAULT_PHASE1_CONFIG_PATH = _BACKEND_DIR / "config" / "benchmark_phase1_v1.json"
DEFAULT_LAYER23_CONFIG_PATH = _BACKEND_DIR / "config" / "benchmark_layer23_v1.json"
CONDITIONS = ("A", "B", "C")
TARGET_AGENT_COUNT = 3000
TOTAL_SIMULATION_HOURS = 60
MINUTES_PER_ROUND = 60
SIMULATION_SUBPROCESS_TIMEOUT_SECONDS = TOTAL_SIMULATION_HOURS * 60 * 60

COMPOSITE_SCORE_KEY_MAP = {
    "prediction_accuracy": "prediction_accuracy_score",
    "convergence": "convergence_score",
    "susceptibility": "susceptibility_score",
    "herd_effect": "herd_effect_score",
    "dqi": "deliberation_quality_score",
    "polarization": "polarization_score",
    "info_diversity": "information_diversity_score",
}

EventRecord = Mapping[str, Any]
SimulationConfigBuilder = Callable[[EventRecord, str], Dict[str, Any]]
ConditionEvaluator = Callable[[EventRecord, str, str, BenchmarkRoleRouter], Dict[str, Any]]


class TraceWriterAdapter(Protocol):
    def write(self, payload: Mapping[str, Any]) -> None: ...


class _LazyTraceWriter:
    def __init__(self, path: Path):
        self._path = path
        self._writer: BenchmarkTraceWriter | None = None

    def write(self, payload: Mapping[str, Any]) -> None:
        if self._writer is None:
            self._writer = BenchmarkTraceWriter(self._path)
        self._writer.write(dict(payload))


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("ecnbench_%Y%m%dT%H%M%S%fZ")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_composite_weights() -> Dict[str, float]:
    return load_benchmark_weights(DEFAULT_BENCHMARK_WEIGHTS_PATH)


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


def _looks_like_scalar_event_map(payload: Mapping[str, Any]) -> bool:
    if not payload:
        return False
    if any(isinstance(value, (dict, list, tuple)) for value in payload.values()):
        return False
    event_keys = {
        "event_id",
        "id",
        "question",
        "prompt",
        "text",
        "title",
        "outcome",
        "answer",
        "label",
        "ground_truth",
        "target",
        "correct_answer",
        "options",
        "choices",
        "answers",
    }
    keys = {str(key) for key in payload.keys()}
    non_id_event_keys = event_keys - {"event_id", "id"}
    return bool(keys & non_id_event_keys) or keys.issubset({"event_id", "id"})


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
        if payload and all(not isinstance(value, (dict, list, tuple)) for value in payload.values()):
            if _looks_like_scalar_event_map(payload) and _looks_like_event(payload):
                _fallback_index[0] += 1
                events.append(_normalize_event_record(payload, _fallback_index[0]))
            return events

        if _looks_like_event(payload):
            _fallback_index[0] += 1
            events.append(_normalize_event_record(payload, _fallback_index[0]))
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


def validate_injection_coverage(
    events: Iterable[Mapping[str, Any]], injection_loader: Step30InjectionLoader
) -> None:
    preflight_failures: list[str] = []
    seen_event_ids: set[str] = set()
    for event in events:
        event_id = str(event["event_id"])
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)

        if not injection_loader.has_event(event_id):
            preflight_failures.append(f"{event_id}: missing event id in injection bank")
            continue

        for condition in ("B", "C"):
            try:
                payload = injection_loader.get_payload(event_id, condition)
                if payload is None or not isinstance(payload, Mapping):
                    raise ValueError("payload must be a JSON object")
            except Exception as exc:  # noqa: BLE001 - aggregate all payload failures into one preflight error
                detail = str(exc.args[0]) if getattr(exc, "args", None) else str(exc)
                preflight_failures.append(f"{event_id} [{condition}]: {detail}")

    if preflight_failures:
        failures = "\n- ".join(preflight_failures)
        raise ValueError(f"Injection payload preflight failed:\n- {failures}")


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
    files = sorted(path for path in directory.rglob("*") if path.is_file() and path.name != "metadata.json")
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
    profile_dir.mkdir(parents=True, exist_ok=True)
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


def build_simulation_config(
    event: Mapping[str, Any],
    condition: str,
    profiles: List[Dict[str, Any]],
    injection_loader: Step30InjectionLoader,
    *,
    llm_model: str | None = None,
) -> Dict[str, Any]:
    question = _first_text(event, ("question", "prompt", "text", "title"))
    scheduled_events: List[Dict[str, Any]] = []
    if condition in ("B", "C"):
        payload = injection_loader.get_payload(str(event["event_id"]), condition)
        scheduled_events.append(build_step30_scheduled_event(payload, poster_agent_id=0))

    config = {
        "event_id": str(event["event_id"]),
        "event_question": question,
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
            "initial_posts": (
                [{"poster_agent_id": 0, "content": question}]
                if question
                else []
            ),
            "scheduled_events": scheduled_events,
            "hot_topics": [],
            "narrative_direction": "",
        },
    }
    if llm_model:
        config["llm_model"] = llm_model
    enforce_protocol_constraints(config)
    return config


def write_simulation_config(run_dir: Path, config: Dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "simulation_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def _extract_tail_text(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def _finite_float_or_none(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return numeric


def _extract_weighted_rubric_score(validated_scales: Mapping[str, Any] | None) -> float | None:
    if not isinstance(validated_scales, Mapping):
        return None

    top_level = _finite_float_or_none(validated_scales.get("weighted_rubric_score"))
    if top_level is not None:
        return top_level

    scores = validated_scales.get("scores")
    if isinstance(scores, Mapping):
        return _finite_float_or_none(scores.get("weighted_rubric_score"))
    return None


def _extract_yes_probability(probabilities: Mapping[str, Any] | None) -> float | None:
    if not isinstance(probabilities, Mapping):
        return None
    for label, raw_value in probabilities.items():
        if isinstance(label, str) and label.strip().casefold() == "yes":
            return _finite_float_or_none(raw_value)
    return None


def _normalize_probabilities(probabilities: Mapping[str, Any] | None) -> Dict[str, float] | None:
    if not isinstance(probabilities, Mapping):
        return None
    normalized: Dict[str, float] = {}
    for label, raw_value in probabilities.items():
        numeric = _finite_float_or_none(raw_value)
        if numeric is None:
            continue
        normalized[str(label)] = float(numeric)
    return normalized or None


def _resolve_ordered_labels(
    event: Mapping[str, Any],
    probabilities: Mapping[str, Any] | None,
) -> List[str]:
    options = event.get("options")
    if isinstance(options, list) and options:
        labels = [str(option) for option in options]
    elif isinstance(probabilities, Mapping) and probabilities:
        labels = sorted(str(label) for label in probabilities.keys())
    else:
        raise ValueError("Unable to resolve ordered labels for RPS")
    if len(set(labels)) != len(labels):
        raise ValueError("Ordered labels must be unique for RPS")
    return labels


def _resolve_event_label(event: Mapping[str, Any]) -> str | None:
    for key in ("outcome", "answer", "label"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _compute_convergence_telemetry(
    unit_dir: Path,
    phase1_cfg: Mapping[str, Any],
    *,
    resolved_label: str | None,
) -> tuple[list[float], bool]:
    checkpoints = [int(checkpoint) for checkpoint in phase1_cfg["telemetry_checkpoints"]]
    trace = compute_round_jsd_trace(
        unit_dir,
        checkpoints=checkpoints,
        min_parsed_probability_ratio=float(phase1_cfg["min_parsed_probability_ratio"]),
        resolved_label=resolved_label,
    )
    epsilon = float(phase1_cfg["jsd_monotonic_tolerance_epsilon"])
    return trace, is_monotonic_nonincreasing_with_epsilon(trace, epsilon)


def _simulation_failure_error(unit_dir: Path, *, timeout_seconds: int | None = None, returncode: int | None = None) -> str:
    parts: List[str] = []
    if timeout_seconds is not None:
        parts.append(f"run_parallel_simulation.py timed out after {timeout_seconds}s")
    if returncode is not None:
        parts.append(f"run_parallel_simulation.py exited with returncode {returncode}")

    log_tail = _extract_tail_text(unit_dir / "simulation.log")
    if log_tail:
        parts.append(f"simulation.log tail:\n{log_tail}")

    return "\n\n".join(parts) if parts else "run_parallel_simulation.py failed"


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
    mcq_dimensions: Mapping[str, Any] | None = None,
    validated_scales: Mapping[str, Any] | None = None,
    directional_accuracy: float | None = None,
    weighted_rubric_score: float | None = None,
    yes_probability: float | None = None,
    strict_contract: bool | None = True,
    error: str | None = None,
    seed_file: str | None = None,
    evidence_text: str | None = None,
    simulation_executed: bool = True,
    injection_direction: str | None = None,
    signed_delta: float | None = None,
    belief_update_failure: bool | None = None,
    evaluator_noisy_dimensions: Any = None,
    round_jsd: list[float] | None = None,
    convergence_monotonic: bool | None = None,
    baseline_scores: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    event_id = str(event["event_id"])
    ground_truth = event.get("outcome") or event.get("answer", "")
    normalized_probabilities = _normalize_probabilities(probabilities)
    directional_correct: int | None = None
    predicted_label: str | None = None
    if normalized_probabilities and isinstance(ground_truth, str) and ground_truth.strip():
        predicted_label = max(
            normalized_probabilities.items(),
            key=lambda item: (item[1], item[0]),
        )[0]
        directional_correct = int(predicted_label == ground_truth.strip())
    resolved_directional_accuracy = _finite_float_or_none(directional_accuracy)
    if resolved_directional_accuracy is None and directional_correct is not None:
        resolved_directional_accuracy = float(directional_correct)
    if resolved_directional_accuracy is None:
        resolved_directional_accuracy = 0.0

    resolved_weighted_rubric_score = _finite_float_or_none(weighted_rubric_score)
    if resolved_weighted_rubric_score is None:
        resolved_weighted_rubric_score = _extract_weighted_rubric_score(validated_scales)
    resolved_yes_probability = _finite_float_or_none(yes_probability)
    if resolved_yes_probability is None:
        resolved_yes_probability = _extract_yes_probability(probabilities)
    rps: float | None = None
    calibration_bracket: str | None = None
    calibration_predicted_probability: float | None = None
    calibration_hit: int | None = None
    if normalized_probabilities and isinstance(ground_truth, str) and ground_truth.strip():
        ordered_labels = _resolve_ordered_labels(event, normalized_probabilities)
        rps = ranked_probability_score(normalized_probabilities, ground_truth.strip(), ordered_labels)
        if predicted_label is not None:
            calibration_predicted_probability = _finite_float_or_none(
                normalized_probabilities.get(predicted_label)
            )
            if calibration_predicted_probability is not None:
                calibration_bracket = assign_probability_bracket(calibration_predicted_probability)
                calibration_hit = int(predicted_label == ground_truth.strip())
    if seed_file:
        try:
            seed_metadata = load_seed_metadata(Path(seed_file).parent)
        except FileNotFoundError:
            seed_metadata = None
        except ValueError as exc:
            metadata_error = _format_exception(exc)
            error = f"{error}; {metadata_error}" if error else metadata_error
            seed_metadata = None
        if isinstance(seed_metadata, Mapping):
            if injection_direction is None:
                injection_direction = seed_metadata.get("injection_direction")
            if signed_delta is None:
                metadata_signed_delta = seed_metadata.get("signed_delta")
                if metadata_signed_delta is not None:
                    if (
                        isinstance(metadata_signed_delta, bool)
                        or not isinstance(metadata_signed_delta, (int, float))
                    ):
                        metadata_error = "metadata.json signed_delta must be a number"
                        error = f"{error}; {metadata_error}" if error else metadata_error
                    else:
                        signed_delta = float(metadata_signed_delta)
            if belief_update_failure is None:
                metadata_belief_update_failure = seed_metadata.get("belief_update_failure")
                if metadata_belief_update_failure is None or isinstance(metadata_belief_update_failure, bool):
                    belief_update_failure = metadata_belief_update_failure
                else:
                    metadata_error = "metadata.json belief_update_failure must be a boolean"
                    error = f"{error}; {metadata_error}" if error else metadata_error
    resolved_round_jsd = round_jsd
    if round_jsd is not None:
        if not isinstance(round_jsd, list) or len(round_jsd) != 5:
            length_detail = len(round_jsd) if isinstance(round_jsd, list) else "non-list"
            telemetry_error = f"round_jsd must have length 5 (got {length_detail})"
            error = f"{error}; Telemetry error: {telemetry_error}" if error else f"Telemetry error: {telemetry_error}"
            resolved_round_jsd = None
            convergence_monotonic = None
    full_simulation_completed = bool(simulation_completed and evaluation_completed and not error)
    return {
        "event_id": event_id,
        "unit_id": f"{event_id}_{condition}_r{repeat}",
        "question": event.get("question", ""),
        "ground_truth": event.get("outcome") or event.get("answer", ""),
        "options": event.get("options", []),
        "condition": condition,
        "repeat": repeat,
        "seed_file": seed_file,
        "simulation_status": simulation_status,
        "full_simulation_completed": full_simulation_completed,
        "simulation_executed": simulation_executed,
        "probabilities": dict(probabilities) if isinstance(probabilities, Mapping) else None,
        "brier": brier,
        "directional_accuracy": resolved_directional_accuracy,
        "directional_correct": directional_correct,
        "weighted_rubric_score": resolved_weighted_rubric_score,
        "yes_probability": resolved_yes_probability,
        "rps": rps,
        "calibration_bracket": calibration_bracket,
        "calibration_predicted_probability": calibration_predicted_probability,
        "calibration_hit": calibration_hit,
        "strict_contract": strict_contract,
        "injection_direction": injection_direction,
        "signed_delta": signed_delta,
        "belief_update_failure": belief_update_failure,
        "evaluator_noisy_dimensions": evaluator_noisy_dimensions,
        "mcq_dimensions": dict(mcq_dimensions) if isinstance(mcq_dimensions, Mapping) else None,
        "validated_scales": dict(validated_scales) if isinstance(validated_scales, Mapping) else None,
        "round_jsd": list(resolved_round_jsd) if isinstance(resolved_round_jsd, list) else resolved_round_jsd,
        "convergence_monotonic": convergence_monotonic,
        "baseline_scores": dict(baseline_scores) if isinstance(baseline_scores, Mapping) else None,
        "error": error,
        "evidence_text": evidence_text,
    }


def _format_exception(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _deterministic_mode_config() -> Dict[str, Any]:
    return {
        "benchmark_mode": Config.BENCHMARK_MODE,
        "temperature": Config.BENCHMARK_TEMPERATURE,
        "seed": Config.BENCHMARK_SEED,
    }


def _benchmark_subprocess_env(router: BenchmarkRoleRouter) -> Dict[str, str]:
    env = os.environ.copy()
    env["LLM_API_KEY"] = router.api_key
    env["LLM_BASE_URL"] = router.base_url
    env["LLM_MODEL_NAME"] = router.model_for("benchmark")
    env["BENCHMARK_MODE"] = "true" if Config.BENCHMARK_MODE else "false"
    env["BENCHMARK_TEMPERATURE"] = str(Config.BENCHMARK_TEMPERATURE)
    env["BENCHMARK_SEED"] = str(Config.BENCHMARK_SEED)
    return env


def _run_simulation_subprocess(
    python_exe: str,
    config_path: Path,
    router: BenchmarkRoleRouter,
    *,
    log_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    run_kwargs = {
        "cwd": str(_BACKEND_DIR),
        "text": True,
        "timeout": SIMULATION_SUBPROCESS_TIMEOUT_SECONDS,
        "env": _benchmark_subprocess_env(router),
    }
    if log_path is None:
        run_kwargs["stdout"] = subprocess.DEVNULL
        run_kwargs["stderr"] = subprocess.DEVNULL
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
            **run_kwargs,
        )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        run_kwargs["stdout"] = log_file
        run_kwargs["stderr"] = log_file
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
            **run_kwargs,
        )


def _evaluate_row(
    event: Mapping[str, Any],
    condition: str,
    evidence_text: str,
    router: BenchmarkRoleRouter,
) -> Dict[str, Any]:
    evaluator = ProbabilityEvaluator(router)
    evaluation = evaluator.evaluate(event.get("question", ""), condition, evidence_text)
    probabilities = evaluation.get("normalized_probabilities") or evaluation.get("probabilities")
    if not isinstance(probabilities, Mapping):
        raise ValueError("Evaluator did not return probabilities")
    mcq_dimensions = evaluation.get("mcq_dimensions")
    validated_scales = evaluation.get("validated_scales")
    if not isinstance(mcq_dimensions, Mapping):
        raise ValueError("Evaluator did not return mcq_dimensions")
    if not isinstance(validated_scales, Mapping):
        raise ValueError("Evaluator did not return validated_scales")
    evaluator_noisy_dimensions = [str(dimension) for dimension in _as_list(evaluation.get("evaluator_noisy_dimensions"))]

    ground_truth = event.get("outcome") or event.get("answer", "")
    if not isinstance(ground_truth, str) or not ground_truth.strip():
        raise ValueError("Event is missing a ground-truth outcome")

    normalized_probabilities = {str(label): float(value) for label, value in probabilities.items()}
    directional_accuracy = _finite_float_or_none(evaluation.get("directional_accuracy"))
    if directional_accuracy is None:
        predicted_label = max(
            ((str(label), float(value)) for label, value in normalized_probabilities.items()),
            key=lambda item: (item[1], item[0]),
        )[0]
        directional_accuracy = float(predicted_label == ground_truth)

    normalized_validated_scales = dict(validated_scales)
    raw_scores = normalized_validated_scales.get("scores")
    if isinstance(raw_scores, Mapping):
        normalized_scores = {str(label): float(value) for label, value in raw_scores.items()}
    else:
        normalized_scores = {}

    weighted_rubric_score = _finite_float_or_none(evaluation.get("weighted_rubric_score"))
    if weighted_rubric_score is None:
        weighted_rubric_score = _finite_float_or_none(normalized_scores.get("weighted_rubric_score"))
    if weighted_rubric_score is None:
        weighted_rubric_score = compute_weighted_rubric_score(mcq_dimensions)
    if weighted_rubric_score is not None:
        normalized_scores["weighted_rubric_score"] = weighted_rubric_score
    normalized_validated_scales["scores"] = normalized_scores

    return {
        "probabilities": normalized_probabilities,
        "brier": brier_score(normalized_probabilities, ground_truth),
        "mcq_dimensions": dict(mcq_dimensions),
        "validated_scales": normalized_validated_scales,
        "directional_accuracy": directional_accuracy,
        "weighted_rubric_score": weighted_rubric_score,
        "evaluator_noisy_dimensions": evaluator_noisy_dimensions,
    }


def _summarize_composite_score(rows: List[Dict[str, Any]], noisy_dimensions: Iterable[str] | None) -> Dict[str, Any]:
    dimension_values: Dict[str, List[float]] = {dimension: [] for dimension in COMPOSITE_SCORE_KEY_MAP}
    for row in rows:
        validated_scales = row.get("validated_scales")
        scores = validated_scales.get("scores") if isinstance(validated_scales, Mapping) else None
        if not isinstance(scores, Mapping):
            continue
        for dimension, score_key in COMPOSITE_SCORE_KEY_MAP.items():
            numeric = _finite_float_or_none(scores.get(score_key))
            if numeric is not None:
                dimension_values[dimension].append(numeric)

    averaged_scores = {
        dimension: round(sum(values) / len(values), 6)
        for dimension, values in dimension_values.items()
        if values
    }
    return compute_composite_score(averaged_scores, _load_composite_weights(), noisy_dimensions=noisy_dimensions)


def _summarize_evaluator_reliability(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    noisy_dimensions: set[str] = set()
    for row in rows:
        for dimension in _as_list(row.get("evaluator_noisy_dimensions")):
            dimension_key = str(dimension).strip()
            if dimension_key:
                noisy_dimensions.add(dimension_key)
    return {"evaluator_noisy": sorted(noisy_dimensions)}


def _summarize_rps(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    per_condition: Dict[str, List[float]] = {condition: [] for condition in CONDITIONS}
    overall_values: List[float] = []
    for row in rows:
        value = _finite_float_or_none(row.get("rps"))
        if value is None:
            continue
        overall_values.append(value)
        condition = str(row.get("condition", ""))
        if condition in per_condition:
            per_condition[condition].append(value)

    by_condition = {
        condition: round(sum(values) / len(values), 6) if values else 0.0
        for condition, values in per_condition.items()
    }
    overall = round(sum(overall_values) / len(overall_values), 6) if overall_values else 0.0
    return {"overall": overall, "by_condition": by_condition}


def _summarize_calibration(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    per_condition: Dict[str, List[tuple[float, bool]]] = {condition: [] for condition in CONDITIONS}
    overall_items: List[tuple[float, bool]] = []
    for row in rows:
        probability = _finite_float_or_none(row.get("calibration_predicted_probability"))
        hit = row.get("calibration_hit")
        if probability is None or hit is None:
            continue
        if not isinstance(hit, (bool, int)):
            raise ValueError("calibration_hit must be boolean or integer")
        overall_items.append((probability, bool(hit)))
        condition = str(row.get("condition", ""))
        if condition in per_condition:
            per_condition[condition].append((probability, bool(hit)))

    return {
        "overall": aggregate_calibration_counts(overall_items),
        "by_condition": {
            condition: aggregate_calibration_counts(values)
            for condition, values in per_condition.items()
        },
    }


def _collect_metric_values(rows: List[Dict[str, Any]], condition: str, metric: str) -> List[float]:
    values: List[float] = []
    for row in rows:
        if str(row.get("condition", "")) != condition:
            continue
        value = _finite_float_or_none(row.get(metric))
        if value is not None:
            values.append(value)
    return values


def summarize_event_results(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    completed_rows = [row for row in rows if row.get("simulation_status") == "completed"]
    simulation_failed_count = sum(1 for row in rows if row.get("simulation_status") == "simulation_failed")
    evaluation_failed_count = sum(1 for row in rows if row.get("simulation_status") == "evaluation_failed")
    summary = summarize_condition_scores([row for row in completed_rows if row.get("brier") is not None])
    summary["rubric"] = summarize_rubric_artifacts(completed_rows)
    summary["directional_accuracy"] = summarize_directional_accuracy(completed_rows)
    summary["weighted_rubric_score"] = summarize_weighted_rubric_score(completed_rows)
    summary["evaluator_reliability"] = _summarize_evaluator_reliability(completed_rows)
    evaluator_reliability = summary["evaluator_reliability"]
    noisy_dimensions: List[str] = []
    if isinstance(evaluator_reliability, Mapping):
        evaluator_noisy = evaluator_reliability.get("evaluator_noisy", [])
        if isinstance(evaluator_noisy, list):
            noisy_dimensions = [str(dimension) for dimension in evaluator_noisy]
    try:
        summary["composite_score"] = _summarize_composite_score(completed_rows, noisy_dimensions)
    except ValueError as exc:
        if str(exc) != "No stable dimensions remain for composite score":
            raise
        summary["composite_score"] = {
            "composite_score": None,
            "renormalized_weights": {},
            "excluded_dimensions": noisy_dimensions,
            "included_dimensions": [],
        }
    yes_probability_summary = summarize_yes_probability(completed_rows)
    summary["content_susceptibility"] = {
        "mean_yes_probability": {
            "overall": yes_probability_summary["overall"],
            "by_condition": yes_probability_summary["by_condition"],
        },
        "delta": {
            "B_minus_C": round(
                yes_probability_summary["by_condition"]["B"] - yes_probability_summary["by_condition"]["C"],
                6,
            ),
        },
    }
    summary["rps"] = _summarize_rps(completed_rows)
    summary["calibration"] = _summarize_calibration(completed_rows)
    brier_a = _collect_metric_values(completed_rows, "A", "brier")
    brier_b = _collect_metric_values(completed_rows, "B", "brier")
    actual_n = min(len(brier_a), len(brier_b))
    effect_size: Dict[str, Any] = {
        "cohens_d": None,
        "ci_lower": None,
        "ci_upper": None,
        "confidence": 0.95,
        "metric": "brier",
    }
    power_analysis: Dict[str, Any] = {
        "required_n_for_target_power": None,
        "actual_n": actual_n,
        "apriori_power": None,
        "achieved_power": None,
    }
    if len(brier_a) >= 2 and len(brier_b) >= 2:
        effect_size = compute_cohens_d_with_ci(brier_a, brier_b)
        effect_size["metric"] = "brier"
        power_analysis = compute_power_analysis(
            actual_n,
            observed_sigma=effect_size["pooled_std"],
        )
    summary["effect_size"] = effect_size
    summary["power_analysis"] = power_analysis
    round_jsd_means = [
        sum(values) / len(values)
        for values in (row.get("round_jsd") for row in completed_rows)
        if isinstance(values, list) and values
    ]
    summary["convergence"] = {
        "mean_round_jsd": round(sum(round_jsd_means) / len(round_jsd_means), 6) if round_jsd_means else None,
        "monotonic_count": sum(
            1 for row in completed_rows if row.get("convergence_monotonic") is True
        ),
    }
    summary["strict_contract"] = summarize_strict_contract(completed_rows)
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
    calibration = summary.get("calibration")
    if isinstance(calibration, Mapping):
        overall = calibration.get("overall")
        if isinstance(overall, Mapping):
            plot_path = run_dir / "calibration_curve.png"
            calibration["plot_path"] = write_calibration_plot(overall, plot_path)
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
    parser.add_argument("--trace-out")
    parser.add_argument("--python-exe", default=sys.executable)
    args = parser.parse_args()

    if args.events <= 0:
        raise ValueError("--events must be > 0")
    if args.repeats <= 0:
        raise ValueError("--repeats must be > 0")

    router = BenchmarkRoleRouter.from_config()
    benchmark_model = router.model_for("benchmark")
    events = load_events_from_raw(args.events_raw, limit=args.events)
    seed_files = load_seed_files(args.seeds_dir)
    profiles = build_profiles(args.seeds_dir, target_count=TARGET_AGENT_COUNT)
    injection_loader = Step30InjectionLoader(args.injection_bank)
    validate_injection_coverage(events, injection_loader)
    layer23_cfg = load_layer23_config(DEFAULT_LAYER23_CONFIG_PATH)
    phase1_cfg = load_phase1_config(DEFAULT_PHASE1_CONFIG_PATH)
    for event in events:
        validate_polymarket_opening_prior(
            event,
            prior_sum_tolerance=float(phase1_cfg["prior_sum_tolerance"]),
        )
    baseline_agent_ids = list(phase1_cfg["baseline_agents"])
    implemented_baseline_agent_ids = list(BASELINE_AGENT_IDS)
    if baseline_agent_ids != implemented_baseline_agent_ids:
        raise ValueError(
            "phase1 baseline_agents must match implemented baseline scoring agents: "
            f"expected {implemented_baseline_agent_ids}, got {baseline_agent_ids}"
        )

    validate_leakage_preflight(
        events,
        seed_files,
        layer23_cfg,
        seed_base_dir=args.seeds_dir,
    )

    output_root = Path(args.output_dir)
    run_id = _utc_run_id()
    run_dir = output_root / run_id
    traces_dir = run_dir / "traces"

    trace_path = Path(args.trace_out) if args.trace_out else traces_dir / "execution.jsonl"
    trace_writer = _LazyTraceWriter(trace_path)
    condition_matrix = build_condition_matrix(events, args.repeats)
    expected_run_units = len(condition_matrix)
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
        "trace_out": str(trace_path),
        "seed_files": [str(path) for path in seed_files],
        "event_ids": [str(event["event_id"]) for event in events],
        "workflow_mode": "abc-per-event",
        "benchmark_model": benchmark_model,
        "expected_run_units": expected_run_units,
        "weights_schema_version": "v1",
        "mcq_prompt_version": "v1",
        "deterministic_mode": _deterministic_mode_config(),
        "phase1_config_version": phase1_cfg["version"],
        "telemetry_checkpoints": list(phase1_cfg["telemetry_checkpoints"]),
        "jsd_monotonic_tolerance_epsilon": float(phase1_cfg["jsd_monotonic_tolerance_epsilon"]),
        "baseline_agents": list(baseline_agent_ids),
        "preflight_market_prior_check": "pass",
        "leakage_check": "pass",
    }

    event_lookup = {str(event["event_id"]): event for event in events}
    event_index_lookup = {str(event["event_id"]): index for index, event in enumerate(events)}
    executor = ProtocolConditionExecutor(
        router=router,
        python_exe=args.python_exe,
        profiles=profiles,
        seed_files=seed_files,
        event_index_lookup=event_index_lookup,
        trace_writer=trace_writer,
        simulation_timeout_seconds=SIMULATION_SUBPROCESS_TIMEOUT_SECONDS,
        simulation_runner=_run_simulation_subprocess,
        simulation_failure_error_builder=_simulation_failure_error,
        config_writer=write_simulation_config,
        profile_writer=write_profiles,
        evidence_builder=build_evidence_text,
        row_builder=build_event_result_row,
        telemetry_builder=lambda unit_dir, event: _compute_convergence_telemetry(
            unit_dir,
            phase1_cfg,
            resolved_label=_resolve_event_label(event),
        ),
        baseline_scores_builder=build_baseline_scores,
        exception_formatter=_format_exception,
    )
    orchestrator = BenchmarkRunOrchestrator(executor=executor)
    orchestrator.run(
        run_id=run_id,
        output_root=output_root,
        events=events,
        repeats=args.repeats,
        build_condition_matrix=lambda _events, _repeats: list(condition_matrix),
        event_lookup=event_lookup,
        write_summary=write_summary,
        config_builder=lambda event, condition: build_simulation_config(
            event,
            condition,
            profiles,
            injection_loader,
            llm_model=benchmark_model,
        ),
        evaluator=_evaluate_row,
        manifest=manifest,
    )

    if args.trace_out:
        default_trace_path = traces_dir / "execution.jsonl"
        if default_trace_path.exists():
            default_trace_path.unlink()


if __name__ == "__main__":
    main()
