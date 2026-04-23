import os
import re

filepath = 'scripts/run_parallel_simulation.py'
if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # We need to find the system prompt for the agents.
    # It is likely passed to generate_twitter_agent_graph or similar.
    # Let's search for "system_prompt" or similar.
    
    # Actually, the error message 'No endpoints found that support tool use' is the key.
    # OASIS uses tool use by default for actions.
    
    # Let's check how many times ActionType is used.
    # If we can change LLMAction to take a strategy that doesn't use tools.
    
    # Looking at the code:
    # actions = {agent: LLMAction() for _, agent in active_agents}
    # await result.env.step(actions)
    
    # The OASIS env.step handles the LLM logic.
    
    # One workaround is to FORCE the model to not use tools by changing the CAMEL configuration.
    
    # Let's check the Camel model initialization.
    match = re.search(r'ModelFactory\.create\(', content)
    if match:
        start = max(0, match.start() - 100)
        end = min(len(content), match.end() + 500)
        print(content[start:end])
