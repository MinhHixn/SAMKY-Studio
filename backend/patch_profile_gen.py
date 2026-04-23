import os
import re

filepath = 'app/services/oasis_profile_generator.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Update _generate_profile_with_llm to use json_repair
    # We want to replace result = json.loads(content) with a json_repair version
    
    new_content = content.replace(
        'result = json.loads(content)',
        'if json_repair:\n                    result = json_repair.loads(content)\n                else:\n                    result = json.loads(content)'
    )
    
    # Also update _try_fix_json
    new_content = new_content.replace(
        'result = json.loads(json_str)',
        'if json_repair:\n                result = json_repair.loads(json_str)\n            else:\n                result = json.loads(json_str)'
    )

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Updated app/services/oasis_profile_generator.py with json_repair.")
    else:
        print("No changes needed in app/services/oasis_profile_generator.py.")
