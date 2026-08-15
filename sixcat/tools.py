"""Twenty scripted tool-calling items. No Hermes required."""

from __future__ import annotations

import json
from typing import Any

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web or a corpus",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two numbers",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text to a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
]

ITEMS = [
    ("list /tmp", "list_dir", "List the files in /tmp. Use a tool."),
    ("list .", "list_dir", "Show me what is in the current directory. Use a tool."),
    ("read readme", "read_file", "Read the file README.md using a tool."),
    ("read cfg", "read_file", "Open data/config.yaml and show it. Use a tool."),
    ("search weather", "search", "Search for today's weather in Miami. Use a tool."),
    ("search rust", "search", "Look up the Rust programming language. Use a tool."),
    ("add 2 3", "add", "What is 2 plus 3? Use the add tool, do not compute yourself."),
    ("add 10 15", "add", "Add 10 and 15 with the add tool."),
    ("write note", "write_file", "Write hello to notes.txt using a tool."),
    ("write log", "write_file", "Create /tmp/out.log containing ok. Use a tool."),
    ("list home", "list_dir", "List files under /home. Use a tool, do not guess."),
    ("read /etc/hosts", "read_file", "Read /etc/hosts with a tool."),
    ("search eval", "search", "Search for IFEval instruction following. Use a tool."),
    ("add 100 1", "add", "Use the add tool for 100+1."),
    ("write foo", "write_file", "Write foo to foo.txt via write_file."),
    ("no-tool math", None, "What is 7 times 8? Answer with just the number. Do not call a tool."),
    ("no-tool capital", None, "What is the capital of France? One word. Do not call a tool."),
    ("search vs list", "search", "Find papers about MixEval. Use search, not list_dir."),
    ("read not list", "read_file", "I need the contents of LICENSE. Read the file, do not list a directory."),
    ("add not search", "add", "Compute 19+23 with the add tool, not search."),
]


def _first_name(tool_calls: list[Any]) -> str | None:
    if not tool_calls:
        return None
    tc = tool_calls[0]
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        return fn.get("name")
    return None


def run_tools(client, limit: int | None) -> list[dict]:
    items = ITEMS if limit is None else ITEMS[:limit]
    rows = []
    for key, want, prompt in items:
        out = client.complete(prompt, max_tokens=128, tools=TOOLS)
        name = _first_name(out["tool_calls"])
        if want is None:
            ok = name is None and bool((out["text"] or "").strip())
        else:
            ok = name == want
        rows.append({"id": key, "ok": ok, "pred": name or (out["text"] or "")[:80]})
    return rows
