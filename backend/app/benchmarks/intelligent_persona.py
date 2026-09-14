"""
Intelligent Persona Generation for ECN-BENCH
Uses OasisProfileGenerator to create diverse personas from a single context file.
"""

import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from ..services.oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from ..utils.llm_client import LLMClient

logger = logging.getLogger("mirofish.intelligent_persona")

@dataclass
class MockEntityNode:
    """Mock EntityNode for OasisProfileGenerator"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    related_edges: List[Dict[str, Any]] = None
    related_nodes: List[Dict[str, Any]] = None

    def get_entity_type(self) -> Optional[str]:
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None

def generate_intelligent_base_profiles(
    context_text: str,
    agent_count: int = 3000,
    llm_client: Optional[LLMClient] = None
) -> List[Dict[str, Any]]:
    """
    ARCHITECTURE v4.0: Cognitive Diversification Pipeline.
    Restores high-fidelity diversity by using specialized extraction and instantiation prompts.
    """
    client = llm_client or LLMClient()
    
    # Target unique contextual identities
    target_seed_count = min(agent_count, 30) 
    
    # STAGE 1: Extract Diverse Stakeholders (Individuals & Organizations)
    extraction_prompt = f"""You are a master sociological researcher.
Analyze the provided event context and identify exactly {target_seed_count} unique and diverse stakeholders.

CONTEXT:
{context_text[:8000]}

MANDATE (CRITICAL):
You MUST identify a diverse mix of:
1. Individual Humans (approx 60%): High-impact individuals, experts, and affected citizens.
2. Institutional/Organizational Accounts (approx 40%): THIS IS MANDATORY. You must include News Outlets (e.g., WSJ, Reuters), Financial Institutions (e.g., Goldman Sachs, JP Morgan), Government Agencies (e.g., The Fed), and NGOs/Think Tanks.

For each, provide:
1. name: Name of the person or organization.
2. type: 'person' or 'organization'.
3. bio: A VERY brief summary of their role in this context (max 100 chars).
4. profession: Their specific occupation or organizational function.

Return ONLY a JSON object with an 'entities' key containing a list of objects with these 4 fields.

CRITICAL OUTPUT CONSTRAINT FOR REASONING MODELS:
You are interacting with a strict automated JSON parser. 
If your architecture forces you to generate a thinking process or reasoning steps, you MUST encapsulate your final JSON object strictly inside a ```json ... ``` markdown code block. 
Do NOT append any conversational text after the JSON block.
"""

    logger.info(f"Extracting {target_seed_count} diverse entities from context...")
    try:
        entities = client.chat_json([
            {"role": "system", "content": "You are a strict data-generator. Output ONLY valid JSON object with 'entities' key. If you must think, ensure the JSON is inside a ```json block."},
            {"role": "user", "content": extraction_prompt}
        ], enforce_benchmark_params=False, max_tokens=4000, repair_truncated_json=True)
        
        # Robust extraction: if the LLM wraps the array in a dictionary
        if isinstance(entities, dict):
            # First, try known keys
            extracted = entities.get("entities") or entities.get("content") or entities.get("list")

            
            # If still None, aggressively find the first list value in the dict
            if not isinstance(extracted, list):
                for value in entities.values():
                    if isinstance(value, list):
                        extracted = value
                        break
            
            entities = extracted if isinstance(extracted, list) else []
            
        if not isinstance(entities, list):
            entities = []
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}")
        return []

    if not entities:
        logger.warning("No entities extracted.")
        return []

    # STAGE 2: High-Fidelity Persona Instantiation
    base_profiles = []
    for i, ent in enumerate(entities[:target_seed_count]):
        if not isinstance(ent, dict):
            logger.warning(f"Skipping non-dict entity: {ent}")
            continue
            
        # TASK 1: RESTORE THE ANTI-DUMP SHIELD
        name = ent.get("name", "Unknown")
        
        # --- ENHANCED ANTI-DUMP SHIELD ---
        name_check = str(ent.get("name", "")).lower()
        bio_len = len(str(ent.get("bio", "")))
        persona_len = len(str(ent.get("persona", "")))
        
        # Trigger if 'context' is ANYWHERE in the name, OR if bio/persona are unusually large
        if "context" in name_check or bio_len > 400 or persona_len > 600:
            logger.warning(f"Detected garbage entity extraction (Name: {ent.get('name')}, BioLen: {bio_len}, PersonaLen: {persona_len}). Activating Standardized Fallback.")
            
            ent["name"] = "Tech Policy Analyst"
            ent["bio"] = "Independent analyst focusing on governance and capability tracking."
            ent["profession"] = "Analyst"
            ent["age"] = 35
            ent["gender"] = "other"
            ent["mbti"] = "INTJ"
            # Strictly enforced 4-axis compressed DNA to prevent token bloat
            ent["persona"] = "- Worldview: Technological progress requires objective measurement.\\n- Motivation: To accurately track industry milestones.\\n- Style: Highly analytical and data-driven.\\n- Biases: Triggered by unsubstantiated corporate hype."
        # ----------------------------------------------

        ent_name = ent.get("name", "Unknown")
        ent_type = ent.get("type", "person")
        ent_bio = ent.get("bio", "Participant")
        ent_profession = ent.get("profession", "Expert")

        # TASK 2: RESTORE DNA COMPRESSION MANDATE
        dna_mandate = """
DNA COMPRESSION MANDATE: 
The 'persona' field MUST be a single string containing exactly 4 bullet points (Worldview, Motivation, Style, Biases). 
CRITICAL: Each bullet point MUST be EXACTLY ONE SHORT SENTENCE. Do not write long paragraphs.

STRICT JSON FORMAT EXAMPLE:
{
  "bio": "Financial analyst watching market trends.",
  "age": 35,
  "gender": "male",
  "mbti": "INTJ",
  "persona": "- Worldview: Empirical skepticism.\\n- Motivation: Protect wealth.\\n- Style: Professional.\\n- Biases: Triggered by inflation.",
  "interested_topics": ["Finance"]
}

CRITICAL OUTPUT CONSTRAINT FOR REASONING MODELS:
You are interacting with a strict automated JSON parser. 
If your architecture forces you to generate a thinking process or reasoning steps, you MUST encapsulate your final JSON object strictly inside a ```json ... ``` markdown code block. 
Do NOT append any conversational text after the JSON block.
"""

        # Tailored prompt based on type to maximize diversity
        if ent_type == "organization":
            instantiation_prompt = f"""Create a detailed persona for an ORGANIZATIONAL account: '{ent_name}'.
Context: {ent_bio}
Role: {ent_profession}

Rules:
- 'bio' MUST be a concise official summary (max 150 chars).
- 'persona' MUST be exactly 4 bullet points (Worldview, Motivation, Style, Biases).
- 'gender' MUST be 'organization', 'mbti' MUST be 'N/A', 'age' is years of operation (integer).
- 'persona' axis 4 MUST start with 'Triggered by...' or 'Biased against...'.
{dna_mandate}
"""
        else:
            instantiation_prompt = f"""Create a detailed persona for an INDIVIDUAL: '{ent_name}'.
Context: {ent_bio}
Role: {ent_profession}

Rules:
- 'bio' MUST be a concise social media bio (max 150 chars).
- 'persona' MUST be exactly 4 bullet points (Worldview, Motivation, Style, Biases).
- Choose a unique country, MBTI, age (integer), and gender (male/female).
- 'persona' axis 4 MUST start with 'Triggered by...' or 'Biased against...'.
{dna_mandate}
"""

        logger.info(f"Generating detailed persona for {ent_name} ({ent_type})...")
        try:
            p_data = client.chat_json([
                {"role": "system", "content": "You are a strict data-generator. Output ONLY valid JSON. If you must think, ensure the JSON is inside a ```json block. DNA axis 4 MUST contain 'Triggered by' or 'Biased against'."},
                {"role": "user", "content": instantiation_prompt}
            ], enforce_benchmark_params=False, max_tokens=1024, repair_truncated_json=True)

            # Defensive normalization (v3.9 safe logic)
            if isinstance(p_data, list):
                if len(p_data) > 0 and isinstance(p_data[0], dict):
                    p_data = p_data[0]
                else:
                    p_data = {}
            elif not isinstance(p_data, dict):
                p_data = {}

            dna = p_data.get("persona", ent.get("persona", ""))
            if isinstance(dna, list): dna = "\n".join(f"- {str(x)}" for x in dna)
            bio = p_data.get("bio", ent.get("bio", ent_bio))
            if isinstance(bio, list): bio = ". ".join(str(x) for x in bio)

            # TASK 3: RESTORE SAFE AGE PARSING (REGEX) - BULLETPROOF
            age_val = p_data.get("age")
            if age_val is None:
                age_val = ent.get("age", 30)
                
            if age_val is None:
                parsed_age = 30
            elif isinstance(age_val, str):
                try:
                    parsed_age = int(re.sub(r'[^0-9]', '', age_val))
                except ValueError:
                    parsed_age = 30
            else:
                try:
                    parsed_age = int(age_val)
                except (ValueError, TypeError):
                    parsed_age = 30

            # Secondary defense: aggressively truncate bloated personas from Stage 2
            safe_persona = str(dna).replace('"', "'")
            if len(safe_persona) > 600:
                logger.warning(f"Stage 2 LLM hallucinated a massive persona for {ent_name}. Truncating.")
                safe_persona = safe_persona[:600] + "... [TRUNCATED]"

            profile_dict = {
                "user_id": i,
                "username": f"{ent_name.lower().replace(' ', '_')}_{i}",
                "name": ent_name,  # STRICT OVERRIDE: Do not use p_data.get("name")
                "realname": ent_name,
                "bio": str(bio)[:160],
                "persona": safe_persona,
                "age": parsed_age,
                # STRICT OVERRIDE: Force organizational gender rules based on ent_type from Stage 1
                "gender": "organization" if ent_type == "organization" else p_data.get("gender", ent.get("gender", "female")),
                "mbti": "N/A" if ent_type == "organization" else p_data.get("mbti", ent.get("mbti", "ISTJ")),
                "country": p_data.get("country", ent.get("country", "US")),
                "profession": ent_profession,
                "interested_topics": p_data.get("interested_topics", ["General"]),
                "karma": random.randint(1000, 5000),
                "friend_count": random.randint(100, 1000),
                "follower_count": random.randint(100, 1000),
                "statuses_count": random.randint(100, 1000),
                "created_at": "2024-01-01",
                "entity_name": ent_name,
                "entity_type": ent_type,
                "activity_level": 0.5,
                "source_seed_file": "intelligent_generation",
            }
            base_profiles.append(profile_dict)
        except Exception as e:
            logger.error(f"Failed to instantiate persona for {ent_name}: {e}")
            
    return base_profiles
