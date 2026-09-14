"""
Defensive JSON Parsing Module for ECN-BENCH
Utilizes json-repair and strict type fallbacks to ensure pipeline stability 
during large-scale (3,000 agent) simulations.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from json_repair import repair_json

logger = logging.getLogger(__name__)

class SafeParser:
    @staticmethod
    def parse_llm_json(raw_text: str, fallback: Any = None) -> Any:
        """
        Attempts to repair and parse JSON from raw LLM output.
        Falls back to the provided structure if all attempts fail.
        """
        if not raw_text:
            return fallback or {}

        try:
            # 1. Direct attempt
            return json.loads(raw_text)
        except json.JSONDecodeError:
            try:
                # 2. Extract JSON from markdown blocks if present
                content = raw_text
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                else:
                    # 2b. Aggressive Regex fallback: find the outermost {} or []
                    import re
                    # Look for { ... } or [ ... ]
                    # This handles cases where the LLM writes text before or after the JSON
                    brace_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', content)
                    if brace_match:
                        content = brace_match.group(0)
                
                # 3. Use json-repair to fix common syntax issues
                repaired = repair_json(content)
                if not repaired or repaired == '""':
                     return fallback or {}
                return json.loads(repaired)
            except Exception as e:
                logger.warning(f"SafeParser failed to salvage JSON. Error: {e}")
                return fallback or {}

    @staticmethod
    def get_dict(data: Any, key: str, default: Dict = None) -> Dict:
        """Strictly ensures a dictionary is returned for a given key."""
        if default is None:
            default = {}
        if not isinstance(data, dict):
            return default
        val = data.get(key, default)
        return val if isinstance(val, dict) else default

    @staticmethod
    def get_list(data: Any, key: str, default: List = None) -> List:
        """Strictly ensures a list is returned for a given key."""
        if default is None:
            default = []
        if not isinstance(data, dict):
            return default
        val = data.get(key, default)
        return val if isinstance(val, list) else default

    @staticmethod
    def get_float(data: Any, key: str, default: float = 0.0) -> float:
        """Safely extracts a float value."""
        if not isinstance(data, dict):
            return default
        try:
            return float(data.get(key, default))
        except (ValueError, TypeError):
            return default

def safe_mcq_dimensions(data: Any) -> Dict[str, Any]:
    """Specific shield for mcq_dimensions."""
    return SafeParser.get_dict(data, "mcq_dimensions", {})

def safe_epistemic_mapping(data: Any) -> Dict[str, Any]:
    """Specific shield for micro_epistemic_mapping."""
    return SafeParser.get_dict(data, "micro_epistemic_mapping", {})
