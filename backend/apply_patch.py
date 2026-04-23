import os
import re

filepath = 'scripts/run_parallel_simulation.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    patch = """
# MONKEYPATCH: Disable tool use in CAMEL for OpenRouter models that don't support it
from camel.models import OpenAIModel
_original_arun = OpenAIModel.arun
async def _patched_arun(self, messages, response_format=None, tools=None):
    # Force tools to None to disable tool use
    return await _original_arun(self, messages, response_format, None)
OpenAIModel.arun = _patched_arun
"""
    
    if 'MONKEYPATCH' not in content:
        # Insert after imports
        new_content = content.replace('import warnings', 'import warnings' + patch)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Applied monkeypatch to scripts/run_parallel_simulation.py")
    else:
        print("Monkeypatch already applied.")
