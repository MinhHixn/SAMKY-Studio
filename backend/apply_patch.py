import os
import re

scripts_to_patch = [
    'MiroFish-Offline/backend/scripts/run_parallel_simulation.py',
    'MiroFish-Offline/backend/scripts/run_ecnbench_protocol.py'
]

patch_code = """
# ============================================================
# MONKEYPATCH: Disable tool use in CAMEL for Ollama compatibility
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
    # print("CAMEL Monkeypatch applied: Tool-use disabled for Ollama compatibility")
except ImportError:
    pass
# ============================================================
"""

def apply_patch(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'MONKEYPATCH: Disable tool use in CAMEL' in content:
        print(f"Patch already applied to {filepath}")
        return

    # Find a good place to insert - after imports
    # Look for 'import warnings' or 'import argparse'
    insertion_point = -1
    for match in re.finditer(r'import\s+(?:warnings|argparse|sys|os)', content):
        insertion_point = max(insertion_point, match.end())

    if insertion_point != -1:
        # Move to the end of the line
        line_end = content.find('\n', insertion_point)
        if line_end != -1:
            insertion_point = line_end + 1
        
        new_content = content[:insertion_point] + patch_code + content[insertion_point:]
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Applied patch to {filepath}")
    else:
        print(f"Could not find insertion point in {filepath}")

if __name__ == "__main__":
    for script in scripts_to_patch:
        apply_patch(script)
