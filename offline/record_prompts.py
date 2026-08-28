"""Record the exact prompts sixcat would send at --limit 20, without exposing gold answers."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sixcat import run as sixrun
from sixcat.code import run_code
from sixcat.policy import resolve_policy, STRICT_BUDGETS


class RecorderClient:
    def __init__(self):
        self.model = "GLM-5.3-Flash (self-administered)"
        self.base_url = "http://offline.invalid/v1"
        self.api_key = "none"
        self.timeout = 180.0
        self.policy = resolve_policy("vendor", "glm-5.3")
        self.records = []

    def complete(self, prompt, *, max_tokens=256, tools=None):
        self.records.append(
            {
                "prompt": prompt,
                "max_tokens": max_tokens,
                "has_tools": bool(tools),
            }
        )
        return {
            "text": "A",
            "tool_calls": [],
            "finish": "stop",
            "reasoning_content": "",
            "reasoning_tokens": None,
            "reasoning_details": None,
            "thinking_field": None,
            "usage": {"prompt_tokens": None, "completion_tokens": None, "reasoning_tokens": None},
            "wall_s": 0.0,
            "wall_tps": None,
        }


LIMIT = 20
out_dir = Path(__file__).resolve().parent
client = RecorderClient()

records = []

def capture(cat):
    def wrapper():
        start = len(client.records)
        yield start

    return wrapper

client.records = records
sixrun.run_knowledge(client, LIMIT)
n_knowledge = len(records)
sixrun.run_math(client, LIMIT)
n_math = len(records) - n_knowledge
sixrun.run_truth(client, LIMIT)
n_truth = len(records) - n_math - n_knowledge
sixrun.run_instruct(client, LIMIT)
n_instruct = len(records) - n_truth - n_math - n_knowledge
run_code(client, LIMIT)
n_code = len(records) - n_instruct - n_truth - n_math - n_knowledge
sixrun.run_tools(client, LIMIT)
n_tools = len(records) - n_code - n_instruct - n_truth - n_math - n_knowledge

cats = (
    [("knowledge", n_knowledge), ("math", n_math), ("truth", n_truth), ("instruct", n_instruct), ("code", n_code), ("tools", n_tools)]
)
out = []
idx = 0
for cat, n in cats:
    for j in range(n):
        rec = records[idx]
        out.append({"cat": cat, "i": j, "prompt": rec["prompt"], "max_tokens": rec["max_tokens"], "has_tools": rec["has_tools"]})
        idx += 1

assert idx == len(records), (idx, len(records))
(out_dir / "prompts.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print("recorded", len(out), "prompts:", dict(cats))
