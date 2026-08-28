"""Replay my recorded answers through sixcat's real battery + scoring code."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sixcat import run as sixrun
from sixcat.client import ChatClient
from sixcat.policy import resolve_policy

HERE = Path(__file__).resolve().parent
prompts = json.loads((HERE / "prompts.json").read_text(encoding="utf-8"))
answers = json.loads((HERE / "answers.json").read_text(encoding="utf-8"))
assert len(prompts) == len(answers)

# Do not let answers drift out of alignment with prompts: verify recorded prompt hashes.
import hashlib

class ReplayClient(ChatClient):
    def __init__(self, answers):
        super().__init__(
            base_url="http://offline.invalid/v1",
            model="GLM-5.3-Flash (session model, self-administered)",
            policy=resolve_policy("vendor", "glm-5.3"),
        )
        self._answers = answers
        self._idx = 0

    def complete(self, prompt, *, max_tokens=256, tools=None):
        rec = prompts[self._idx]
        assert hashlib.sha1(prompt.encode()).hexdigest() == hashlib.sha1(rec["prompt"].encode()).hexdigest(), f"prompt drift at {self._idx}"
        ans = self._answers[self._idx]
        self._idx += 1
        tool_calls = [
            {"function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
            for c in ans.get("tool_calls", [])
        ]
        return {
            "text": ans.get("text", ""),
            "tool_calls": tool_calls,
            "finish": "stop",
            "reasoning_content": "",
            "reasoning_tokens": None,
            "reasoning_details": None,
            "thinking_field": None,
            "usage": {"prompt_tokens": None, "completion_tokens": None, "reasoning_tokens": None},
            "wall_s": 0.01,
            "wall_tps": None,
        }

client = ReplayClient(answers)

# Patch network/preflight dependencies with offline stand-ins.
sixrun.fetch_server_props = lambda *a, **k: {}
sixrun.probe_policy = lambda *a, **k: {"status": "ok", "reason": "offline replay"}
sixrun.assemble_preflight = lambda **k: {"note": "offline replay, preflight skipped"}

result = sixrun.run_battery(client, limit=20)
out = HERE / "run.json"
out.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(sixrun.render_table(result))
print(f"\nsaved: {out}  |  replayed {client._idx} items")
