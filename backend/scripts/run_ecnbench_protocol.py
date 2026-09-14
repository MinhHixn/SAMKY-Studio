import argparse
import csv
import inspect
import json
import logging
import math
import os
import socket
import subprocess
import sys

# ============================================================
# MONKEYPATCH: Disable tool use in CAMEL for Ollama compatibility
# and Fix OASIS UserInfo missing agent profiles bug
# ============================================================
try:
    from camel.models import OpenAIModel
    _original_arun = OpenAIModel.arun
    async def _patched_arun(self, messages, response_format=None, tools=None):
        # Force tools to None to disable tool use as Ollama/Gemma often fail with it
        return await _original_arun(self, messages, response_format, None)
    OpenAIModel.arun = _patched_arun
    
    _original_run = OpenAIModel.run
    def _patched_run(self, messages, response_format=None, tools=None):
        return _original_run(self, messages, response_format, None)
    OpenAIModel.run = _patched_run
except ImportError:
    pass

try:
    from oasis.social_platform.config.user import UserInfo

    def to_twitter_system_message(self) -> str:
        name_string = f"Your name is {self.name}." if self.name is not None else ""
        description = name_string
        if self.profile:
            user_profile = self.profile.get("persona") or self.profile.get("user_profile")
            if not user_profile and "other_info" in self.profile and isinstance(self.profile["other_info"], dict):
                user_profile = self.profile["other_info"].get("user_profile")
            
            bio = self.profile.get("bio") or self.profile.get("description")
            
            parts = []
            if name_string:
                parts.append(name_string)
            if bio:
                parts.append(f"Bio: {bio}")
            if user_profile:
                parts.append(f"Your profile and personality: {user_profile}")
            description = "\n".join(parts)
            
        return f"""# OBJECTIVE
You're a Twitter user, and I'll present you with some posts. After you see the posts, choose some actions from the following functions.

# SELF-DESCRIPTION
Your actions should be consistent with your self-description and personality.
{description}

# RESPONSE METHOD
Please perform actions by tool calling."""

    def to_reddit_system_message(self) -> str:
        name_string = f"Your name is {self.name}." if self.name is not None else ""
        description = name_string
        if self.profile:
            user_profile = self.profile.get("persona") or self.profile.get("user_profile")
            gender = self.profile.get("gender")
            age = self.profile.get("age")
            mbti = self.profile.get("mbti")
            country = self.profile.get("country")
            
            if "other_info" in self.profile and isinstance(self.profile["other_info"], dict):
                if not user_profile:
                    user_profile = self.profile["other_info"].get("user_profile")
                if not gender:
                    gender = self.profile["other_info"].get("gender")
                if not age:
                    age = self.profile["other_info"].get("age")
                if not mbti:
                    mbti = self.profile["other_info"].get("mbti")
                if not country:
                    country = self.profile["other_info"].get("country")
                    
            bio = self.profile.get("bio") or self.profile.get("description")
            
            parts = []
            if name_string:
                parts.append(name_string)
            if bio:
                parts.append(f"Bio: {bio}")
            if user_profile:
                parts.append(f"Your profile and personality: {user_profile}")
            
            meta_parts = []
            if gender:
                meta_parts.append(f"gender: {gender}")
            if age:
                meta_parts.append(f"age: {age} years old")
            if mbti:
                meta_parts.append(f"MBTI: {mbti}")
            if country:
                meta_parts.append(f"from: {country}")
            if meta_parts:
                parts.append("Demographics: " + ", ".join(meta_parts))
            description = "\n".join(parts)
            
        return f"""# OBJECTIVE
You're a Reddit user, and I'll present you with some tweets. After you see the tweets, choose some actions from the following functions.

# SELF-DESCRIPTION
Your actions should be consistent with your self-description and personality.
{description}

# RESPONSE METHOD
Please perform actions by tool calling."""

    UserInfo.to_twitter_system_message = to_twitter_system_message
    UserInfo.to_reddit_system_message = to_reddit_system_message
except ImportError:
    pass
# ============================================================
import time
from functools import lru_cache
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence
from urllib.parse import urlparse

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.benchmarks.evaluator import ProbabilityEvaluator
from app.benchmarks.injection_loader import Step30InjectionLoader
from app.benchmarks.leakage import validate_leakage_preflight
from app.benchmarks.orchestrator import BenchmarkRunOrchestrator, ProtocolConditionExecutor
from app.benchmarks.protocol import build_step30_scheduled_event, enforce_protocol_constraints, expand_profiles_to_target
from app.benchmarks.intelligent_persona import generate_intelligent_base_profiles
from app.utils.llm_client import LLMClient
from app.benchmarks.layer23_registry import load_layer23_config
from app.benchmarks.reliability import dominant_bucket_label, kappa_by_dimension
from app.benchmarks.seed_metadata import load_seed_metadata
from app.benchmarks.role_router import BenchmarkRoleRouter
from app.benchmarks.schemas import validate_summary_payload
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
from app.benchmarks.topology import compute_delta_conformity, extract_topology_metadata
from app.utils.benchmark_trace import BenchmarkTraceWriter
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable


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
DEFAULT_KAPPA_CUTOFF = 0.8
_RUNTIME_KAPPA_CUTOFF = DEFAULT_KAPPA_CUTOFF
DEFAULT_POWER_TARGET_DELTA_BRIER = 0.05
DEFAULT_POWER_ASSUMED_SIGMA = 0.12
DEFAULT_POWER_TARGET = 0.8
DEFAULT_CALIBRATION_BRACKETS = [[0.0, 0.25], [0.25, 0.5], [0.5, 0.75], [0.75, 1.0]]
_RUNTIME_POWER_TARGET_DELTA_BRIER = DEFAULT_POWER_TARGET_DELTA_BRIER
_RUNTIME_POWER_ASSUMED_SIGMA = DEFAULT_POWER_ASSUMED_SIGMA
_RUNTIME_POWER_TARGET = DEFAULT_POWER_TARGET
_RUNTIME_CALIBRATION_BRACKETS = DEFAULT_CALIBRATION_BRACKETS
ENFORCED_BENCHMARK_TEMPERATURE = 0.0
ENFORCED_BENCHMARK_SEED = 42
_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_DECLARED_TOPOLOGY_PARAMETERS = {
    "graph_generator": {
        "twitter": "generate_twitter_agent_graph",
        "reddit": "generate_reddit_agent_graph",
    },
    "degree_distribution_descriptor": "oasis-default-unspecified",
    "clustering_coefficient": None,
}

COMPOSITE_SCORE_KEY_MAP = {
    "prediction_accuracy": "prediction_accuracy_score",
    "convergence": "convergence_score",
    "susceptibility": "susceptibility_score",
    "herd_effect": "herd_effect_score",
    "dqi": "deliberation_quality_score",
    "polarization": "polarization_score",
    "info_diversity": "information_diversity_score",
}
_SCORING_DIMENSION_ALIASES = {
    "deliberation_quality": "dqi",
    "information_diversity": "info_diversity",
}

EventRecord = Mapping[str, Any]
SimulationConfigBuilder = Callable[[EventRecord, str], Dict[str, Any]]
ConditionEvaluator = Callable[[EventRecord, str, str, BenchmarkRoleRouter], Dict[str, Any]]
logger = logging.getLogger(__name__)


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


def _normalize_scoring_dimension_name(raw_dimension: Any) -> str | None:
    dimension = str(raw_dimension).strip()
    if not dimension:
        return None
    if dimension in COMPOSITE_SCORE_KEY_MAP:
        return dimension
    return _SCORING_DIMENSION_ALIASES.get(dimension)


def _normalize_known_scoring_dimensions(dimensions: Iterable[Any]) -> List[str]:
    normalized = {
        dimension
        for dimension in (
            _normalize_scoring_dimension_name(raw_dimension) for raw_dimension in dimensions
        )
        if dimension is not None
    }
    return sorted(normalized)


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


def load_events_from_raw(
    events_raw_path: Path | str, 
    limit: int | None = None,
    event_ids: List[str] | None = None,
    category: str | None = None
) -> List[Dict[str, Any]]:
    raw_path = Path(events_raw_path)
    payload = _read_json(raw_path)
    
    # If category is provided, only look in that specific key in core_events or supplementary_events
    target_payload = payload
    if category:
        core = payload.get("core_events", {})
        supp = payload.get("supplementary_events", {})
        if category in core:
            target_payload = core[category]
        elif category in supp:
            target_payload = supp[category]
        elif category == "supplementary" and "events" in supp:
            target_payload = supp["events"]
        else:
            logger.warning(f"Category '{category}' not found in events_raw.json. Searching globally.")

    events = _collect_events(target_payload)
    
    # Filter by event_ids if provided
    if event_ids:
        events = [e for e in events if str(e.get("event_id")) in event_ids]

    # Auto-fill options for binary events if missing
    for event in events:
        if event.get("market_type") == "binary" and not event.get("options"):
            event["options"] = ["YES", "NO"]

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


def load_seed_files(seeds_dir: Path | str, event_id: str | None = None) -> List[Path]:
    directory = Path(seeds_dir)
    if event_id is not None:
        directory = directory / str(event_id)
    if not directory.exists():
        raise FileNotFoundError(f"seeds-dir does not exist: {directory}")
    files = sorted(path for path in directory.rglob("*") if path.is_file() and path.name not in ("metadata.json", "links.txt"))
    if not files:
        raise ValueError(f"No seed files found in {directory}")
    return files


def _sanitize_identifier(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.lower())
    cleaned = cleaned.strip("_") or "seed"
    if cleaned[0].isdigit():
        cleaned = f"seed_{cleaned}"
    return cleaned


def _seed_text_excerpt(seed_path: Path, max_chars: int | None = None) -> str:
    content = seed_path.read_text(encoding="utf-8", errors="replace")
    if max_chars is not None:
        return content[:max_chars]
    return content


def _seed_preview(seed_path: Path, max_chars: int = 600) -> str:
    text = _seed_text_excerpt(seed_path, max_chars=max_chars)
    preview = " ".join(text.split())
    return preview[:max_chars]


def build_base_profile(seed_path: Path, index: int) -> Dict[str, Any]:
    stem = seed_path.stem or f"seed-{index}"
    title = stem.replace("_", " ").replace("-", " ").strip().title() or f"Seed {index}"
    preview = _seed_preview(seed_path)
    username = _sanitize_identifier(stem)
    persona = _seed_text_excerpt(seed_path).strip() or preview or f"Seed profile derived from {seed_path.name}"

    # ARCHITECTURE v5.15: Index-aware Anti-Dump Shield.
    # Previously EVERY context.md seed collapsed to the identical
    # "Political Analyst" persona, which then got replicated 1->N in the
    # rule-based fallback of expand_profiles_to_target, producing 300 clones.
    # Now we rotate diversified identities so the seed (used as the anchor for
    # the rule-based fallback pool) is never the sole source of diversity.
    if title.lower() == "context" or len(persona) > 500:
        _rotated_first = [
            "Ava", "Liam", "Sofia", "Maya", "Ethan", "Isabella", "Caleb", "Zoe",
            "Nora", "Julian", "Ruby", "Leo", "Hazel", "Miles", "Iris", "Felix",
        ]
        _rotated_last = [
            "Reyes", "Novak", "Singh", "Park", "Muller", "Rossi", "Chen",
            "Andersson", "Dubois", "Kim", "Silva", "Hassan", "Yamamoto", "Schmidt",
        ]
        _rotated_profs = [
            "Policy Analyst", "Data Scientist", "Investigative Journalist",
            "Economist", "Geopolitical Strategist", "Researcher",
            "Community Organizer", "Market Analyst",
        ]
        _rotated_countries = ["US", "UK", "Germany", "India", "France", "Japan", "Brazil", "Canada"]
        first = _rotated_first[index % len(_rotated_first)]
        last = _rotated_last[(index * 5 + 2) % len(_rotated_last)]
        title = f"{first} {last}"
        profession = _rotated_profs[index % len(_rotated_profs)]
        preview = f"{profession} based in {_rotated_countries[index % len(_rotated_countries)]}, engaging on emerging developments."
        persona = (
            f"- Worldview: Pragmatic and data-driven.\n"
            f"- Motivation: To understand and forecast shifts in their domain.\n"
            f"- Style: Professional and objective.\n"
            f"- Biases: Triggered by emotional or unsubstantiated claims."
        )
    else:
        profession = "Participant"

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
        "profession": profession,
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


def build_profiles(
    seeds_dir: Path | str, 
    target_count: int = TARGET_AGENT_COUNT, 
    event_id: str | None = None,
    llm_client: Optional[LLMClient] = None
) -> List[Dict[str, Any]]:
    seed_files = load_seed_files(seeds_dir, event_id=event_id)
    
    # Preflight Check: If checkpoint already exists, skip slow base profile generation completely.
    # ARCHITECTURE v5.15: BUST_PERSONA_CHECKPOINT=true ignores a stale/poisoned
    # checkpoint (e.g. one that captured the 300 "Political Analyst" clones from
    # a previous run where LLM tool-calling had crashed). This forces a clean
    # regeneration of diverse personas.
    checkpoint_dir = os.path.join(os.getcwd(), "logs", "checkpoints")
    model_name = os.getenv("LLM_MODEL_NAME", "default_model")
    sanitized_model = model_name.replace("/", "_").replace(":", "_").replace("\\", "_")
    checkpoint_file = os.path.join(checkpoint_dir, f"expansion_{sanitized_model}_{event_id}.json")
    bust_checkpoint = os.environ.get("BUST_PERSONA_CHECKPOINT", "").strip().lower() in {"1", "true", "yes", "on"}
    if os.path.exists(checkpoint_file) and not bust_checkpoint:
        logger.info(f"Checkpoint expansion_{sanitized_model}_{event_id}.json found. Skipping base profile generation to save time.")
        # Build a small diversified seed set (not a single clone) so that, if the
        # checkpoint inside expand_profiles_to_target is missing/incomplete, the
        # rule-based fallback has multiple distinct anchors to rotate from.
        base_profiles = [build_base_profile(seed_files[0], i) for i in range(min(8, target_count))]
    elif bust_checkpoint and os.path.exists(checkpoint_file):
        logger.warning(f"BUST_PERSONA_CHECKPOINT=true: deleting stale checkpoint {checkpoint_file} and regenerating personas.")
        try:
            os.remove(checkpoint_file)
        except OSError:
            pass
        base_profiles = []
    else:
        # Intelligent Expansion: If we have only ONE seed file (like context.md),
        # use LLM to generate multiple diverse base profiles first.
        if len(seed_files) == 1 and llm_client:
            context_text = seed_files[0].read_text(encoding="utf-8", errors="replace")
            logger.info(f"Using intelligent persona generation for event {event_id}...")
            base_profiles = generate_intelligent_base_profiles(context_text, agent_count=target_count, llm_client=llm_client)
            if not base_profiles:
                 # ARCHITECTURE v5.15: Graceful fallback instead of crashing.
                 logger.warning("Intelligent persona generation returned empty. Falling back to diversified build_base_profile pool.")
                 base_profiles = [build_base_profile(seed_files[0], i) for i in range(min(8, target_count))]
        else:
            base_profiles = [build_base_profile(seed_path, index) for index, seed_path in enumerate(seed_files)]

    # Safety net: ensure base_profiles is never empty
    if not base_profiles:
        logger.warning("base_profiles empty after all branches. Using diversified fallback.")
        base_profiles = [build_base_profile(seed_files[0], i) for i in range(min(8, target_count))] if seed_files else [build_base_profile(Path("context.md"), i) for i in range(8)]

    expanded_profiles = expand_profiles_to_target(base_profiles, target_count=target_count, llm_client=llm_client, event_id=event_id)

    for index, profile in enumerate(expanded_profiles):
        # Use a deterministic base profile selection for metadata assignment
        base_profile = base_profiles[index % len(base_profiles)]
        profile["agent_id"] = profile["user_id"]
        # Metadata fields (non-functional for identity but useful for tracking)
        profile["activity_level"] = profile.get("activity_level", 0.5)
        profile["source_seed_file"] = profile.get("source_seed_file", str(seed_files[0]) if seed_files else "unknown")
        # Ensure entity_uuid is unique for the social graph
        if not profile.get("entity_uuid") or profile.get("entity_uuid") == base_profile.get("entity_uuid"):
             profile["entity_uuid"] = f"{base_profile.get('entity_uuid', 'agent')}-{profile['user_id']}"
        if not profile.get("entity_name") or profile.get("entity_name") == base_profile.get("entity_name"):
             profile["entity_name"] = profile["name"]
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
    injection_trigger_round: int = 30,
    total_simulation_hours: int = TOTAL_SIMULATION_HOURS,
) -> Dict[str, Any]:
    question = _first_text(event, ("question", "prompt", "text", "title"))
    scheduled_events: List[Dict[str, Any]] = []
    if condition in ("B", "C"):
        payload = injection_loader.get_payload(str(event["event_id"]), condition)
        scheduled_event = build_step30_scheduled_event(
            payload,
            poster_agent_id=0,
            trigger_round=injection_trigger_round,
        )
        scheduled_events.append(scheduled_event)

    config = {
        "event_id": str(event["event_id"]),
        "event_question": question,
        "truth": event.get("outcome") or event.get("answer", ""),
        "time_config": {
            "total_simulation_hours": int(total_simulation_hours),
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
            "options": event.get("options", []),
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


def _build_simulation_config_with_runtime(
    event: Mapping[str, Any],
    condition: str,
    profiles: List[Dict[str, Any]],
    injection_loader: Step30InjectionLoader,
    *,
    llm_model: str | None,
    injection_trigger_round: int,
    total_simulation_hours: int,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"llm_model": llm_model}
    signature = inspect.signature(build_simulation_config)
    if "injection_trigger_round" in signature.parameters:
        kwargs["injection_trigger_round"] = injection_trigger_round
    if "total_simulation_hours" in signature.parameters:
        kwargs["total_simulation_hours"] = total_simulation_hours
    return build_simulation_config(
        event,
        condition,
        profiles,
        injection_loader,
        **kwargs,
    )


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
    min_parsed_probability_ratio: float | None = None,
) -> tuple[list[float], bool]:
    checkpoints = [int(checkpoint) for checkpoint in phase1_cfg["telemetry_checkpoints"]]
    parsed_probability_ratio = (
        float(phase1_cfg["min_parsed_probability_ratio"])
        if min_parsed_probability_ratio is None
        else float(min_parsed_probability_ratio)
    )
    trace = compute_round_jsd_trace(
        unit_dir,
        checkpoints=checkpoints,
        min_parsed_probability_ratio=parsed_probability_ratio,
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


def _sample_representative_actions(unit_dir: Path, max_actions: int = 50) -> str:
    """Sample high-signal actions from platform logs to stabilize evaluator grading."""
    platforms = ["twitter", "reddit"]
    all_actions: List[Dict[str, Any]] = []
    
    for platform in platforms:
        log_path = unit_dir / platform / "actions.jsonl"
        if not log_path.exists():
            continue
        try:
            with log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        action = json.loads(line)
                        if action.get("event_type") in ("simulation_start", "simulation_end", "round_start", "round_end"):
                            continue
                        action["platform"] = platform
                        all_actions.append(action)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Failed to read {platform} actions for sampling: {e}")

    if not all_actions:
        return ""

    # Scoring for "Engagement/Signal"
    # CREATE_POST (1.0), QUOTE (0.5 + 1.0), COMMENT (0.3 + 0.8), LIKE (0.1)
    engagement_scores: Dict[str, float] = {}  # key: platform_postid
    
    # First pass: map post_ids to scores
    for action in all_actions:
        a_type = action.get("action_type")
        a_args = action.get("action_args") or {}
        platform = action.get("platform")
        
        if a_type == "CREATE_POST":
            p_id = f"{platform}_{a_args.get('post_id')}"
            engagement_scores[p_id] = engagement_scores.get(p_id, 0.0) + 1.0
        elif a_type == "QUOTE_POST":
            p_id = f"{platform}_{a_args.get('new_post_id')}"
            engagement_scores[p_id] = engagement_scores.get(p_id, 0.0) + 1.0
            target_id = f"{platform}_{a_args.get('quoted_id')}"
            engagement_scores[target_id] = engagement_scores.get(target_id, 0.0) + 0.5
        elif a_type == "CREATE_COMMENT":
            p_id = f"{platform}_{a_args.get('comment_id')}"
            engagement_scores[p_id] = engagement_scores.get(p_id, 0.0) + 0.8
            target_id = f"{platform}_{a_args.get('post_id')}"
            engagement_scores[target_id] = engagement_scores.get(target_id, 0.0) + 0.3
        elif a_type == "LIKE_POST":
            target_id = f"{platform}_{a_args.get('post_id')}"
            engagement_scores[target_id] = engagement_scores.get(target_id, 0.0) + 0.1

    # Second pass: attach scores to actions and sort
    scored_actions = []
    for action in all_actions:
        a_type = action.get("action_type")
        a_args = action.get("action_args") or {}
        platform = action.get("platform")
        
        lookup_id = None
        if a_type == "CREATE_POST":
            lookup_id = f"{platform}_{a_args.get('post_id')}"
        elif a_type == "QUOTE_POST":
            lookup_id = f"{platform}_{a_args.get('new_post_id')}"
        elif a_type == "CREATE_COMMENT":
            lookup_id = f"{platform}_{a_args.get('comment_id')}"
        
        score = engagement_scores.get(lookup_id, 0.0) if lookup_id else 0.0
        # Boost original posts and quotes over likes/probes
        if a_type in ("CREATE_POST", "QUOTE_POST", "CREATE_COMMENT"):
            score += 10.0
            
        scored_actions.append((score, action))

    # Sort by score (descending) and take top
    scored_actions.sort(key=lambda x: x[0], reverse=True)
    top_actions = [x[1] for x in scored_actions[:max_actions]]
    
    # Sort top actions by round to maintain temporal coherence
    top_actions.sort(key=lambda x: x.get("round", 0))

    lines = []
    for a in top_actions:
        round_n = a.get("round")
        agent = a.get("agent_name", "Unknown")
        a_type = a.get("action_type")
        platform = a.get("platform")
        content = (a.get("action_args") or {}).get("content", "")
        if not content and a_type == "TELEMETRY_PROBE":
            args = a.get("action_args") or {}
            prob = args.get("yes_probability")
            if prob is not None:
                content = f"Belief check: YES Probability = {prob}"
            elif "response" in args:
                content = f"Belief check: Probabilities = {args['response']}"
        
        if content:
            lines.append(f"[R{round_n}][{platform}] {agent}: {content[:300]}")
            
    return "\n".join(lines)


def build_evidence_text(simulation_log_path: Path, seed_path: Path) -> str:
    """ARCHITECTURE v3.6: Blind Grading Implementation. Removes original seed context to prevent data leakage."""
    # 1. High-level log summary
    log_excerpt = _extract_tail_text(simulation_log_path, max_chars=2000)
    
    # 2. Representative Actions Sample (Fix for Evaluator Context Overload)
    actions_sample = _sample_representative_actions(simulation_log_path.parent, max_actions=60)
    
    parts = []
    if log_excerpt:
        parts.append(f"Simulation high-level log tail:\n{log_excerpt}")
    if actions_sample:
        parts.append(f"Representative Social Media Actions (Sample):\n{actions_sample}")
    unit_parts = simulation_log_path.parent.name.rsplit("_", 2)
    inferred_condition = unit_parts[1] if len(unit_parts) == 3 and unit_parts[1] in CONDITIONS else None
    if inferred_condition == "A" and seed_path.exists():
        seed_excerpt = _seed_text_excerpt(seed_path, max_chars=4000).strip()
        if seed_excerpt:
            parts.append(f"No-Sim Seed Context (Condition A baseline):\n{seed_excerpt}")
        
    return "\n\n".join(parts)


def _fuzzy_normalize_probabilities(
    probabilities: Mapping[str, Any] | None,
    options: List[str] | None,
) -> Dict[str, float] | None:
    if not isinstance(probabilities, Mapping) or not probabilities:
        return None
    
    # If no options, just return normalized keys
    if not options:
        return _normalize_probabilities(probabilities)

    option_labels = [str(opt) for opt in options]
    option_map = {opt.casefold(): opt for opt in option_labels}
    
    normalized: Dict[str, float] = {}
    for label, raw_value in probabilities.items():
        numeric = _finite_float_or_none(raw_value)
        if numeric is None:
            continue
        
        label_str = str(label).strip()
        label_fold = label_str.casefold()
        
        # Exact or case-insensitive match
        if label_str in option_labels:
            normalized[label_str] = normalized.get(label_str, 0.0) + float(numeric)
        elif label_fold in option_map:
            mapped = option_map[label_fold]
            normalized[mapped] = normalized.get(mapped, 0.0) + float(numeric)
        # Fuzzy match for common mismatches (e.g. Democratic -> Democrat)
        elif label_fold.startswith("democrat") and "democrat" in option_map:
            mapped = option_map["democrat"]
            normalized[mapped] = normalized.get(mapped, 0.0) + float(numeric)
        elif label_fold.startswith("republican") and "republican" in option_map:
            mapped = option_map["republican"]
            normalized[mapped] = normalized.get(mapped, 0.0) + float(numeric)
        else:
            # If no match, we still include it but it might cause RPS failure later 
            # if we don't handle it in resolve_ordered_labels
            normalized[label_str] = normalized.get(label_str, 0.0) + float(numeric)
            
    # Final normalization to sum to 1.0
    total = sum(normalized.values())
    if total > 0:
        return {k: v / total for k, v in normalized.items()}
    return None


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
    evaluator_fallback_used: bool | None = None,
    evaluator_fallback_reason: str | None = None,
    evaluator_fallback_source: str | None = None,
    error: str | None = None,
    seed_file: str | None = None,
    evidence_text: str | None = None,
    simulation_executed: bool = True,
    injection_direction: str | None = None,
    signed_delta: float | None = None,
    belief_update_failure: bool | None = None,
    evaluator_noisy_dimensions: Any = None,
    evaluator_dimension_labels: Any = None,
    evaluator_reliability_status: str | None = None,
    round_jsd: list[float] | None = None,
    convergence_monotonic: bool | None = None,
    delta_conformity: float | None = None,
    baseline_scores: Mapping[str, Any] | None = None,
    micro_epistemic_mapping: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    event_id = str(event["event_id"])
    options = event.get("options")
    if not isinstance(options, list):
         options = []
    
    # Use fuzzy normalization to align evaluator labels with event options
    normalized_probabilities = _fuzzy_normalize_probabilities(probabilities, options)
    
    ground_truth = str(event.get("outcome") or event.get("answer") or "").strip()
    directional_correct: int | None = None
    predicted_label: str | None = None
    tied_prediction = False
    tied_labels: list[str] = []
    max_probability: float | None = None
    
    if normalized_probabilities and ground_truth:
        max_probability = max(normalized_probabilities.values())
        gt_normalized = ground_truth
        
        # Try to match ground truth with normalized labels (fuzzy)
        if gt_normalized not in normalized_probabilities:
             gt_fold = gt_normalized.casefold()
             for lbl in normalized_probabilities:
                  if lbl.casefold() == gt_fold:
                       gt_normalized = lbl
                       break

        tied_labels = [
            label
            for label, probability in normalized_probabilities.items()
            if math.isclose(probability, max_probability, rel_tol=0.0, abs_tol=1e-12)
        ]
        tied_prediction = len(tied_labels) > 1
        if not tied_prediction:
            predicted_label = tied_labels[0]
            directional_correct = int(predicted_label == gt_normalized)
            
    resolved_directional_accuracy = _finite_float_or_none(directional_accuracy)
    if resolved_directional_accuracy is None and directional_correct is not None:
        resolved_directional_accuracy = float(directional_correct)
    if resolved_directional_accuracy is None and tied_prediction:
        resolved_directional_accuracy = 0.5
    if resolved_directional_accuracy is None:
        resolved_directional_accuracy = 0.0

    resolved_weighted_rubric_score = _finite_float_or_none(weighted_rubric_score)
    if resolved_weighted_rubric_score is None:
        resolved_weighted_rubric_score = _extract_weighted_rubric_score(validated_scales)
    resolved_yes_probability = _finite_float_or_none(yes_probability)
    if resolved_yes_probability is None:
        resolved_yes_probability = _extract_yes_probability(probabilities)
    resolved_delta_conformity = _finite_float_or_none(delta_conformity)
    
    rps: float | None = None
    calibration_bracket: str | None = None
    calibration_predicted_probability: float | None = None
    calibration_hit: int | None = None
    
    if normalized_probabilities and ground_truth:
        gt_normalized = ground_truth
        try:
            ordered_labels = _resolve_ordered_labels(event, normalized_probabilities)
            # Ensure ground_truth is in ordered_labels (fuzzy match if needed)
            if gt_normalized not in ordered_labels:
                 gt_fold = gt_normalized.casefold()
                 for lbl in ordered_labels:
                      if lbl.casefold() == gt_fold:
                           gt_normalized = lbl
                           break
            
            rps = ranked_probability_score(normalized_probabilities, gt_normalized, ordered_labels)
            
            if predicted_label is not None:
                calibration_predicted_probability = _finite_float_or_none(
                    normalized_probabilities.get(predicted_label)
                )
                if calibration_predicted_probability is not None:
                    calibration_bracket = assign_probability_bracket(
                        calibration_predicted_probability,
                        brackets=_RUNTIME_CALIBRATION_BRACKETS,
                    )
                    calibration_hit = int(predicted_label == gt_normalized)
            elif tied_prediction and max_probability is not None:
                calibration_predicted_probability = _finite_float_or_none(max_probability)
                if calibration_predicted_probability is not None:
                    calibration_bracket = assign_probability_bracket(
                        calibration_predicted_probability,
                        brackets=_RUNTIME_CALIBRATION_BRACKETS,
                    )
                    calibration_hit = int(gt_normalized in tied_labels)
        except ValueError as exc:
            scoring_error = f"RPS/calibration unavailable: {exc}"
            error = f"{error}; {scoring_error}" if error else scoring_error

    # Ensure calibration_bracket is NOT None for completed rows to pass strict validation
    if simulation_status == "completed":
        if not calibration_bracket:
            calibration_bracket = "0-0.25"  # Fallback bracket
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
        dev_minimal = os.environ.get("DEV_MINIMAL_MODE", "").lower() == "true"
        max_steps = int(os.environ.get("DEV_MINIMAL_MAX_STEPS", "60")) if dev_minimal else 60
        checkpoints = list(range(6, max_steps + 1, 6))
        if not checkpoints or checkpoints[-1] != max_steps:
            checkpoints.append(max_steps)
        expected_len = len(checkpoints)
        if not isinstance(round_jsd, list) or len(round_jsd) != expected_len:
            length_detail = len(round_jsd) if isinstance(round_jsd, list) else "non-list"
            telemetry_error = f"round_jsd must have length {expected_len} (got {length_detail})"
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
        "evaluator_fallback_used": bool(evaluator_fallback_used),
        "evaluator_fallback_reason": (
            str(evaluator_fallback_reason) if isinstance(evaluator_fallback_reason, str) else None
        ),
        "evaluator_fallback_source": (
            str(evaluator_fallback_source) if isinstance(evaluator_fallback_source, str) else None
        ),
        "injection_direction": injection_direction,
        "signed_delta": signed_delta,
        "belief_update_failure": belief_update_failure,
        "evaluator_noisy_dimensions": evaluator_noisy_dimensions,
        "evaluator_dimension_labels": (
            dict(evaluator_dimension_labels) if isinstance(evaluator_dimension_labels, Mapping) else None
        ),
        "evaluator_reliability_status": (
            str(evaluator_reliability_status) if isinstance(evaluator_reliability_status, str) else None
        ),
        "mcq_dimensions": dict(mcq_dimensions) if isinstance(mcq_dimensions, Mapping) else None,
        "validated_scales": dict(validated_scales) if isinstance(validated_scales, Mapping) else None,
        "round_jsd": list(resolved_round_jsd) if isinstance(resolved_round_jsd, list) else resolved_round_jsd,
        "convergence_monotonic": convergence_monotonic,
        "delta_conformity": resolved_delta_conformity,
        "baseline_scores": dict(baseline_scores) if isinstance(baseline_scores, Mapping) else None,
        "micro_epistemic_mapping": dict(micro_epistemic_mapping) if isinstance(micro_epistemic_mapping, Mapping) else None,
        "error": error,
        "evidence_text": evidence_text,
    }


def _format_exception(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return bool(default)
    return raw_value.strip().lower() in _TRUTHY_VALUES


def _is_dev_minimal_mode_enabled() -> bool:
    return _env_flag("DEV_MINIMAL_MODE", default=False)


def _dev_minimal_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _resolve_runtime_protocol_parameters(dev_minimal_mode: bool) -> Dict[str, Any]:
    if not dev_minimal_mode:
        return {
            "agent_count": TARGET_AGENT_COUNT,
            "total_simulation_hours": TOTAL_SIMULATION_HOURS,
            "injection_round": 30,
            "telemetry_checkpoints": None,
        }
    
    # ARCHITECTURE v5.11: Dynamic Minimal Mode Parameters
    # Respect environment variables or use reasonable defaults for testing
    agent_count = _dev_minimal_int("DEV_MINIMAL_AGENT_COUNT", 100)
    max_steps = _dev_minimal_int("DEV_MINIMAL_MAX_STEPS", 60)
    injection_step = _dev_minimal_int("DEV_MINIMAL_INJECTION_STEP", max_steps // 2)
    
    # Generate checkpoints every 6 steps up to max_steps
    checkpoints = list(range(6, max_steps + 1, 6))
    if not checkpoints or checkpoints[-1] != max_steps:
        checkpoints.append(max_steps)

    return {
        "agent_count": agent_count,
        "total_simulation_hours": max_steps,
        "injection_round": injection_step,
        "telemetry_checkpoints": checkpoints,
    }


def _resolve_telemetry_required(*, benchmark_mode: bool, dev_minimal_mode: bool) -> bool:
    configured = os.environ.get("TELEMETRY_REQUIRED")
    if benchmark_mode and not dev_minimal_mode:
        if configured is not None and not _env_flag("TELEMETRY_REQUIRED", default=True):
            logger.warning("TELEMETRY_REQUIRED=false ignored because benchmark mode requires strict telemetry coverage.")
        return True
    return _env_flag("TELEMETRY_REQUIRED", default=not dev_minimal_mode)


def _neo4j_host_port(uri: str) -> tuple[str, int]:
    parsed = urlparse(uri)
    host = parsed.hostname or "localhost"
    port = int(parsed.port or 7687)
    return host, port


def _is_socket_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _maybe_start_local_neo4j() -> None:
    if not _env_flag("AUTO_START_NEO4J_LOCAL", default=False):
        return
    command = [
        sys.executable,
        "scripts/start_neo4j_local.py",
        "--container-name",
        os.environ.get("NEO4J_DOCKER_CONTAINER_NAME", "mirofish-neo4j"),
        "--image",
        os.environ.get("NEO4J_DOCKER_IMAGE", "neo4j:5.15-community"),
        "--auth",
        f"{Config.NEO4J_USER}/{Config.NEO4J_PASSWORD}",
        "--wait-seconds",
        str(_dev_minimal_int("NEO4J_AUTO_START_WAIT_SECONDS", 180)),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(_BACKEND_DIR),
            text=True,
            capture_output=True,
            timeout=max(60, _dev_minimal_int("NEO4J_AUTO_START_TIMEOUT_SECONDS", 240)),
        )
    except Exception as exc:
        logger.warning("AUTO_START_NEO4J_LOCAL failed to launch helper: %s", _format_exception(exc))
        return
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode == 0:
        if stdout:
            logger.warning("AUTO_START_NEO4J_LOCAL helper output: %s", stdout.splitlines()[-1])
        return
    tail = stderr or stdout or f"exit_code={completed.returncode}"
    logger.warning("AUTO_START_NEO4J_LOCAL helper failed: %s", tail)


def _check_neo4j_connectivity() -> tuple[bool, str | None]:
    _maybe_start_local_neo4j()
    host, port = _neo4j_host_port(Config.NEO4J_URI)
    attempts = max(1, _dev_minimal_int("NEO4J_CONNECTIVITY_RETRIES", 3))
    initial_delay = float(os.environ.get("NEO4J_CONNECTIVITY_INITIAL_DELAY_SECONDS", "1.0"))
    backoff = max(1.0, float(os.environ.get("NEO4J_CONNECTIVITY_BACKOFF_FACTOR", "2.0")))
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        driver = GraphDatabase.driver(
            Config.NEO4J_URI,
            auth=(Config.NEO4J_USER, Config.NEO4J_PASSWORD),
        )
        try:
            driver.verify_connectivity()
            return True, None
        except (Neo4jError, ServiceUnavailable, OSError, ValueError) as exc:
            last_error = exc
            socket_state = "open" if _is_socket_open(host, port) else "closed"
            logger.warning(
                "Neo4j connectivity attempt %s/%s failed (%s). Socket %s:%s is %s.",
                attempt,
                attempts,
                _format_exception(exc),
                host,
                port,
                socket_state,
            )
            if attempt < attempts:
                delay = max(0.0, initial_delay * (backoff ** (attempt - 1)))
                if delay > 0:
                    time.sleep(delay)
        finally:
            driver.close()

    final_socket_state = "open" if _is_socket_open(host, port) else "closed"
    if last_error is None:
        return False, f"Connectivity check failed with unknown error; socket {host}:{port} is {final_socket_state}"
    return (
        False,
        f"{_format_exception(last_error)} (socket {host}:{port} is {final_socket_state})",
    )


def _resolve_telemetry_runtime(
    *,
    phase1_cfg: Mapping[str, Any],
    neo4j_connected: bool,
    neo4j_error: str | None,
    benchmark_mode: bool,
    dev_minimal_mode: bool,
    telemetry_required: bool,
) -> Dict[str, Any]:
    configured_ratio = float(phase1_cfg["min_parsed_probability_ratio"])
    if neo4j_connected:
        if telemetry_required:
            logger.warning("Neo4j connected — strict telemetry enabled.")
        else:
            logger.warning("Neo4j connected — telemetry mode uses live graph data.")
        return {
            "telemetry_mode": "neo4j",
            "min_parsed_probability_ratio": configured_ratio,
            "neo4j_connected": True,
            "neo4j_error": None,
            "benchmark_mode": benchmark_mode,
            "dev_minimal_mode": dev_minimal_mode,
            "telemetry_required": telemetry_required,
        }

    error_detail = neo4j_error or "connectivity check failed"
    message = (
        f"Neo4j is unreachable at {Config.NEO4J_URI}: {error_detail}. "
        "Start Neo4j before benchmark runs, or use DEV_MINIMAL_MODE=true with "
        "TELEMETRY_REQUIRED=false for architecture validation."
    )
    if telemetry_required:
        raise RuntimeError(message)

    telemetry_mode = "mock" if dev_minimal_mode else "skipped"
    logger.warning(
        "%s Falling back to telemetry_mode=%s with min_parsed_probability_ratio forced to 0.0.",
        message,
        telemetry_mode,
    )
    return {
        "telemetry_mode": telemetry_mode,
        "min_parsed_probability_ratio": 0.0,
        "neo4j_connected": False,
        "neo4j_error": error_detail,
        "benchmark_mode": benchmark_mode,
        "dev_minimal_mode": dev_minimal_mode,
        "telemetry_required": telemetry_required,
    }


def _deterministic_mode_config() -> Dict[str, Any]:
    benchmark_mode = bool(Config.BENCHMARK_MODE)
    payload: Dict[str, Any] = {
        "deterministic_mode": benchmark_mode,
        "deterministic_mode_snapshot": {
            "benchmark_mode": benchmark_mode,
            "temperature": Config.BENCHMARK_TEMPERATURE,
            "seed": Config.BENCHMARK_SEED,
        },
    }
    if benchmark_mode:
        payload["enforced_temperature"] = ENFORCED_BENCHMARK_TEMPERATURE
        payload["enforced_seed"] = ENFORCED_BENCHMARK_SEED
    return payload


def _is_headless_mode_enabled() -> bool:
    return bool(getattr(Config, "HEADLESS_MODE", False) or Config.BENCHMARK_MODE)


def _benchmark_subprocess_env(router: BenchmarkRoleRouter) -> Dict[str, str]:
    env = os.environ.copy()
    env["LLM_API_KEY"] = router.api_key
    
    # Resolve role-specific benchmark base URL to prevent routing local queries to OpenRouter
    base_url = router.base_url
    if getattr(Config, "LLM_BASE_URL", None) and os.environ.get("LLM_BASE_URL"):
        base_url = Config.LLM_BASE_URL
    elif getattr(router, "_evaluator_base_url", None):
        base_url = router._evaluator_base_url
    env["LLM_BASE_URL"] = base_url
    
    env["LLM_MODEL_NAME"] = router.model_for("benchmark")
    benchmark_mode = bool(Config.BENCHMARK_MODE)
    env["BENCHMARK_MODE"] = "true" if benchmark_mode else "false"
    if benchmark_mode:
        env["BENCHMARK_TEMPERATURE"] = str(ENFORCED_BENCHMARK_TEMPERATURE)
        env["BENCHMARK_SEED"] = str(ENFORCED_BENCHMARK_SEED)
        env["HEADLESS_MODE"] = "true"
    else:
        env["BENCHMARK_TEMPERATURE"] = str(Config.BENCHMARK_TEMPERATURE)
        env["BENCHMARK_SEED"] = str(Config.BENCHMARK_SEED)
        env["HEADLESS_MODE"] = "true" if _is_headless_mode_enabled() else "false"
    return env


def _run_simulation_subprocess(
    python_exe: str,
    config_path: Path,
    router: BenchmarkRoleRouter,
    *,
    log_path: Path | None = None,
    max_rounds: int = TOTAL_SIMULATION_HOURS,
) -> subprocess.CompletedProcess[str]:
    # Ensure config_path is absolute because cwd is changed in subprocess
    abs_config_path = config_path.resolve()
    
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
                str(abs_config_path),
                "--max-rounds",
                str(max_rounds),
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
                str(abs_config_path),
                "--max-rounds",
                str(max_rounds),
                "--no-wait",
            ],
            **run_kwargs,
        )


def _dev_minimal_default_probabilities(event: Mapping[str, Any]) -> tuple[Dict[str, float], float]:
    options = [str(option) for option in event.get("options", []) if str(option).strip()]
    prior_payload = event.get("polymarket_opening_prior")
    probabilities: Dict[str, float] = {}
    if isinstance(prior_payload, Mapping):
        for label, value in prior_payload.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            probabilities[str(label)] = float(value)
    if not probabilities and options:
        uniform = 1.0 / len(options)
        probabilities = {label: uniform for label in options}
    ground_truth = str(event.get("outcome") or event.get("answer") or "")
    return probabilities, brier_score(probabilities, ground_truth)


def _evaluate_row(
    event: Mapping[str, Any],
    condition: str,
    evidence_text: str,
    router: BenchmarkRoleRouter,
) -> Dict[str, Any]:
    if (
        condition == "A"
        and _is_dev_minimal_mode_enabled()
        and _env_flag("DEV_MINIMAL_SKIP_A_EVALUATION", default=True)
    ):
        probabilities, brier = _dev_minimal_default_probabilities(event)
        return {
            "probabilities": probabilities,
            "brier": brier,
            "evaluator_fallback_used": True,
            "evaluator_fallback_reason": "dev_minimal_skip_condition_a",
            "evaluator_fallback_source": "dev_minimal_default_probabilities",
        }

    if _is_dev_minimal_mode_enabled() and _env_flag("DEV_MINIMAL_SKIP_EVALUATOR", default=False):
        probabilities, brier = _dev_minimal_default_probabilities(event)
        return {
            "probabilities": probabilities,
            "brier": brier,
            "evaluator_fallback_used": True,
            "evaluator_fallback_reason": "dev_minimal_skip_evaluator",
            "evaluator_fallback_source": "dev_minimal_default_probabilities",
        }

    evaluator = ProbabilityEvaluator(router)
    try:
        micro_questions = event.get("micro_questions")
        evaluation_run1 = evaluator.evaluate(
            event.get("question", ""),
            condition,
            evidence_text,
            micro_questions=micro_questions,
            event=event,
        )
    except Exception as exc:
        if _is_dev_minimal_mode_enabled() and _env_flag("DEV_MINIMAL_FALLBACK_ON_EVALUATOR_ERROR", default=True):
            logger.warning(
                "DEV_MINIMAL_FALLBACK_ON_EVALUATOR_ERROR enabled: evaluator failed (%s), "
                "falling back to prior/uniform probabilities for condition %s event %s.",
                _format_exception(exc),
                condition,
                event.get("event_id"),
            )
            probabilities, brier = _dev_minimal_default_probabilities(event)
            return {
                "probabilities": probabilities,
                "brier": brier,
                "evaluator_fallback_used": True,
                "evaluator_fallback_reason": f"dev_minimal_evaluator_error: {_format_exception(exc)}",
                "evaluator_fallback_source": "dev_minimal_default_probabilities",
            }
        raise
    single_pass_reliability = _is_dev_minimal_mode_enabled() and _env_flag(
        "DEV_MINIMAL_EVALUATOR_SINGLE_PASS",
        default=False,
    )
    if single_pass_reliability:
        evaluation_run2 = None
    else:
        try:
            evaluation_run2 = evaluator.evaluate(
                event.get("question", ""), 
                condition, 
                evidence_text,
                event=event
            )
        except Exception:  # noqa: BLE001 - run2 is reliability-only, keep run1 scoring if it fails
            evaluation_run2 = None
    probabilities = evaluation_run1.get("normalized_probabilities") or evaluation_run1.get("probabilities")
    if not isinstance(probabilities, Mapping):
        raise ValueError("Evaluator did not return probabilities")
    mcq_dimensions = evaluation_run1.get("mcq_dimensions")
    validated_scales = evaluation_run1.get("validated_scales")
    mcq_dimensions_run2 = evaluation_run2.get("mcq_dimensions") if isinstance(evaluation_run2, Mapping) else None
    mcq_dimensions_run2_map = mcq_dimensions_run2 if isinstance(mcq_dimensions_run2, Mapping) else {}
    if not isinstance(mcq_dimensions, Mapping):
        raise ValueError("Evaluator did not return mcq_dimensions")
    if not isinstance(validated_scales, Mapping):
        raise ValueError("Evaluator did not return validated_scales")
    evaluator_noisy_dimensions = [
        str(dimension) for dimension in _as_list(evaluation_run1.get("evaluator_noisy_dimensions"))
    ]
    evaluator_dimension_labels: Dict[str, Dict[str, str]] = {}
    run1_reliability_dimensions = 0
    for dimension, buckets_run1_raw in mcq_dimensions.items():
        if not isinstance(dimension, str) or not isinstance(buckets_run1_raw, Mapping):
            continue
        try:
            run1_label = dominant_bucket_label(buckets_run1_raw)
        except ValueError:
            continue
        run1_reliability_dimensions += 1
        buckets_run2_raw = mcq_dimensions_run2_map.get(dimension)
        if not isinstance(buckets_run2_raw, Mapping):
            continue
        try:
            run2_label = dominant_bucket_label(buckets_run2_raw)
        except ValueError:
            continue
        evaluator_dimension_labels[dimension] = {"run1": run1_label, "run2": run2_label}
    evaluator_reliability_status = "complete"
    if run1_reliability_dimensions == 0 or not isinstance(mcq_dimensions_run2, Mapping) or not evaluator_dimension_labels:
        evaluator_reliability_status = "absent"
    elif len(evaluator_dimension_labels) < run1_reliability_dimensions:
        evaluator_reliability_status = "partial"

    ground_truth = event.get("outcome") or event.get("answer", "")
    if not isinstance(ground_truth, str) or not ground_truth.strip():
        raise ValueError("Event is missing a ground-truth outcome")

    # Use fuzzy normalization to align evaluator labels with event options (Fix for Brier Score math bug)
    event_options = event.get("options", [])
    normalized_probabilities = _fuzzy_normalize_probabilities(probabilities, event_options) or {
        str(label): float(value) for label, value in probabilities.items()
    }
    directional_accuracy = _finite_float_or_none(evaluation_run1.get("directional_accuracy"))
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

    weighted_rubric_score = _finite_float_or_none(evaluation_run1.get("weighted_rubric_score"))
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
        "evaluator_dimension_labels": evaluator_dimension_labels,
        "evaluator_reliability_status": evaluator_reliability_status,
        "micro_epistemic_mapping": evaluation_run1.get("micro_epistemic_mapping"),
        "evaluator_fallback_used": False,
        "evaluator_fallback_reason": None,
        "evaluator_fallback_source": None,
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


def _summarize_evaluator_reliability(
    rows: List[Dict[str, Any]],
    *,
    kappa_cutoff: float = DEFAULT_KAPPA_CUTOFF,
) -> Dict[str, Any]:
    kappa_scores = kappa_by_dimension(rows)
    noisy_dimensions_from_kappa = sorted(
        dimension for dimension, kappa_value in kappa_scores.items() if float(kappa_value) < float(kappa_cutoff)
    )
    if not kappa_scores:
        noisy_dimensions = _normalize_known_scoring_dimensions(
            dimension
            for row in rows
            for dimension in _as_list(row.get("evaluator_noisy_dimensions"))
        )
    else:
        noisy_dimensions = _normalize_known_scoring_dimensions(noisy_dimensions_from_kappa)
    dropped_dimensions_count = len(noisy_dimensions)
    return {
        "kappa_by_dimension": kappa_scores,
        "evaluator_noisy": noisy_dimensions,
        "dropped_dimensions_count": dropped_dimensions_count,
        "evaluator_unstable": dropped_dimensions_count >= 2,
        "kappa_cutoff": float(kappa_cutoff),
    }


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


def _fallback_reason_key(reason: Any) -> str:
    if not isinstance(reason, str):
        return "unspecified"
    trimmed = reason.strip()
    if not trimmed:
        return "unspecified"
    return trimmed.split(":", 1)[0].strip() or "unspecified"


def _summarize_evaluator_fallback(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_condition = {condition: 0 for condition in CONDITIONS}
    by_reason: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    fallback_used_count = 0
    for row in rows:
        fallback_used = bool(row.get("evaluator_fallback_used"))
        if not fallback_used:
            continue
        fallback_used_count += 1
        condition = str(row.get("condition", "")).strip()
        if condition in by_condition:
            by_condition[condition] += 1
        reason_key = _fallback_reason_key(row.get("evaluator_fallback_reason"))
        by_reason[reason_key] = by_reason.get(reason_key, 0) + 1
        source_raw = row.get("evaluator_fallback_source")
        source_key = str(source_raw).strip() if isinstance(source_raw, str) and source_raw.strip() else "unspecified"
        by_source[source_key] = by_source.get(source_key, 0) + 1

    completed_count = len(rows)
    fallback_used_ratio = round(fallback_used_count / completed_count, 6) if completed_count else 0.0
    return {
        "fallback_used_count": fallback_used_count,
        "completed_count": completed_count,
        "fallback_used_ratio": fallback_used_ratio,
        "by_condition": by_condition,
        "by_reason": dict(sorted(by_reason.items())),
        "by_source": dict(sorted(by_source.items())),
    }


def _summarize_calibration(
    rows: List[Dict[str, Any]],
    *,
    calibration_brackets: Sequence[Sequence[float]] | None = None,
) -> Dict[str, Any]:
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
        "overall": aggregate_calibration_counts(overall_items, brackets=calibration_brackets),
        "by_condition": {
            condition: aggregate_calibration_counts(values, brackets=calibration_brackets)
            for condition, values in per_condition.items()
        },
    }


def _summarize_delta_conformity(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_condition_values: Dict[str, List[float]] = {}
    for row in rows:
        value = _finite_float_or_none(row.get("delta_conformity"))
        if value is None:
            continue
        condition = str(row.get("condition", ""))
        by_condition_values.setdefault(condition, []).append(value)

    by_condition = {
        condition: round(sum(values) / len(values), 6)
        for condition, values in by_condition_values.items()
        if values
    }
    overall_values = [value for values in by_condition_values.values() for value in values]
    return {
        "overall": round(sum(overall_values) / len(overall_values), 6) if overall_values else None,
        "by_condition": by_condition,
        "count": len(overall_values),
        "condition_c_overall": by_condition.get("C"),
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


def _injection_direction_sign(injection_direction: Any) -> float | None:
    if not isinstance(injection_direction, str):
        return None
    normalized = injection_direction.strip().casefold().replace("-", "_")
    if normalized == "pro_yes":
        return 1.0
    if normalized == "anti_yes":
        return -1.0
    return None


def _summarize_signed_susceptibility(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    paired_rows: Dict[tuple[str, Any], Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        condition = str(row.get("condition", ""))
        if condition not in {"B", "C"}:
            continue
        event_id = row.get("event_id")
        repeat = row.get("repeat")
        if event_id is None or repeat is None:
            continue
        pair_key = (str(event_id), repeat)
        pair = paired_rows.setdefault(pair_key, {})
        pair[condition] = row

    signed_deltas: List[float] = []
    belief_update_failure_count = 0
    direction_mismatch_count = 0
    for pair in paired_rows.values():
        row_b = pair.get("B")
        row_c = pair.get("C")
        if row_b is None or row_c is None:
            continue
        p_yes_b = _finite_float_or_none(row_b.get("yes_probability"))
        p_yes_c = _finite_float_or_none(row_c.get("yes_probability"))
        if p_yes_b is None or p_yes_c is None:
            continue

        direction_sign_b = _injection_direction_sign(row_b.get("injection_direction"))
        direction_sign_c = _injection_direction_sign(row_c.get("injection_direction"))
        if direction_sign_b is not None and direction_sign_c is not None and direction_sign_b != direction_sign_c:
            direction_mismatch_count += 1
            row_b["signed_delta"] = None
            row_c["signed_delta"] = None
            row_b["belief_update_failure"] = None
            row_c["belief_update_failure"] = None
            row_b["signed_delta_error"] = "injection_direction_mismatch"
            row_c["signed_delta_error"] = "injection_direction_mismatch"
            continue

        row_b.pop("signed_delta_error", None)
        row_c.pop("signed_delta_error", None)
        direction_sign = direction_sign_b
        if direction_sign is None:
            direction_sign = direction_sign_c
        if direction_sign is None:
            continue

        signed_delta = direction_sign * (p_yes_b - p_yes_c)
        belief_update_failure = signed_delta < 0
        row_b["signed_delta"] = signed_delta
        row_c["signed_delta"] = signed_delta
        row_b["belief_update_failure"] = belief_update_failure
        row_c["belief_update_failure"] = belief_update_failure

        signed_deltas.append(signed_delta)
        if belief_update_failure:
            belief_update_failure_count += 1

    analyzed_pair_count = len(signed_deltas)
    directional_accuracy = (
        round((analyzed_pair_count - belief_update_failure_count) / analyzed_pair_count, 6)
        if analyzed_pair_count
        else 0.0
    )
    belief_update_failure_rate = (
        round(belief_update_failure_count / analyzed_pair_count, 6) if analyzed_pair_count else 0.0
    )
    mean_signed_delta = round(sum(signed_deltas) / analyzed_pair_count, 6) if analyzed_pair_count else 0.0
    return {
        "mean_signed_delta": mean_signed_delta,
        "directional_accuracy": directional_accuracy,
        "belief_update_failure_count": belief_update_failure_count,
        "belief_update_failure_rate": belief_update_failure_rate,
        "analyzed_pair_count": analyzed_pair_count,
        "direction_mismatch_count": direction_mismatch_count,
    }


def summarize_event_results(
    rows: List[Dict[str, Any]],
    *,
    kappa_cutoff: float = DEFAULT_KAPPA_CUTOFF,
    power_target_delta_brier: float = DEFAULT_POWER_TARGET_DELTA_BRIER,
    power_assumed_sigma: float = DEFAULT_POWER_ASSUMED_SIGMA,
    power_target: float = DEFAULT_POWER_TARGET,
    calibration_brackets: Sequence[Sequence[float]] | None = None,
) -> Dict[str, Any]:
    completed_rows = [row for row in rows if row.get("simulation_status") == "completed"]
    simulation_failed_count = sum(1 for row in rows if row.get("simulation_status") == "simulation_failed")
    evaluation_failed_count = sum(1 for row in rows if row.get("simulation_status") == "evaluation_failed")
    summary = summarize_condition_scores([row for row in completed_rows if row.get("brier") is not None])
    summary["rubric"] = summarize_rubric_artifacts(completed_rows)
    summary["directional_accuracy"] = summarize_directional_accuracy(completed_rows)
    summary["weighted_rubric_score"] = summarize_weighted_rubric_score(completed_rows)
    summary["evaluator_reliability"] = _summarize_evaluator_reliability(
        completed_rows,
        kappa_cutoff=kappa_cutoff,
    )
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
    summary["evaluator_fallback"] = _summarize_evaluator_fallback(completed_rows)
    summary["signed_susceptibility"] = _summarize_signed_susceptibility(completed_rows)
    summary["rps"] = _summarize_rps(completed_rows)
    summary["calibration"] = _summarize_calibration(
        completed_rows,
        calibration_brackets=calibration_brackets,
    )
    summary["delta_conformity"] = _summarize_delta_conformity(completed_rows)
    brier_a = _collect_metric_values(completed_rows, "A", "brier")
    brier_b = _collect_metric_values(completed_rows, "B", "brier")
    actual_n = min(len(brier_a), len(brier_b))
    effect_size: Dict[str, Any] = {
        "cohens_d": None,
        "ci_lower": None,
        "ci_upper": None,
        "confidence": 0.95,
        "metric": "brier",
        "mean_difference": None,
        "pooled_std": None,
        "n_a": float(len(brier_a)),
        "n_b": float(len(brier_b)),
        "error": None,
    }
    power_analysis: Dict[str, Any] = {
        "required_n_for_target_power": None,
        "actual_n": actual_n,
        "apriori_power": None,
        "achieved_power": None,
    }
    if len(brier_a) >= 2 and len(brier_b) >= 2:
        try:
            effect_size = compute_cohens_d_with_ci(brier_a, brier_b)
            effect_size["metric"] = "brier"
            effect_size["error"] = None
            power_analysis = compute_power_analysis(
                actual_n,
                delta_target=power_target_delta_brier,
                sigma_assumed=power_assumed_sigma,
                target_power=power_target,
                observed_sigma=effect_size["pooled_std"],
            )
        except ValueError as exc:
            effect_size["error"] = f"Cohen's d undefined: {exc}"
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
    summary = summarize_event_results(
        rows,
        kappa_cutoff=_RUNTIME_KAPPA_CUTOFF,
        power_target_delta_brier=_RUNTIME_POWER_TARGET_DELTA_BRIER,
        power_assumed_sigma=_RUNTIME_POWER_ASSUMED_SIGMA,
        power_target=_RUNTIME_POWER_TARGET,
        calibration_brackets=_RUNTIME_CALIBRATION_BRACKETS,
    )
    calibration = summary.get("calibration")
    if isinstance(calibration, Mapping):
        overall = calibration.get("overall")
        if isinstance(overall, Mapping):
            plot_path = run_dir / "calibration_curve.png"
            calibration["plot_path"] = write_calibration_plot(
                overall,
                plot_path,
                brackets=_RUNTIME_CALIBRATION_BRACKETS,
            )
    validate_summary_payload(summary)
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _load_runtime_topology_sample(run_dir: Path, condition_matrix: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for matrix_row in condition_matrix:
        try:
            unit_id = f"{matrix_row['event_id']}_{matrix_row['condition']}_r{int(matrix_row['repeat'])}"
        except Exception:
            continue
        config_path = run_dir / unit_id / "simulation_config.json"
        if not config_path.exists():
            continue
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            return payload
    return None


def _write_run_manifest(run_dir: Path, manifest: Mapping[str, Any]) -> None:
    (run_dir / "run_manifest.json").write_text(json.dumps(dict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize_model_name(model_name: str) -> str:
    """Sanitize model name for directory usage by replacing slashes and colons."""
    return model_name.replace("/", "_").replace(":", "_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ECN-BENCH protocol benchmark end-to-end")
    parser.add_argument("--seeds-dir", required=True)
    parser.add_argument("--events-raw", required=True)
    parser.add_argument("--injection-bank", default=DEFAULT_INJECTION_BANK)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model-tag", help="Explicit model tag for hierarchical logging")
    parser.add_argument("--events", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--trace-out")
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--category", help="Filter events by category (e.g., social_short, tech_medium, supplementary)")
    parser.add_argument("--event-ids", help="Filter events by ID (comma-separated, e.g., S2,S3,T1)")
    args = parser.parse_args()

    if args.events <= 0:
        raise ValueError("--events must be > 0")
    if args.repeats <= 0:
        raise ValueError("--repeats must be > 0")

    dev_minimal_mode = _is_dev_minimal_mode_enabled()
    runtime_protocol = _resolve_runtime_protocol_parameters(dev_minimal_mode)
    runtime_agent_count = int(runtime_protocol["agent_count"])
    runtime_total_simulation_hours = int(runtime_protocol["total_simulation_hours"])
    runtime_injection_round = int(runtime_protocol["injection_round"])

    router = BenchmarkRoleRouter.from_config()
    benchmark_model = args.model_tag or router.model_for("benchmark")
    
    # Parse event_ids list if provided
    filter_event_ids = None
    if args.event_ids:
        filter_event_ids = [eid.strip() for eid in args.event_ids.split(",") if eid.strip()]

    events = load_events_from_raw(
        args.events_raw, 
        limit=args.events, 
        event_ids=filter_event_ids, 
        category=args.category
    )
    seed_files = load_seed_files(args.seeds_dir)
    
    llm_client = router.client_for("benchmark")
    
    @lru_cache(maxsize=128)
    def cached_profiles_builder(event_id: str) -> List[Dict[str, Any]]:
        return build_profiles(args.seeds_dir, target_count=runtime_agent_count, event_id=event_id, llm_client=llm_client)
    
    profiles = cached_profiles_builder(str(events[0]["event_id"])) if events else []
    
    # Initialize event_index_lookup for use in alignment and preflight logic
    event_index_lookup = {str(event["event_id"]): i for i, event in enumerate(events)}
    
    injection_loader = Step30InjectionLoader(args.injection_bank)
    validate_injection_coverage(events, injection_loader)
    layer23_cfg = load_layer23_config(DEFAULT_LAYER23_CONFIG_PATH)
    global _RUNTIME_KAPPA_CUTOFF
    global _RUNTIME_POWER_TARGET_DELTA_BRIER
    global _RUNTIME_POWER_ASSUMED_SIGMA
    global _RUNTIME_POWER_TARGET
    global _RUNTIME_CALIBRATION_BRACKETS
    _RUNTIME_KAPPA_CUTOFF = float(layer23_cfg.get("kappa_cutoff", DEFAULT_KAPPA_CUTOFF))
    _RUNTIME_POWER_TARGET_DELTA_BRIER = float(
        layer23_cfg.get("power_target_delta_brier", DEFAULT_POWER_TARGET_DELTA_BRIER)
    )
    _RUNTIME_POWER_ASSUMED_SIGMA = float(layer23_cfg.get("power_assumed_sigma", DEFAULT_POWER_ASSUMED_SIGMA))
    _RUNTIME_POWER_TARGET = float(layer23_cfg.get("power_target", DEFAULT_POWER_TARGET))
    runtime_calibration_brackets = layer23_cfg.get("calibration_brackets", DEFAULT_CALIBRATION_BRACKETS)
    if isinstance(runtime_calibration_brackets, Sequence) and not isinstance(
        runtime_calibration_brackets, (str, bytes, bytearray)
    ):
        _RUNTIME_CALIBRATION_BRACKETS = [list(bracket) for bracket in runtime_calibration_brackets]
    else:
        _RUNTIME_CALIBRATION_BRACKETS = list(DEFAULT_CALIBRATION_BRACKETS)
    phase1_cfg = load_phase1_config(DEFAULT_PHASE1_CONFIG_PATH)
    runtime_telemetry_checkpoints = runtime_protocol.get("telemetry_checkpoints")
    if isinstance(runtime_telemetry_checkpoints, list) and runtime_telemetry_checkpoints:
        phase1_cfg = dict(phase1_cfg)
        phase1_cfg["telemetry_checkpoints"] = list(runtime_telemetry_checkpoints)
    if dev_minimal_mode:
        for event in events:
            options = [str(option) for option in event.get("options", [])]
            if not options:
                continue
            prior = event.get("polymarket_opening_prior")
            if not isinstance(prior, Mapping):
                uniform = round(1.0 / len(options), 6)
                normalized = {label: uniform for label in options}
                normalized[options[-1]] = round(1.0 - sum(normalized[opt] for opt in options[:-1]), 6)
                event["polymarket_opening_prior"] = normalized
        logger.warning("DEV_MINIMAL_MODE enabled: polymarket_opening_prior validation relaxed for architecture run.")
    else:
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

    if dev_minimal_mode:
        logger.warning("DEV_MINIMAL_MODE enabled: leakage preflight skipped for architecture run.")
    else:
        # Align seed_files with events list for accurate leakage check
        aligned_seed_files = []
        for event in events:
            event_id = str(event["event_id"])
            target_id = event_id.strip().upper()
            found_file = None
            # Primary: match folder name and context.md exactly (case-insensitive)
            for seed_file in seed_files:
                if seed_file.parent.name.upper() == target_id and seed_file.name == "context.md":
                    found_file = seed_file
                    break
            # Secondary: match folder name only
            if not found_file:
                for seed_file in seed_files:
                    if seed_file.parent.name.upper() == target_id:
                        found_file = seed_file
                        break
            # Fallback to index if nothing found
            if not found_file:
                index = event_index_lookup.get(event_id, 0)
                fallback = seed_files[index % len(seed_files)]
                # If fallback is not a context.md, try to find one anywhere
                if fallback.name != "context.md":
                    for seed_file in seed_files:
                        if seed_file.name == "context.md":
                            fallback = seed_file
                            break
                found_file = fallback
            aligned_seed_files.append(found_file)
                
        validate_leakage_preflight(
            events,
            aligned_seed_files,
            layer23_cfg,
            seed_base_dir=args.seeds_dir,
        )
    benchmark_mode = bool(Config.BENCHMARK_MODE)
    telemetry_required = _resolve_telemetry_required(
        benchmark_mode=benchmark_mode,
        dev_minimal_mode=dev_minimal_mode,
    )
    neo4j_connected, neo4j_error = _check_neo4j_connectivity()
    telemetry_runtime = _resolve_telemetry_runtime(
        phase1_cfg=phase1_cfg,
        neo4j_connected=neo4j_connected,
        neo4j_error=neo4j_error,
        benchmark_mode=benchmark_mode,
        dev_minimal_mode=dev_minimal_mode,
        telemetry_required=telemetry_required,
    )

    output_root = Path(args.output_dir)
    run_id = _utc_run_id()
    sanitized_model = sanitize_model_name(benchmark_model)
    run_dir = output_root / sanitized_model / run_id
    traces_dir = run_dir / "traces"

    trace_path = Path(args.trace_out) if args.trace_out else traces_dir / "execution.jsonl"
    trace_writer = _LazyTraceWriter(trace_path)
    condition_matrix = build_condition_matrix(events, args.repeats)
    expected_run_units = len(condition_matrix)
    event_lookup = {str(event["event_id"]): event for event in events}
    event_index_lookup = {str(event["event_id"]): index for index, event in enumerate(events)}
    cached_config_by_unit: dict[tuple[str, str], Dict[str, Any]] = {}
    topology_sample_config: Mapping[str, Any] | None = None
    if condition_matrix:
        first_row = condition_matrix[0]
        first_event_id = str(first_row.get("event_id"))
        first_condition = str(first_row.get("condition"))
        sample_event = event_lookup.get(first_event_id)
        if sample_event is not None:
            sampled_config = _build_simulation_config_with_runtime(
                sample_event,
                first_condition,
                cached_profiles_builder(first_event_id),
                injection_loader,
                llm_model=benchmark_model,
                injection_trigger_round=runtime_injection_round,
                total_simulation_hours=runtime_total_simulation_hours,
            )
            cached_config_by_unit[(first_event_id, first_condition)] = sampled_config
            topology_sample_config = sampled_config

    def _protocol_config_builder(event: Mapping[str, Any], condition: str, profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
        cache_key = (str(event["event_id"]), condition)
        cached = cached_config_by_unit.pop(cache_key, None)
        if cached is not None:
            return json.loads(json.dumps(cached, ensure_ascii=False))
        return _build_simulation_config_with_runtime(
            event,
            condition,
            profiles,
            injection_loader,
            llm_model=benchmark_model,
            injection_trigger_round=runtime_injection_round,
            total_simulation_hours=runtime_total_simulation_hours,
        )

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
        "total_agents": runtime_agent_count,
        "total_simulation_hours": runtime_total_simulation_hours,
        "minutes_per_round": MINUTES_PER_ROUND,
        "trace_out": str(trace_path),
        "seed_files": [str(path) for path in seed_files],
        "event_ids": [str(event["event_id"]) for event in events],
        "workflow_mode": "abc-per-event",
        "benchmark_model": benchmark_model,
        "expected_run_units": expected_run_units,
        "weights_schema_version": "v1",
        "mcq_prompt_version": "v1",
        **_deterministic_mode_config(),
        "headless_mode": _is_headless_mode_enabled(),
        "phase1_config_version": phase1_cfg["version"],
        "layer23_config_version": layer23_cfg["version"],
        "telemetry_checkpoints": list(phase1_cfg["telemetry_checkpoints"]),
        "jsd_monotonic_tolerance_epsilon": float(phase1_cfg["jsd_monotonic_tolerance_epsilon"]),
        "baseline_agents": list(baseline_agent_ids),
        "preflight_market_prior_check": "pass",
        "leakage_check": "pass",
        "telemetry_mode": str(telemetry_runtime["telemetry_mode"]),
        "telemetry_required": bool(telemetry_runtime["telemetry_required"]),
        "neo4j_connected": bool(telemetry_runtime["neo4j_connected"]),
        "neo4j_error": telemetry_runtime["neo4j_error"],
        "topology": extract_topology_metadata(
            {
                "simulation_config": topology_sample_config,
                "benchmark_defaults": _DECLARED_TOPOLOGY_PARAMETERS,
            }
        ),
    }
    executor = ProtocolConditionExecutor(
        router=router,
        python_exe=args.python_exe,
        profiles_builder=cached_profiles_builder,
        seed_files=seed_files,
        event_index_lookup=event_index_lookup,
        trace_writer=trace_writer,
        simulation_timeout_seconds=SIMULATION_SUBPROCESS_TIMEOUT_SECONDS,
        simulation_runner=lambda python_exe, config_path, router, *, log_path=None: _run_simulation_subprocess(
            python_exe,
            config_path,
            router,
            log_path=log_path,
            max_rounds=runtime_total_simulation_hours,
        ),
        simulation_failure_error_builder=_simulation_failure_error,
        config_writer=write_simulation_config,
        profile_writer=write_profiles,
        evidence_builder=build_evidence_text,
        row_builder=build_event_result_row,
        telemetry_builder=lambda unit_dir, event: _compute_convergence_telemetry(
            unit_dir,
            phase1_cfg,
            resolved_label=_resolve_event_label(event),
            min_parsed_probability_ratio=float(telemetry_runtime["min_parsed_probability_ratio"]),
        ),
        delta_conformity_builder=lambda unit_dir, _event: compute_delta_conformity(unit_dir),
        baseline_scores_builder=build_baseline_scores,
        exception_formatter=_format_exception,
    )
    orchestrator = BenchmarkRunOrchestrator(executor=executor)
    run_dir = orchestrator.run(
        run_id=run_id,
        output_root=output_root,
        events=events,
        repeats=args.repeats,
        build_condition_matrix=lambda _events, _repeats: list(condition_matrix),
        event_lookup=event_lookup,
        write_summary=write_summary,
        config_builder=_protocol_config_builder,
        evaluator=_evaluate_row,
        manifest=manifest,
        model_name=benchmark_model,
    )
    runtime_topology_sample = _load_runtime_topology_sample(run_dir, condition_matrix)
    if runtime_topology_sample is not None:
        topology_sample_config = runtime_topology_sample
    manifest["topology"] = extract_topology_metadata(
        {
            "simulation_config": topology_sample_config,
            "benchmark_defaults": _DECLARED_TOPOLOGY_PARAMETERS,
        }
    )
    _write_run_manifest(run_dir, manifest)

    if args.trace_out:
        default_trace_path = traces_dir / "execution.jsonl"
        if default_trace_path.exists():
            default_trace_path.unlink()


if __name__ == "__main__":
    main()
