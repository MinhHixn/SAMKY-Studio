"""ECN-BENCH protocol primitives."""

from __future__ import annotations
from copy import deepcopy
import os
from typing import Any, Dict, List


def _as_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error


def _is_dev_minimal_mode_enabled() -> bool:
    return os.environ.get("DEV_MINIMAL_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _dev_minimal_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def enforce_protocol_constraints(config: Dict[str, Any]) -> None:
    """Validate the benchmark protocol invariants."""
    dev_minimal_mode = _is_dev_minimal_mode_enabled()
    required_agent_count = _dev_minimal_int("DEV_MINIMAL_AGENT_COUNT", 100) if dev_minimal_mode else 3000
    required_rounds = _dev_minimal_int("DEV_MINIMAL_MAX_STEPS", 30) if dev_minimal_mode else 60

    agent_configs = config.get("agent_configs")
    if not isinstance(agent_configs, list):
        raise ValueError("agent_configs must be a list")
    if len(agent_configs) != required_agent_count:
        if dev_minimal_mode:
            raise ValueError(
                f"DEV_MINIMAL_MODE requires exactly {required_agent_count} agents, got {len(agent_configs)}"
            )
        raise ValueError(f"Protocol requires exactly 3000 agents, got {len(agent_configs)}")

    time_config = config.get("time_config", {})
    total_simulation_hours = _as_int(time_config.get("total_simulation_hours"), "total_simulation_hours")
    minutes_per_round = _as_int(time_config.get("minutes_per_round"), "minutes_per_round")
    if minutes_per_round <= 0:
        raise ValueError("minutes_per_round must be greater than 0")

    total_rounds = (total_simulation_hours * 60) // minutes_per_round
    if total_rounds != required_rounds:
        if dev_minimal_mode:
            raise ValueError(
                f"DEV_MINIMAL_MODE requires exactly {required_rounds} rounds, got {total_rounds}"
            )
        raise ValueError(f"Protocol requires exactly 60 rounds, got {total_rounds}")


import json
import logging
import asyncio
import os
import random
from copy import deepcopy
from typing import Any, Dict, List, Optional
from ..utils.llm_client import LLMClient

try:
    import json_repair
except ImportError:
    json_repair = None

logger = logging.getLogger("mirofish.protocol")

# --- Diversified DNA Template Library ---
DNA_TEMPLATES = [
    {
        "worldview": "Pragmatic institutionalist; filters truth through {profession} experience.",
        "motivation": "Driven to identify systemic risks and protect {country} interests.",
        "tone": "Clinical, analytical, and technical; uses industry-specific jargon.",
        "biases": "Triggered by irrational market volatility; biased against policies lacking empirical backing."
    },
    {
        "worldview": "Grassroots activist; views the world through the lens of social equity and local community impact.",
        "motivation": "Motivated to give a voice to the underrepresented and challenge top-down narratives.",
        "tone": "Passionate, urgent, and direct; uses colloquial but forceful language.",
        "biases": "Triggered by corporate jargon; biased against institutional reports that ignore human-level consequences."
    },
    {
        "worldview": "Techno-optimist; believes decentralized technology and innovation solve core societal frictions.",
        "motivation": "Aims to promote efficient, code-driven solutions over slow bureaucratic processes.",
        "tone": "Optimistic, fast-paced, and informal; heavy use of tech metaphors.",
        "biases": "Triggered by luddite rhetoric; biased against legacy regulations that stifle innovation."
    },
    {
        "worldview": "Skeptical contrarian; assumes mainstream consensus is a lagging indicator or manufactured narrative.",
        "motivation": "Driven to find the 'hidden' angle and question the assumptions of the loudest voices.",
        "tone": "Sarcastic, questioning, and provocative; uses rhetorical questions and counter-examples.",
        "biases": "Triggered by 'expert' appeals to authority; biased against unanimous media consensus."
    },
    {
        "worldview": "Traditionalist moralist; evaluates events based on historical continuity and cultural stability.",
        "motivation": "Motivated to preserve institutional integrity and societal cohesion.",
        "tone": "Measured, formal, and respectful; uses historical references and structured arguments.",
        "biases": "Triggered by rapid, disruptive change; biased against radical departures from established norms."
    },
    {
        "worldview": "Globalist bureaucrat; views events through the prism of international relations and treaty compliance.",
        "motivation": "Aims to ensure multi-lateral cooperation and procedural adherence.",
        "tone": "Diplomatic, verbose, and neutral; uses international law and policy terminology.",
        "biases": "Triggered by isolationist rhetoric; biased against unilateral actions that ignore global standards."
    }
]

def _get_diversified_dna(profession: str, country: str, index: int) -> str:
    """Select and hydrate a DNA template based on index and context."""
    tpl = DNA_TEMPLATES[index % len(DNA_TEMPLATES)]
    return (
        f"- Worldview: {tpl['worldview'].format(profession=profession, country=country)}\n"
        f"- Motivation: {tpl['motivation'].format(profession=profession, country=country)}\n"
        f"- Tone: {tpl['tone'].format(profession=profession, country=country)}\n"
        f"- Biases & Triggers: {tpl['biases'].format(profession=profession, country=country)}"
    )

async def _summarize_persona_async(persona_text: str, client: LLMClient, index: int = 0) -> str:
    """Summarize a large persona into a concise metadata string along 4 core axes."""
    if not persona_text or len(persona_text) < 300:
        return persona_text
        
    def _run():
        # Variation injection to prevent identical summarizations for similar base profiles
        variation = [
            "Focus on the agent's professional skepticism.",
            "Emphasize the agent's emotional connection to the community.",
            "Highlight the agent's reliance on quantitative data.",
            "Stress the agent's distrust of centralized power.",
            "Focus on the agent's role as a mediator and diplomat."
        ][index % 5]

        prompt = f"""You must compress the 1,000-word biography into exactly 4 highly detailed bullet points. Each bullet point must act as a strict behavioral constraint for a simulation agent. 

GUIDANCE: {variation}

1. Worldview & Epistemology: Explain exactly how they filter truth and view the system (e.g., 'Radical empiricist; evaluates everything through Bayesian probability rather than ideology').
2. Primary Motivation: State their core objective for participating in social media discussions.
3. Communication Tone & Style: Define their textual fingerprint (e.g., 'Clinical, dry, uses heavy academic jargon').
4. Biases & Action Triggers (CRITICAL): You MUST start this bullet point with 'Triggered by...' or 'Biased against...'. Define the specific concepts or rhetoric that force this agent to react aggressively or dismissively.

Persona:
{persona_text}

OUTPUT FORMAT:
Return ONLY a valid JSON object with a 'summary' string field containing the bullet points.
"""
        try:
            response = client.chat_json([
                {"role": "system", "content": "You are an expert behavioral profiler. Output strictly valid JSON."},
                {"role": "user", "content": prompt}
            ], enforce_benchmark_params=False)
            if isinstance(response, dict) and "summary" in response:
                return response["summary"]
            elif isinstance(response, str):
                return response
            return persona_text
        except Exception as e:
            logger.error(f"Persona summarization failed: {e}")
            return persona_text
    
    res = await asyncio.to_thread(_run)
    return res

def _validate_persona_dna(persona_text: str) -> bool:
    """Check if the persona string contains the required 4-axis markers."""
    if not persona_text or not isinstance(persona_text, str):
        return False
    lower_text = persona_text.lower()
    # Check for trigger markers (allowing common variations)
    has_trigger = any(marker in lower_text for marker in [
        "triggered by", "biased against", "reaction triggers", "biases:", "triggers:"
    ])
    # Check for multiple axes (at least 3 bullet points or significant length/newlines)
    has_structure = (
        persona_text.count("- ") >= 3 or 
        persona_text.count("•") >= 3 or 
        persona_text.count("\n") >= 3 or
        persona_text.count("1.") >= 3
    )
    return has_trigger and has_structure and len(persona_text) > 80

async def _generate_synthetic_batch_async(base: Dict[str, Any], count: int, client: LLMClient, seed: int = 0) -> List[Dict[Dict[str, Any]]]:
    """RESTORED: High-fidelity synthetic expansion with 4-Axis DNA blueprints."""
    def _run():
        prompt = f"""You are an expert in social psychology and synthetic data generation.
Your task is to take the following BASE PERSONA and expand it into {count} unique, first-class identities.

BASE PERSONA:
Name: {base.get('name')}
Bio: {base.get('bio')}
Profession: {base.get('profession')}
Existing DNA Template: 
{base.get('persona')}

INSTRUCTIONS FOR COGNITIVE EXPANSION (CRITICAL):
1. NO CLONES. Every identity must have a unique name, background, and specific reason for engaging.
2. 4-AXIS BLUEPRINT: Every variation MUST have a 'persona' field consisting of exactly 4 detailed bullet points:
   - Worldview & Epistemology: How they filter truth.
   - Primary Motivation: Their personal objective.
   - Communication Style: Their textual fingerprint.
   - Biases & Triggers: MUST start with 'Triggered by...' or 'Biased against...'.
3. DIVERSIFY: vary the demographic spread (age, gender, country) and the epistemic stance significantly.
4. Each variation must represent a UNIQUE stakeholder or observer.

OUTPUT FORMAT:
Return ONLY a valid JSON list of {count} objects. Each object MUST contain:
- name: Full name
- bio: Unique social media bio
- persona: The 4-Axis DNA string (4 bullet points)
- age: Integer
- gender: male, female, or other
- mbti: MBTI type
- profession: Specific occupation
- country: Country name
- interested_topics: List of strings
"""
        try:
            # RESTORED: Use natural temperature (0.7) for creativity
            response = client.chat_json([
                {"role": "system", "content": "You are a master sociological researcher specializing in synthetic population modeling. Output strictly valid JSON."},
                {"role": "user", "content": prompt}
            ], enforce_benchmark_params=False, max_tokens=4096, temperature=0.7)
            
            if isinstance(response, list):
                return response
            elif isinstance(response, dict):
                # Handle cases where LLM wraps the list in a key
                for val in response.values():
                    if isinstance(val, list):
                        return val
            return []
        except Exception as e:
            logger.error(f"Restored expansion batch failed: {e}")
            return []

    return await asyncio.to_thread(_run)

def expand_profiles_to_target(
    base_profiles: List[Dict[str, Any]], 
    target_count: int = 3000,
    llm_client: Optional[LLMClient] = None
) -> List[Dict[str, Any]]:
    """
    ARCHITECTURE v3.4: Intelligent Synthetic Expansion.
    Scales a high-fidelity base set to target size using LLM-driven cognitive blueprints.
    """
    if not base_profiles:
        raise ValueError("Cannot expand profiles from an empty base list")
    
    if target_count <= len(base_profiles):
        return base_profiles[:target_count]

    checkpoint_file = os.path.join(os.getcwd(), "logs", "synthetic_expansion_checkpoint.json")
    expanded: List[Dict[str, Any]] = []

    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                expanded = json.load(f)
            logger.info(f"Loaded {len(expanded)} profiles from checkpoint.")
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")

    if len(expanded) >= target_count:
        return expanded[:target_count]

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Initial seeding if checkpoint is empty
    if len(expanded) == 0:
        logger.info("Initializing expansion with base identities...")
        for i, base in enumerate(base_profiles):
            original = deepcopy(base)
            original["user_id"] = i
            # Unique identifiers
            base_name = original.get("name", "Agent")
            original["name"] = f"{base_name} #{i}"
            original["username"] = f"{original.get('username', 'agent')}_{i}"
            expanded.append(original)
        
        os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(expanded, f)

    # RESTORED: Intelligent Batch Expansion
    if llm_client:
        max_retries = 3
        batch_size = 5
        chunk_size = 25 # Expand in chunks to maintain performance
        
        while len(expanded) < target_count and max_retries > 0:
            remaining = target_count - len(expanded)
            current_chunk = min(chunk_size, remaining)
            logger.info(f"Synthetic expansion: {len(expanded)}/{target_count} ready. Generating chunk of {current_chunk}...")
            
            tasks = []
            for i in range(0, current_chunk, batch_size):
                b_idx = (len(expanded) + i) % len(base_profiles)
                n = min(batch_size, current_chunk - i)
                tasks.append(_generate_synthetic_batch_async(base_profiles[b_idx], n, llm_client, seed=len(expanded) + i))
            
            results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            
            new_batch_count = 0
            for batch in results:
                if isinstance(batch, Exception) or not batch:
                    continue
                for v in batch:
                    if len(expanded) >= target_count: break
                    if not isinstance(v, dict): continue
                    
                    # DNA VALIDATION: Ensure expansion follows the 4-axis rule
                    dna = v.get("persona", "")
                    if not _validate_persona_dna(dna):
                         continue
                    
                    v_idx = len(expanded)
                    # Merge with base template for safety, but overwrite with synthetic data
                    new_v = deepcopy(base_profiles[v_idx % len(base_profiles)])
                    new_v.update(v)
                    new_v["user_id"] = v_idx
                    new_v["name"] = f"{v.get('name', 'Agent')} #{v_idx}"
                    new_v["username"] = f"{v.get('name', 'agent').lower().replace(' ', '_')}_{v_idx}"
                    
                    expanded.append(new_v)
                    new_batch_count += 1
            
            if new_batch_count == 0:
                max_retries -= 1
                logger.warning(f"Batch expansion yielded 0 valid agents. Retries left: {max_retries}")
            
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(expanded, f)

    # Hardened Fallback (Rule-based) if LLM fails
    needed = target_count - len(expanded)
    if needed > 0:
        logger.warning(f"Resorting to DIVERSIFIED rule-based fallback for {needed} agents.")
        for i in range(needed):
            v_idx = len(expanded)
            b_idx = v_idx % len(base_profiles)
            var = deepcopy(base_profiles[b_idx])
            var["user_id"] = v_idx
            var["persona"] = _get_diversified_dna(var.get('profession', 'Expert'), var.get('country', 'US'), v_idx)
            var["name"] = f"{var.get('profession', 'Agent')} #{v_idx}"
            expanded.append(var)

    return expanded[:target_count]


def _extract_usable_text(payload: Dict[str, Any]) -> str:
    for key in ("body", "headline"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def build_step30_scheduled_event(
    payload: Dict[str, Any],
    poster_agent_id: int = 0,
    *,
    trigger_round: int = 30,
) -> Dict[str, Any]:
    """Create the scheduled event used for step-30 injections."""
    content = _extract_usable_text(payload)
    if not content:
        raise ValueError("Injection payload must include body/headline text")

    event: Dict[str, Any] = {
        "trigger_round": int(trigger_round),
        "posts": [{"poster_agent_id": poster_agent_id, "content": content}],
    }
    temporal_updates = payload.get("temporal_updates")
    if isinstance(temporal_updates, list):
        event["temporal_updates"] = deepcopy(temporal_updates)
    return event
