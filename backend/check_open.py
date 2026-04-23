import os
import re

for root, _, files in os.walk('.'):
    if '.venv' in root or '.pytest_cache' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            # Find open( without encoding
            matches = re.finditer(r'open\([^)]*\)', content)
            for m in matches:
                if 'encoding' not in m.group(0):
                    print(f"Missing encoding in {filepath}: {m.group(0)}")
