import os
import re

filepath = 'scripts/run_parallel_simulation.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    match = re.search(r'def _apply_benchmark_env', content)
    if match:
        start = match.start()
        # Find next function or class
        next_match = re.search(r'\n(def|class)\s', content[match.end():])
        end = match.end() + next_match.start() if next_match else len(content)
        print(content[start:end])
