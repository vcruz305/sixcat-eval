"""Twenty scripted tool-calling items. No Hermes required."""

from __future__ import annotations

import copy
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
    ("two exact adds", [("add", {"a": 19, "b": 23}), ("add", {"a": 100, "b": 1})], "Call add exactly twice, in this order: first 19+23, then 100+1. Do not answer directly."),
    ("exact multiline write", [("write_file", {"path": "reports/run note.txt", "content": "alpha\nbeta: 2"})], "Use write_file once. Path must be 'reports/run note.txt' and content must be exactly two lines: alpha, then beta: 2."),
    ("confusable exact read", [("read_file", {"path": "data/archive 2026/config.yaml"})], "Read the contents of data/archive 2026/config.yaml. Do not list its directory and do not search for it."),
    ("exact quoted search", [("search", {"query": "HumanEval+ edge case failures"})], "Use search with the exact query: HumanEval+ edge case failures"),
    ("read license distractors", [("read_file", {"path": "LICENSE"})], "The words search and list_dir are distractors. Use read_file to read LICENSE."),
    ("search not filesystem", [("search", {"query": "MixEval benchmark paper"})], "Find the MixEval benchmark paper using search. Do not call list_dir or read_file."),
    ("exact hidden list", [("list_dir", {"path": ".github/workflows"})], "List .github/workflows exactly; do not read any file."),
    ("write json literal", [("write_file", {"path": "out/result.json", "content": "{\"ok\":true,\"n\":3}"})], "Write the exact compact JSON {\"ok\":true,\"n\":3} to out/result.json using write_file."),
    ("decimal add", [("add", {"a": -2.5, "b": 7.75})], "Use add for -2.5 plus 7.75. Do not calculate it yourself."),
    ("two exact reads", [("read_file", {"path": "README.md"}), ("read_file", {"path": "LICENSE"})], "Call read_file twice in order: README.md, then LICENSE."),
    ("no-tool math", None, "What is 7 times 8? Answer with just the number. Do not call any tool, even add."),
    ("no-tool capital", None, "What is the capital of France? One word. Do not call search."),
    ("no-tool explain", None, "In five words, explain what a directory is. Do not call list_dir."),
    ("read cfg", [("read_file", {"path": "data/config.yaml"})], "Open data/config.yaml with read_file and no other tool."),
    ("list home", [("list_dir", {"path": "/home"})], "List files under /home. Use list_dir, do not guess."),
    ("search weather", [("search", {"query": "today's weather in Miami"})], "Search using the exact query today's weather in Miami."),
    ("write trailing newline", [("write_file", {"path": "notes.txt", "content": "hello\n"})], "Write hello followed by one newline to notes.txt."),
    ("negative add", [("add", {"a": -19, "b": -23})], "Use add to combine negative nineteen and negative twenty-three."),
    ("read readme", [("read_file", {"path": "README.md"})], "Read README.md using exactly one tool call."),
    ("list current", [("list_dir", {"path": "."})], "List the current directory using path '.'."),
]


def _first_name(tool_calls: list[Any]) -> str | None:
    if not tool_calls:
        return None
    tc = tool_calls[0]
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        return fn.get("name")
    return None


def _normalise_calls(tool_calls: list[Any]) -> list[tuple[str | None, Any]]:
    normalised = []
    for tool_call in tool_calls or []:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        function = function if isinstance(function, dict) else {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                pass
        normalised.append((function.get("name"), arguments))
    return normalised


def _tool_answer_ok(want: Any, tool_calls: list[Any], text: str) -> tuple[bool, Any]:
    calls = _normalise_calls(tool_calls)
    if want is None:
        return not calls and bool(text.strip()), calls or text[:80]
    if isinstance(want, str):
        return bool(calls) and calls[0][0] == want, calls[0][0] if calls else None
    expected = [(name, arguments) for name, arguments in want]
    return calls == expected, calls


def run_tools(client, limit: int | None, session=None, max_tokens: int | None = None) -> list[dict]:
    from .journal import emit, gate

    mt = 256 if max_tokens is None else max_tokens
    items = ITEMS if limit is None else ITEMS[:limit]
    rows = []
    for name, want, prompt in items:
        key = f"tool:{name}"
        g = gate(session, "tools", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        out = client.complete(prompt, max_tokens=mt, tools=TOOLS)
        ok, pred = _tool_answer_ok(want, out["tool_calls"], out["text"] or "")
        usage = out.get("usage") or {}
        rows.append(
            emit(
                session,
                "tools",
                key,
                {
                    "ok": ok,
                    "pred": pred,
                    "gold": want,
                    "raw_text": out["text"] or "",
                    "reasoning_content": out.get("reasoning_content") or "",
                    "tool_calls": copy.deepcopy(out["tool_calls"]),
                    "parse_confidence": "not_applicable",
                    "prompt": prompt,
                    "grader": {"name": "structured-tool-call", "item": name},
                    "finish": out.get("finish"),
                    "ctok": usage.get("completion_tokens"),
                    "ptok": usage.get("prompt_tokens"),
                    "request_params": out.get("request_params"),
                },
            )
        )
    return rows
