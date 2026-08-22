from __future__ import annotations

import ast
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from .dataio import read_jsonl
from .selection import CODE_CHALLENGE_IDS, select_by_ids


_ALLOWED_IMPORTS = frozenset(
    {
        "bisect",
        "cmath",
        "collections",
        "decimal",
        "fractions",
        "functools",
        "hashlib",
        "heapq",
        "itertools",
        "math",
        "operator",
        "random",
        "re",
        "statistics",
        "string",
        "typing",
    }
)
_BLOCKED_CALLS = frozenset(
    {
        "open",
        "exec",
        "compile",
        "__import__",
        "input",
        "breakpoint",
        "exit",
        "quit",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "dir",
    }
)
_BLOCKED_ATTRIBUTES = frozenset(
    {
        "system",
        "popen",
        "fork",
        "spawn",
        "kill",
        "urlopen",
        "sys",
        "os",
        "subprocess",
        "socket",
        "pathlib",
        "builtins",
        "importlib",
    }
)
_ALLOWED_TOP_LEVEL = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Import,
    ast.ImportFrom,
    ast.Assign,
    ast.AnnAssign,
)


class _CandidateGuard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.safe = True

    def visit_Import(self, node: ast.Import) -> None:
        if any(alias.name.split(".", 1)[0] not in _ALLOWED_IMPORTS for alias in node.names):
            self.safe = False
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if node.level or root not in _ALLOWED_IMPORTS:
            self.safe = False
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_CALLS:
            self.safe = False
        if isinstance(node.func, ast.Attribute) and node.func.attr in _BLOCKED_ATTRIBUTES:
            self.safe = False
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            self.safe = False
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_") or node.attr in _BLOCKED_ATTRIBUTES:
            self.safe = False
        self.generic_visit(node)


def _candidate_is_guarded(source: str) -> bool:
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if not isinstance(node, _ALLOWED_TOP_LEVEL):
            return False
    guard = _CandidateGuard()
    guard.visit(tree)
    return guard.safe


def _run_humaneval(prompt: str, completion: str, test: str, entry: str, timeout: float = 8.0) -> bool:
    # strip markdown fences
    body = completion
    m = re.search(r"```(?:python)?\s*([\s\S]*?)```", completion)
    if m:
        body = m.group(1)
    # A model may repeat the complete entry-point definition. Treat only an
    # unindented definition of that exact function as a full replacement;
    # nested helper definitions are part of an ordinary completion.
    repeated_entry = re.search(rf"(?m)^def\s+{re.escape(entry)}\s*\(", body)
    candidate_source = body[repeated_entry.start() :] if repeated_entry else prompt + body
    if not _candidate_is_guarded(candidate_source):
        return False
    with tempfile.TemporaryDirectory() as td:
        candidate_path = Path(td) / "candidate.py"
        tests_path = Path(td) / "tests.py"
        harness_path = Path(td) / "harness.py"
        candidate_path.write_text(candidate_source, encoding="utf-8")
        tests_path.write_text(test, encoding="utf-8")
        success_token = f"SIXCAT_HARNESS_OK_{secrets.token_hex(16)}"
        harness = (
            "import ast\n"
            "import builtins\n"
            "import runpy\n"
            "import traceback\n"
            f"candidate_path = {str(candidate_path)!r}\n"
            f"tests_path = {str(tests_path)!r}\n"
            f"entry_point = {entry!r}\n"
            f"success_token = {success_token!r}\n"
            f"allowed_imports = {sorted(_ALLOWED_IMPORTS)!r}\n"
            "real_import = builtins.__import__\n"
            "def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):\n"
            "    root = name.split('.', 1)[0]\n"
            "    if level or root not in allowed_imports:\n"
            "        raise ImportError(f'import of {name!r} is blocked by the HumanEval guard')\n"
            "    return real_import(name, globals, locals, fromlist, level)\n"
            "def safe_arithmetic_eval(expression):\n"
            "    tree = ast.parse(str(expression), mode='eval')\n"
            "    def visit(node):\n"
            "        if isinstance(node, ast.Constant) and type(node.value) in (int, float):\n"
            "            return node.value\n"
            "        if isinstance(node, ast.UnaryOp):\n"
            "            value = visit(node.operand)\n"
            "            if isinstance(node.op, ast.UAdd):\n"
            "                return +value\n"
            "            if isinstance(node.op, ast.USub):\n"
            "                return -value\n"
            "        if isinstance(node, ast.BinOp):\n"
            "            left, right = visit(node.left), visit(node.right)\n"
            "            if isinstance(node.op, ast.Add):\n"
            "                return left + right\n"
            "            if isinstance(node.op, ast.Sub):\n"
            "                return left - right\n"
            "            if isinstance(node.op, ast.Mult):\n"
            "                return left * right\n"
            "            if isinstance(node.op, ast.Div):\n"
            "                return left / right\n"
            "            if isinstance(node.op, ast.FloorDiv):\n"
            "                return left // right\n"
            "            if isinstance(node.op, ast.Mod):\n"
            "                return left % right\n"
            "            if isinstance(node.op, ast.Pow):\n"
            "                return left ** right\n"
            "        raise ValueError('safe eval accepts numeric arithmetic only')\n"
            "    return visit(tree.body)\n"
            "candidate_builtins = dict(vars(builtins))\n"
            "for blocked_name in ('open', 'exec', 'compile', 'input', 'breakpoint', "
            "'exit', 'quit', 'getattr', 'setattr', 'delattr', 'globals', 'locals', "
            "'vars', 'dir'):\n"
            "    candidate_builtins.pop(blocked_name, None)\n"
            "candidate_builtins['__import__'] = guarded_import\n"
            "candidate_builtins['eval'] = safe_arithmetic_eval\n"
            "try:\n"
            "    candidate_namespace = runpy.run_path(\n"
            "        candidate_path,\n"
            "        init_globals={'__builtins__': candidate_builtins},\n"
            "        run_name='candidate',\n"
            "    )\n"
            "    test_globals = dict(candidate_namespace)\n"
            "    test_globals['__builtins__'] = vars(builtins)\n"
            "    test_namespace = runpy.run_path(\n"
            "        tests_path, init_globals=test_globals, run_name='tests'\n"
            "    )\n"
            "    candidate = candidate_namespace.get(entry_point)\n"
            "    checker = test_namespace.get('check')\n"
            "    if not callable(candidate) or not callable(checker):\n"
            "        raise AssertionError('candidate or check is not callable')\n"
            "    checker(candidate)\n"
            "except BaseException:\n"
            "    traceback.print_exc()\n"
            "    raise SystemExit(1)\n"
            "print(success_token, flush=True)\n"
        )
        harness_path.write_text(harness, encoding="utf-8")
        child_env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "HOME"}
        }
        child_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"})
        try:
            r = subprocess.run(
                [sys.executable, "-I", "-S", str(harness_path)],
                capture_output=True,
                cwd=td,
                env=child_env,
                timeout=timeout,
                text=True,
            )
        except subprocess.TimeoutExpired:
            return False
        stdout_lines = r.stdout.splitlines()
        return r.returncode == 0 and bool(stdout_lines) and stdout_lines[-1] == success_token


def run_code(
    client,
    limit: int | None,
    session=None,
    max_tokens: int | None = None,
    *,
    skip_code_exec: bool = False,
) -> list[dict]:
    from .journal import emit, gate

    if skip_code_exec:
        return []
    mt = 1024 if max_tokens is None else max_tokens
    rows = []
    items = select_by_ids(
        read_jsonl("humaneval.jsonl"),
        limit,
        CODE_CHALLENGE_IDS,
        key=lambda item: str(item.get("task_id") or ""),
    )
    for item in items:
        key = str(item.get("task_id") or "unknown")
        g = gate(session, "code", key)
        if g == "stop":
            return rows
        if isinstance(g, dict):
            rows.append(g)
            continue
        prompt = item["prompt"]
        out = client.complete(
            "Complete the following Python function. Output only code.\n\n" + prompt,
            max_tokens=mt,
        )
        ok = _run_humaneval(prompt, out["text"] or "", item["test"], item["entry_point"])
        usage = out.get("usage") or {}
        rows.append(
            emit(
                session,
                "code",
                key,
                {
                    "ok": ok,
                    "pred": (out["text"] or "")[:200],
                    "raw_text": out["text"] or "",
                    "reasoning_content": out.get("reasoning_content") or "",
                    "parse_confidence": "not_applicable",
                    "task_id": key,
                    "entry_point": item["entry_point"],
                    # task_id is the deterministic locator into the shipped dataset; the
                    # large prompt/tests need not be duplicated into every result row.
                    "grader": {
                        "name": "humaneval-local",
                        "dataset": "humaneval.jsonl",
                        "task_id": key,
                        "entry_point": item["entry_point"],
                    },
                    "finish": out.get("finish"),
                    "ctok": usage.get("completion_tokens"),
                    "ptok": usage.get("prompt_tokens"),
                    "request_params": out.get("request_params"),
                },
            )
        )
    return rows
