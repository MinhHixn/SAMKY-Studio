from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Literal

InjectionDirection = Literal["pro_YES", "anti_YES"]
VALID_INJECTION_DIRECTIONS = {"pro_YES", "anti_YES"}


def _metadata_path(seed_dir: Path | str) -> Path:
    path = Path(seed_dir)
    if path.is_file():
        return path
    return path / "metadata.json"


def load_seed_metadata(seed_dir: Path | str) -> Dict[str, Any]:
    metadata_path = _metadata_path(seed_dir)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError(f"metadata.json must contain an object: {metadata_path}")

    direction = metadata.get("injection_direction")
    if not isinstance(direction, str) or direction not in VALID_INJECTION_DIRECTIONS:
        raise ValueError(
            "metadata.json injection_direction must be one of pro_YES or anti_YES"
        )

    return dict(metadata)
