import sys
import os
import re
from pathlib import Path

def verify_environment():
    print("=== MiroFish-Offline Architecture Verification ===")
    
    # 1. Verify Python Version
    version = sys.version_info
    print(f"Current Python: {version.major}.{version.minor}.{version.micro}")
    if version.major != 3 or version.minor != 11:
        print("WARNING: This simulation core REQUIRES Python 3.11 for compatibility with 'camel-oasis'.")
        print("Using other versions may cause 'ModuleNotFoundError: No module named oasis' or segment faults.")
    else:
        print("SUCCESS: Python 3.11 environment verified.")

    # 2. Verify Telemetry Architecture (Frozen JSD Fix)
    sim_script = Path(__file__).parent / "backend" / "scripts" / "run_parallel_simulation.py"
    if not sim_script.exists():
        print("ERROR: run_parallel_simulation.py not found.")
        return

    content = sim_script.read_text(encoding="utf-8")
    
    # Check for Contextual Injection
    has_context = "_TELEMETRY_PROBE_CONTEXTUAL_SYSTEM_PROMPT" in content
    has_memory = "_get_agent_recent_memory_summary" in content
    
    # Check for Random Selection (Diversity)
    has_random = "random.choice(list(agent_names.keys()))" in content
    
    # Check for Strict Schema
    has_schema = "json_schema=schema" in content and "response_format" in content

    print("\nArchitecture Integrity Check:")
    
    if has_context and has_memory:
        print("  [OK] Contextual Injection (Agent Bio/Memory grounding active)")
    else:
        print("  [FAIL] Contextual Injection missing! Telemetry may suffer from Context Amnesia.")

    if has_random:
        print("  [OK] Diversity Enforcement (Random agent sampling active)")
    else:
        print("  [FAIL] Random Selection missing! JSD may become frozen (Neutrality Trap).")

    if has_schema:
        print("  [OK] Structured Output (Strict JSON schema enforcement active)")
    else:
        print("  [FAIL] JSON Schema enforcement missing! Risk of persona-based refusals.")

    print("\nIMPORTANT: Do not revert these architectural changes. They are critical for mathematical JSD movement and swarm diversity.")

if __name__ == "__main__":
    verify_environment()
