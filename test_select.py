import os
from ecogent_experiment.tool_registry import ToolRegistry
from ecogent_experiment.inference import create_engine_from_config
from ecogent_experiment.tiny_llm import TinyLLM

r = ToolRegistry(os.path.join('data', 'chroma'))
res = r.search_all_collections('please search google with KKBAU and tell me the result', n_results=5)
print('Candidates:', [t['tool_key'] for t in res])

import ecogent_experiment.tiny_llm
ecogent_experiment.tiny_llm.TOOL_SELECTION_PROMPT = """<|im_start|>system
You are a tool selector. You must choose the single best tool for the user's task from the list below.

Available tools:
{tools}

You must return a valid JSON object with a single key "tool" and the name of the selected tool as its value.
<|im_end|>
<|im_start|>user
Task: "{task}"
<|im_end|>
<|im_start|>assistant
"""

engine = create_engine_from_config(os.path.join('config', 'config.json'))
llm = TinyLLM(engine)
candidate_names = [f"{t.get('tool_key')}: {t.get('description', '')}" for t in res]
print('Candidate names:', candidate_names)

decision = llm.select_tool('please search google with KKBAU and tell me the result', candidate_names)
print('Decision:', decision)
