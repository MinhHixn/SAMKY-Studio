import os
import re

filepath = 'scripts/run_parallel_simulation.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Let's find where the model is initialized.
    # The error message implies that camel is trying to use tool use.
    # OpenRouter error: 'No endpoints found that support tool use. Try disabling \"create_post\".'
    
    # In camel-ai/oasis, agents often have tool-use enabled by default.
    # We need to find the initialization of the OASIS environment or agents.
    
    print(content[content.find('class SimulationRunner'):content.find('class SimulationRunner')+1000])
