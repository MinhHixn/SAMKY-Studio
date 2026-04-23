"""
Intelligent Persona Generation for ECN-BENCH
Uses OasisProfileGenerator to create diverse personas from a single context file.
"""

import json
import logging
import random
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
    Generate high-fidelity base profiles directly from the event context.
    For small counts (<= 100), it attempts to generate all agents uniquely from the context.
    """
    client = llm_client or LLMClient()
    generator = OasisProfileGenerator(llm_client=client)
    
    # For Phase 0/Minimal runs, we want 100% unique contextual identities, not expansions.
    target_seed_count = min(agent_count, 60) if agent_count > 100 else agent_count
    valid_types = generator.INDIVIDUAL_ENTITY_TYPES + generator.GROUP_ENTITY_TYPES
    
    prompt = f"""You are an expert in social simulation and demographic modeling.
Analyze the provided event context and identify exactly {target_seed_count} unique stakeholders, observers, and affected parties.

CONTEXT:
{context_text[:10000]}

VALID ENTITY TYPES:
{", ".join(valid_types)}

TASK:
Return a JSON object with an 'entities' list. Each entity must be a unique individual or a specific representative of a group.
For each entity, generate:
1. name: Full name.
2. type: One of the valid types above.
3. occupation: Specific job related to the context.
4. country: Relevant country.
5. persona_dna: A strict 4-Axis DNA profile consisting of EXACTLY 4 detailed bullet points:
   - Worldview & Epistemology: How they filter truth.
   - Primary Motivation: Why they engage in this specific topic.
   - Communication Style: Their textual fingerprint.
   - Biases & Triggers: MUST start with 'Triggered by...' or 'Biased against...'.
"""

    logger.info(f"Generating {target_seed_count} unique contextual identities with 4-Axis DNA...")
    try:
        response = client.chat_json([
            {"role": "system", "content": "You are a master sociological profiler. Output strictly valid JSON."},
            {"role": "user", "content": prompt}
        ], enforce_benchmark_params=False, max_tokens=8192, repair_truncated_json=True)
        extracted_entities = response.get("entities", [])
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}")
        return []

    if not extracted_entities:
        logger.warning("No entities extracted from context.")
        return []

    # 2. Instantiate each identity
    base_profiles = []
    for i, ent in enumerate(extracted_entities[:target_seed_count]):
        name = ent.get("name", f"Agent {i}")
        etype = ent.get("type", "person")
        dna = ent.get("persona_dna", "")
        
        # Ensure type is valid
        if etype not in valid_types:
            etype = "person"
            
        mock_node = MockEntityNode(
            uuid=f"intel-{i}",
            name=name,
            labels=[etype, "Entity"],
            summary=dna, # Inject DNA as the core summary
            attributes={
                "occupation": ent.get("occupation"),
                "country": ent.get("country")
            }
        )
        
        logger.info(f"Instantiating contextual agent: {name} ({etype})...")
        try:
            profile: OasisAgentProfile = generator.generate_profile_from_entity(mock_node, user_id=i)
            
            # Convert OasisAgentProfile to the dict format expected by the benchmark
            profile_dict = {
                "user_id": i,
                "username": profile.user_name,
                "name": profile.name,
                "realname": profile.name,
                "bio": profile.bio,
                # RE-ENFORCE DNA: Ensure the generator didn't dilute the 4-Axis DNA
                "persona": dna if dna else profile.persona,
                "age": profile.age or 30,
                "gender": profile.gender or "other",
                "mbti": profile.mbti or "ISTJ",
                "country": profile.country or ent.get("country") or "US",
                "profession": profile.profession or ent.get("occupation") or "Participant",
                "interested_topics": profile.interested_topics,
                "karma": profile.karma,
                "friend_count": profile.friend_count,
                "follower_count": profile.follower_count,
                "statuses_count": profile.statuses_count,
                "created_at": profile.created_at,
                "entity_name": profile.name,
                "entity_uuid": mock_node.uuid,
                "entity_type": etype,
                "activity_level": 0.5,
                "source_seed_file": "intelligent_generation",
            }
            base_profiles.append(profile_dict)
        except Exception as e:
            logger.error(f"Failed to instantiate agent {name}: {e}")
            
    return base_profiles
