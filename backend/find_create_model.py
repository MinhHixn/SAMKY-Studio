import os
import re

filepath = 'scripts/run_parallel_simulation.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    match = re.search(r'def create_model', content)
    if match:
        start = match.start()
        end = min(len(content), match.start() + 1000)
        print(content[start:end])
