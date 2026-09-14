"""ECN-BENCH protocol primitives."""

from __future__ import annotations
from copy import deepcopy
import os
import re
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
import math
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

def _post_process_synthetic_profile(profile: Dict[str, Any], base_template: Dict[str, Any]) -> Dict[str, Any]:
    """ARCHITECTURE v3.8: Advanced defensive filtering and structural normalization."""
    # Ensure name is a valid string
    name = profile.get("name")
    if isinstance(name, list):
        profile["name"] = " ".join(str(x) for x in name)
    elif not name:
        profile["name"] = f"{base_template.get('profession', 'Agent')} #{profile.get('user_id', 'X')}"

    # CRITICAL: Fix 'bio' if LLM returned an array (common Qwen-7B failure)
    bio = profile.get("bio")
    if isinstance(bio, list):
        # Join array into a single string, then truncate for conciseness
        profile["bio"] = ". ".join(str(x) for x in bio).strip()[:160]
    elif isinstance(bio, str):
        profile["bio"] = bio[:160]
    else:
        profile["bio"] = base_template.get("bio", "Social media participant")[:160]
    
    # Fix 'persona' if returned as array
    persona = profile.get("persona")
    if isinstance(persona, list):
        profile["persona"] = "\n".join(f"- {str(x).strip('- ')}" for x in persona)
    elif not isinstance(persona, str):
        profile["persona"] = base_template.get("persona", "A neutral observer.")

    # Validate Age
    try:
        age_val = profile.get("age")
        if isinstance(age_val, str):
            profile["age"] = int(re.sub(r'[^0-9]', '', age_val))
        else:
            profile["age"] = int(age_val or 30)
    except (ValueError, TypeError, re.error):
        profile["age"] = 30

    # Strict normalization for core fields
    for field in ["name", "bio", "persona", "profession", "country", "mbti"]:
        if field in profile:
            profile[field] = str(profile[field]).strip().replace('"', "'")
            
    return profile

async def _generate_synthetic_batch_async(base: Dict[str, Any], count: int, client: LLMClient, seed: int = 0) -> List[Dict[str, Any]]:
    """ARCHITECTURE v3.8: High-success Persona Generation with Structural Anchors."""
    def _run():
        # Minimal high-signal attributes for example to reduce token noise
        example_json = {
            "name": "Jordan Smith",
            "bio": "Financial analyst and decentralized tech advocate.",
            "persona": "- Worldview: Empirical skepticism...\n- Motivation: Protect wealth...\n- Style: Professional...\n- Biases: Triggered by inflation.",
            "age": 34,
            "gender": "male",
            "mbti": "INTJ",
            "profession": "Analyst",
            "country": "UK",
            "interested_topics": ["Finance", "Crypto"]
        }

        prompt = f"""Task: Generate {count} unique stakeholder personas.
Target: Expand '{base.get('name')}' ({base.get('profession')}) into distinct identities.

STRICT JSON FORMAT:
[
  {{
    "name": "Full Name",
    "bio": "Concise string (max 160 chars)",
    "persona": "- Axis 1: ...\\n- Axis 2: ...\\n- Axis 3: ...\\n- Axis 4: Biased against...",
    "age": 30,
    "gender": "male/female/other",
    "mbti": "XXXX",
    "profession": "Specific title",
    "country": "Full Name",
    "interested_topics": ["topic1", "topic2"]
  }}
]

RULES:
1. 'bio' MUST be a STRING. NEVER an array [].
2. 'persona' MUST be a STRING with 4 bullet points.
3. Every persona MUST include a 'Biases & Triggers' point.
4. Each of the {count} identities must have a unique name and background.

Example Object:
{json.dumps(example_json)}

Generate exactly {count} objects in a JSON list:"""
        try:
            # Enable repair_truncated_json for better fault tolerance
            response = client.chat_json([
                {"role": "system", "content": "You are a sociological research unit. Output ONLY valid JSON list. 'bio' field MUST be a string, NOT an array."},
                {"role": "user", "content": prompt}
            ], enforce_benchmark_params=False, max_tokens=4000, temperature=0.7, repair_truncated_json=True)
            
            if isinstance(response, list):
                return response
            elif isinstance(response, dict):
                # Handle cases where LLM wraps the list in a key
                for val in response.values():
                    if isinstance(val, list):
                        return val
            return []
        except Exception as e:
            logger.error(f"Batch generation failed: {e}")
            return []

    return await asyncio.to_thread(_run)

def expand_profiles_to_target(
    base_profiles: List[Dict[str, Any]], 
    target_count: int = 3000,
    llm_client: Optional[LLMClient] = None,
    event_id: str = "default"
) -> List[Dict[str, Any]]:
    """
    ARCHITECTURE v3.5: Intelligent Async Micro-Batching Expansion.
    Scales a high-fidelity base set using concurrent small batches to prevent LLM attention dilution.
    Uses event-specific checkpoints to prevent Context Bleed.
    """
    if not base_profiles:
        raise ValueError("Cannot expand profiles from an empty base list")
    
    # ARCHITECTURE v3.11: Ensure rule is applied to base profiles if we return them directly
    if target_count <= len(base_profiles):
        res = base_profiles[:target_count]
        for profile in res:
            if "persona" in profile:
                rule = "- Global Language Rule: Speak and post strictly in English only."
                if rule not in profile["persona"]:
                    profile["persona"] = profile["persona"].strip() + f"\n{rule}"
        return res

    # ARCHITECTURE v4.1: Event-specific checkpoint to prevent Memory Leak / Context Bleed
    checkpoint_dir = os.path.join(os.getcwd(), "logs", "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)
    
    model_name = os.getenv("LLM_MODEL_NAME", "default_model")
    sanitized_model = model_name.replace("/", "_").replace(":", "_").replace("\\", "_")
    checkpoint_file = os.path.join(checkpoint_dir, f"expansion_{sanitized_model}_{event_id}.json")
    expanded: List[Dict[str, Any]] = []

    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                expanded = json.load(f)
            logger.info(f"Loaded {len(expanded)} profiles from event checkpoint: {event_id}")
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")

    if len(expanded) >= target_count:
        # ARCHITECTURE v3.11: Ensure rule is applied even when returning from checkpoint
        for profile in expanded[:target_count]:
            if "persona" in profile:
                rule = "- Global Language Rule: Speak and post strictly in English only."
                if rule not in profile["persona"]:
                    profile["persona"] = profile["persona"].strip() + f"\n{rule}"
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
            base_name = original.get("name", "Agent")
            original["name"] = f"{base_name} #{i}"
            original["username"] = f"{original.get('username', 'agent')}_{i}"
            expanded.append(original)
        
        os.makedirs(os.path.dirname(checkpoint_file), exist_ok=True)
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(expanded, f)

    # MICRO-BATCHING ARCHITECTURE
    if llm_client:
        MAX_GLOBAL_RETRIES = 10  # Increased for extreme robustness
        BATCH_SIZE = 5  # High-stability size for complex persona JSON
        MAX_CONCURRENT_BATCHES = 3  # Limit concurrency for local LLM stability
        
        global_retries = MAX_GLOBAL_RETRIES
        total_failures = 0
        iteration_count = 0
        
        while len(expanded) < target_count and global_retries > 0:
            iteration_count += 1
            remaining = target_count - len(expanded)
            # Determine how many batches we need to run concurrently
            batches_needed = math.ceil(remaining / BATCH_SIZE)
            current_concurrency = min(batches_needed, MAX_CONCURRENT_BATCHES)
            
            logger.info(f"Expansion Progress: {len(expanded)}/{target_count} (Total Failures: {total_failures}). "
                        f"Requesting {current_concurrency} parallel batches of {BATCH_SIZE}...")
            
            tasks = []
            for i in range(current_concurrency):
                b_idx = (len(expanded) + (i * BATCH_SIZE)) % len(base_profiles)
                # Vary seed by iteration and batch index to prevent repetitive hallucinations
                tasks.append(_generate_synthetic_batch_async(
                    base_profiles[b_idx], BATCH_SIZE, llm_client, 
                    seed=len(expanded) + (iteration_count * 100) + i
                ))
            
            results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            
            new_agents_found = 0
            for batch in results:
                if isinstance(batch, Exception) or not batch:
                    total_failures += BATCH_SIZE # Whole batch failed
                    continue
                
                batch_valid_count = 0
                for v in batch:
                    if len(expanded) >= target_count: break
                    if not isinstance(v, dict): 
                        total_failures += 1
                        continue
                    
                    # STRICT DNA VALIDATION
                    dna = v.get("persona", "")
                    if not _validate_persona_dna(dna):
                         total_failures += 1
                         logger.debug(f"Persona validation failed for synthetic agent.")
                         continue
                    
                    # ARCHITECTURE v3.7: Apply defensive post-processing
                    v_idx = len(expanded)
                    processed_v = _post_process_synthetic_profile(v, base_profiles[v_idx % len(base_profiles)])
                    
                    # ARCHITECTURE v3.11: Global Linguistic Firewall Injection
                    if "persona" in processed_v:
                        processed_v["persona"] += "\n- Global Language Rule: Speak and post strictly in English only."
                    
                    # Merge with base template for safety, but overwrite with synthetic data
                    new_v = deepcopy(base_profiles[v_idx % len(base_profiles)])
                    new_v.update(processed_v)
                    new_v["user_id"] = v_idx
                    new_v["name"] = f"{processed_v.get('name', 'Agent')} #{v_idx}"
                    new_v["username"] = f"{processed_v.get('name', 'agent').lower().replace(' ', '_')}_{v_idx}"
                    
                    expanded.append(new_v)
                    new_agents_found += 1
                    batch_valid_count += 1
                
                # Account for LLM returning fewer items than requested
                if len(batch) < BATCH_SIZE:
                    total_failures += (BATCH_SIZE - len(batch))
            
            if new_agents_found == 0:
                global_retries -= 1
                logger.warning(f"Micro-batch generation yielded 0 valid agents. Global retries left: {global_retries}")
            else:
                # Reset retries if we're making progress
                global_retries = MAX_GLOBAL_RETRIES
            
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(expanded, f)

    # Hardened Fallback (Rule-based) if LLM fails
    # ARCHITECTURE v5.15: Diversified rule-based fallback.
    # Previously this branch deep-copied a SINGLE base profile `needed` times,
    # producing 300 identical "Political Analyst" clones (name/username/bio all
    # collapsed) whenever intelligent generation + synthetic batches failed
    # (typically because the vLLM 400 tool/strict crash killed every LLMAction).
    # This made the swarm behaviourally homogeneous and invalidated Claim 1/3.
    # Now each replica gets a distinct identity drawn from rotated pools.
    needed = target_count - len(expanded)
    if needed > 0:
        logger.warning(f"Resorting to DIVERSIFIED rule-based fallback for {needed} agents.")
        _fallback_first_names = [
            "Ava", "Liam", "Sofia", "Noah", "Maya", "Ethan", "Isabella", "Lucas",
            "Mia", "Caleb", "Zoe", "Owen", "Lily", "Carter", "Aria", "Wyatt",
            "Nora", "Julian", "Ruby", "Leo", "Hazel", "Miles", "Iris", "Felix",
            "Vera", "Hugo", "Clara", "Theo", "Juno", "Oscar"
        ]
        _fallback_last_names = [
            "Carter", "Reyes", "Okafor", "Novak", "Singh", "Park", "Muller",
            "Rossi", "Chen", "Andersson", "Dubois", "Kim", "Silva", "Hassan",
            "Yamamoto", "Schmidt", "Lopez", "Ivanov", "Bauer", "Nguyen",
            "Fernandez", "Walsh", "Khan", "Petrov", "Mbeki", "Tanaka", "Costa"
        ]
        _fallback_mbtis = ["INTJ", "ENTP", "INFJ", "ESTP", "ENFP", "ISTJ", "ENTJ", "ISFP"]
        for i in range(needed):
            v_idx = len(expanded)
            b_idx = v_idx % len(base_profiles)
            var = deepcopy(base_profiles[b_idx])
            var["user_id"] = v_idx

            # Rotate diversified identity attributes so no two clones are identical
            first = _fallback_first_names[v_idx % len(_fallback_first_names)]
            last = _fallback_last_names[(v_idx * 7 + 3) % len(_fallback_last_names)]
            profession = var.get("profession", "Analyst") or "Analyst"
            country = var.get("country", "US") or "US"
            var["persona"] = _get_diversified_dna(profession, country, v_idx)
            var["name"] = f"{first} {last} #{v_idx}"
            var["realname"] = f"{first} {last}"
            var["username"] = f"{first.lower()}_{last.lower()}_{v_idx}"
            var["mbti"] = _fallback_mbtis[v_idx % len(_fallback_mbtis)]
            var["age"] = 22 + (v_idx * 13 % 45)  # 22..66 spread
            var["bio"] = f"{profession} based in {country}, engaging on emerging developments."
            var["entity_name"] = var["name"]
            var["entity_uuid"] = f"agent-fallback-{v_idx}"
            expanded.append(var)

    # FINAL PASS: Ensure EVERY agent (base, synthetic, fallback, checkpoint)
    # has the Global Linguistic Firewall Rule injected.
    logger.info(f"Injecting Global Language Rule into {len(expanded)} profiles...")
    for profile in expanded:
        if "persona" in profile:
            rule = "- Global Language Rule: Speak and post strictly in English only."
            if rule not in profile["persona"]:
                profile["persona"] = profile["persona"].strip() + f"\n{rule}"

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
