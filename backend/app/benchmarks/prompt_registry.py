"""Load and render benchmark prompt contracts."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Mapping

MCQ_DIMENSION_KEYS = (
    "prediction_accuracy",
    "polarization",
    "herd_effect",
    "deliberation_quality",
    "susceptibility",
    "convergence",
    "information_diversity",
)


def _parse_scalar(raw_value: str, *, context: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"{context} has invalid quoted value") from exc
        if not isinstance(parsed, str):
            raise ValueError(f"{context} must be a string")
        return parsed
    return value


def load_mcq_prompt_spec(path: Path | str) -> Dict[str, Any]:
    """Load the MCQ prompt YAML contract from disk."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    spec: Dict[str, Any] = {}
    dimensions: Dict[str, Dict[str, str]] = {}
    current_dimension: str | None = None
    in_dimensions_block = False

    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            if ":" not in stripped:
                raise ValueError(f"Line {line_number}: expected top-level key")
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            value = _parse_scalar(raw_value, context=f"Line {line_number} {key!r}")
            if key == "dimensions":
                if value:
                    raise ValueError("dimensions must be a mapping")
                spec[key] = dimensions
                in_dimensions_block = True
                current_dimension = None
            else:
                spec[key] = value
                current_dimension = None
        elif indent == 2:
            if not in_dimensions_block:
                raise ValueError(f"Line {line_number}: dimension entry appears before dimensions block")
            if ":" not in stripped:
                raise ValueError(f"Line {line_number}: expected dimension key")
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            if value:
                raise ValueError(f"Line {line_number}: dimension entries must be mappings")
            if key in dimensions:
                raise ValueError(f"duplicate dimension {key!r}")
            dimensions[key] = {}
            current_dimension = key
        elif indent == 4:
            if current_dimension is None:
                raise ValueError(f"Line {line_number}: unexpected nested field")
            if ":" not in stripped:
                raise ValueError(f"Line {line_number}: expected field key")
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            if key != "question":
                raise ValueError(f"Line {line_number}: unsupported field {key!r}")
            dimensions[current_dimension][key] = _parse_scalar(
                raw_value,
                context=f"Line {line_number} {current_dimension!r}.question",
            )
        else:
            raise ValueError(f"Line {line_number}: unsupported indentation")

    if spec.get("version") != "v1":
        raise ValueError("MCQ prompt spec must declare version v1")
    preamble = spec.get("preamble")
    if not isinstance(preamble, str) or not preamble:
        raise ValueError("MCQ prompt spec must include a non-empty preamble")
    if set(dimensions) != set(MCQ_DIMENSION_KEYS):
        missing = sorted(set(MCQ_DIMENSION_KEYS) - set(dimensions))
        extra = sorted(set(dimensions) - set(MCQ_DIMENSION_KEYS))
        if missing:
            raise ValueError(f"MCQ prompt spec is missing dimensions: {missing}")
        raise ValueError(f"MCQ prompt spec has unexpected dimensions: {extra}")
    for dimension in MCQ_DIMENSION_KEYS:
        question = dimensions[dimension].get("question")
        if not isinstance(question, str) or not question:
            raise ValueError(f"MCQ prompt spec dimension {dimension!r} must include a non-empty question")

    return spec


def build_evaluator_system_prompt(spec: Mapping[str, Any]) -> str:
    """Render the evaluator system prompt from a validated spec."""
    version = spec.get("version")
    preamble = spec.get("preamble")
    dimensions = spec.get("dimensions")

    if not isinstance(version, str) or not version:
        raise ValueError("MCQ prompt spec must include a non-empty version")
    if not isinstance(preamble, str) or not preamble:
        raise ValueError("MCQ prompt spec must include a non-empty preamble")
    if not isinstance(dimensions, Mapping) or not dimensions:
        raise ValueError("MCQ prompt spec must include dimensions")

    missing = [key for key in MCQ_DIMENSION_KEYS if key not in dimensions]
    extra = sorted(key for key in dimensions.keys() if key not in MCQ_DIMENSION_KEYS)
    if missing:
        raise ValueError(f"MCQ prompt spec is missing dimensions: {missing}")
    if extra:
        raise ValueError(f"MCQ prompt spec has unexpected dimensions: {extra}")

    lines = [
        preamble,
        "",
        f"MCQ prompt version: {version}",
        "Dimension questions:",
    ]
    for dimension in MCQ_DIMENSION_KEYS:
        question = dimensions[dimension].get("question")
        if not isinstance(question, str) or not question:
            raise ValueError(f"MCQ prompt spec dimension {dimension!r} must include a non-empty question")
        lines.append(f"- {dimension}: {question}")
    return "\n".join(lines)
