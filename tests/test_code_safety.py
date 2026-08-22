from __future__ import annotations

from unittest.mock import patch


def test_humaneval_correct_completion_passes():
    from sixcat.code import _run_humaneval

    assert _run_humaneval(
        "def add(a, b):\n",
        "    return a + b\n",
        "def check(candidate):\n    assert candidate(1, 2) == 3\n",
        "add",
    )


def test_humaneval_systemexit_zero_cannot_forge_a_pass():
    from sixcat.code import _run_humaneval

    assert not _run_humaneval(
        "def add(a, b):\n",
        "    return 0\n\nraise SystemExit(0)\n",
        "def check(candidate):\n    assert candidate(1, 2) == 3\n",
        "add",
    )


def test_humaneval_low_level_exit_zero_cannot_forge_a_pass():
    from sixcat.code import _run_humaneval

    assert not _run_humaneval(
        "def add(a, b):\n",
        "    __builtins__['__import__']('os')._exit(0)\n",
        "def check(candidate):\n    assert candidate(1, 2) == 3\n",
        "add",
    )


def test_humaneval_guard_rejects_indirect_escape_primitives():
    from sixcat.code import _candidate_is_guarded

    assert not _candidate_is_guarded(
        "def add(a, b):\n    return __builtins__['open']('victim', 'w').write('x')\n"
    )
    assert not _candidate_is_guarded(
        "def add(a, b):\n    return getattr(__builtins__, 'open')('victim', 'w').write('x')\n"
    )
    assert not _candidate_is_guarded(
        "import typing\ndef add(a, b):\n    return typing.sys.modules['os'].remove('victim')\n"
    )
    assert not _candidate_is_guarded(
        "import random\ndef add(a, b):\n    return random._os.remove('victim')\n"
    )


def test_humaneval_guard_rejects_host_side_effect_primitives():
    from sixcat.code import _run_humaneval

    dangerous = (
        "    import os\n    os.remove('victim')\n    return a + b\n",
        "    import subprocess\n    subprocess.run(['whoami'])\n    return a + b\n",
        "    import socket\n    return a + b\n",
        "    open('victim', 'w').write('x')\n    return a + b\n",
        "    exec('return 3')\n",
        "    return ().__class__.__mro__\n",
    )
    for completion in dangerous:
        assert not _run_humaneval(
            "def add(a, b):\n",
            completion,
            "def check(candidate):\n    assert candidate(1, 2) == 3\n",
            "add",
        )


def test_humaneval_guard_allows_normal_stdlib_math_imports():
    from sixcat.code import _run_humaneval

    assert _run_humaneval(
        "def root(n):\n",
        "    import math\n    return math.isqrt(n)\n",
        "def check(candidate):\n    assert candidate(81) == 9\n",
        "root",
    )


def test_humaneval_guard_accepts_canonical_safe_eval_and_hashlib():
    from sixcat.code import _run_humaneval

    assert _run_humaneval(
        "def do_algebra(operator, operand):\n",
        "    expression = str(operand[0])\n"
        "    for oprt, oprn in zip(operator, operand[1:]):\n"
        "        expression += oprt + str(oprn)\n"
        "    return eval(expression)\n",
        "def check(candidate):\n    assert candidate(['+', '*', '-'], [2, 3, 4, 5]) == 9\n",
        "do_algebra",
    )
    assert _run_humaneval(
        "def string_to_md5(text):\n",
        "    import hashlib\n"
        "    return hashlib.md5(text.encode('ascii')).hexdigest() if text else None\n",
        "def check(candidate):\n"
        "    assert candidate('Hello world') == '3e25960a79dbc69b674cd4ec67a72c62'\n"
        "    assert candidate('') is None\n",
        "string_to_md5",
    )


def test_humaneval_preserves_nested_helper_definitions_in_completion():
    from sixcat.code import _run_humaneval

    assert _run_humaneval(
        "def add_then_increment(a, b):\n",
        "    def increment(value):\n"
        "        return value + 1\n"
        "    return increment(a + b)\n",
        "def check(candidate):\n    assert candidate(1, 2) == 4\n",
        "add_then_increment",
    )


def test_humaneval_tests_can_reference_candidate_module_helpers():
    from sixcat.code import _run_humaneval

    assert _run_humaneval(
        "def helper(value):\n"
        "    return value + 1\n\n"
        "def solve(value):\n",
        "    return helper(value)\n",
        "def check(candidate):\n"
        "    assert helper(1) == 2\n"
        "    assert candidate(2) == 3\n",
        "solve",
    )


def test_code_execution_can_be_skipped_explicitly():
    from sixcat.code import run_code

    class FailClient:
        def complete(self, *args, **kwargs):
            raise AssertionError("model must not be called when code execution is explicitly skipped")

    with patch("sixcat.code.read_jsonl") as read_jsonl:
        rows = run_code(FailClient(), limit=1, skip_code_exec=True)

    assert rows == []
    read_jsonl.assert_not_called()


def test_run_battery_labels_disabled_code_execution_and_omits_code_score():
    from unittest.mock import patch

    from sixcat.policy import strict_policy
    from sixcat.run import run_battery

    class FakeClient:
        policy = strict_policy()
        model = "fixture-model"
        base_url = "http://fixture/v1"
        api_key = "none"

        def complete(self, prompt, **kwargs):
            return {
                "text": "391",
                "reasoning_content": "",
                "finish": "stop",
                "usage": {"completion_tokens": 1},
            }

    row = {"ok": True, "finish": "stop", "ctok": 1, "parse_confidence": "high"}
    with (
        patch("sixcat.run.fetch_server_props", return_value={"source": "test"}),
        patch("sixcat.run.run_knowledge", return_value=[row]),
        patch("sixcat.run.run_math", return_value=[row]),
        patch("sixcat.run.run_truth", return_value=[row]),
        patch("sixcat.run.run_instruct", return_value=[row]),
        patch("sixcat.run.run_code", return_value=[]) as run_code,
        patch("sixcat.run.run_tools", return_value=[row]),
    ):
        result = run_battery(FakeClient(), limit=1, skip_code_exec=True)

    run_code.assert_called_once()
    assert run_code.call_args.kwargs["skip_code_exec"] is True
    assert result["code_execution"] == "disabled"
    assert result["categories"]["code"] is None
    assert result["n"]["code"] == 0
    assert "code-exec-disabled" in result["overall_flags"]
    assert result["overall"]["score"] == 100.0
