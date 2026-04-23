import os
import re

filepath = 'scripts/run_parallel_simulation.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.readlines()
    
    for i, line in enumerate(content):
        if 'LLMAction' in line:
            print(f"Line {i+1}: {line.strip()}")
