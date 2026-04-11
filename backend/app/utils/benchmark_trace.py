import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class BenchmarkTraceWriter:
    """Append benchmark records as JSON lines with UTC timestamps."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, payload: Dict[str, Any]) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
