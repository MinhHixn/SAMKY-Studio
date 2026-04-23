import os
import re

def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        return

    new_content = re.sub(
        r'([ \t]*)(conn = sqlite3\.connect\(.*?\))',
        r'\1\2\n\1conn.execute("PRAGMA encoding = \'UTF-8\';")',
        content
    )

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, _, files in os.walk('.'):
    if '.venv' in root or '.pytest_cache' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))
