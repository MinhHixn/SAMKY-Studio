import os
import re

filepath = 'scripts/run_parallel_simulation.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove the monkeypatch
    new_content = re.sub(
        r'import warnings\n# MONKEYPATCH:.*?OpenAIModel\.arun = _patched_arun\n',
        'import warnings',
        content,
        flags=re.DOTALL
    )
    
    # Remove the model_config_dict={"tool_choice": "none"} change
    new_content = new_content.replace(
        'model_config_dict={"tool_choice": "none"},',
        ''
    )
    # Also handle the other variation if regex failed earlier
    new_content = re.sub(
        r'\n\s+model_config_dict=\{"tool_choice": "none"\}',
        '',
        new_content
    )

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Reverted tool-use restrictions and monkeypatch in scripts/run_parallel_simulation.py")
    else:
        print("No restrictions found to revert.")
