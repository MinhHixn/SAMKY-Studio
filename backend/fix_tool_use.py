import os
import re

filepath = 'scripts/run_parallel_simulation.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # We want to change:
    # return ModelFactory.create(
    #     model_platform=ModelPlatformType.OPENAI,
    #     model_type=llm_model,
    # )
    # to:
    # return ModelFactory.create(
    #     model_platform=ModelPlatformType.OPENAI,
    #     model_type=llm_model,
    #     model_config_dict={'tool_choice': 'none'}
    # )
    #
    # However, ModelFactory.create takes ModelConfig.
    # Let's check imports to see if ModelConfig is available.
    
    new_content = re.sub(
        r'(return ModelFactory\.create\(\s+model_platform=ModelPlatformType\.OPENAI,\s+model_type=llm_model,)(\s+\))',
        r'\1\n        model_config_dict={"tool_choice": "none"}\2',
        content,
        flags=re.DOTALL
    )
    
    if 'model_config_dict' not in new_content:
        # Fallback if the regex didn't match exactly
        new_content = content.replace(
            'model_type=llm_model,',
            'model_type=llm_model,\n        model_config_dict={"tool_choice": "none"},'
        )

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath} to disable tool choice.")
