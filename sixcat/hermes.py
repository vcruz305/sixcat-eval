from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import inspect
import time
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator
from urllib.parse import urlparse


def find_project_root(*, script_path: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    configured = os.environ.get("SIXCAT_PROJECT_ROOT")
    if configured:
        candidates.append(Path(configured).expanduser())
    cwd = Path.cwd().resolve()
    candidates.extend((cwd, *cwd.parents))
    source = (script_path or Path(__file__)).resolve()
    candidates.extend(source.parents)
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "sixcat" / "__main__.py").is_file() and (resolved / "pyproject.toml").is_file():
            return resolved
    return None


PROJECT_ROOT = find_project_root()
if PROJECT_ROOT is not None and str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class HermesRuntimeTarget:
    def __init__(
        self,
        *,
        profile: str,
        model: str,
        provider: str,
        runtime: dict[str, Any],
    ) -> None:
        self.profile = profile
        self.model = model
        self.provider = provider
        self.runtime = dict(runtime)


class ProxyInfo:
    def __init__(self, *, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_provider(value: Any) -> str:
    return _clean_text(value).casefold().replace("_", "-")


def _route_value(route_info: dict[str, Any], key: str) -> str:
    return _clean_text(
        route_info.get(key)
        or route_info.get(f"effective_{key}")
        or route_info.get(f"resolved_{key}")
    )


def require_exact_route(
    route_info: dict[str, Any],
    *,
    expected_provider: str,
    expected_model: str,
) -> None:
    actual_provider = _route_value(route_info, "provider")
    actual_model = _route_value(route_info, "model")
    provider_matches = _canonical_provider(actual_provider) == _canonical_provider(expected_provider)
    model_matches = actual_model == expected_model
    if not provider_matches or not model_matches:
        raise RuntimeError(
            "Hermes runtime identity drift: "
            f"expected {expected_provider}/{expected_model}, "
            f"got {actual_provider or 'unknown'}/{actual_model or 'unknown'}"
        )


def _auth_resolved(runtime: dict[str, Any]) -> bool:
    return bool(
        runtime.get("api_key")
        or runtime.get("credential_pool")
        or runtime.get("command")
        or runtime.get("acp_command")
    )


def public_target_receipt(target: HermesRuntimeTarget) -> dict[str, Any]:
    return {
        "status": "ready",
        "target_kind": "hermes_runtime_model",
        "profile": target.profile,
        "model": target.model,
        "provider": target.provider,
        "api_mode": _clean_text(target.runtime.get("api_mode")) or None,
        "auth": "resolved" if _auth_resolved(target.runtime) else "missing",
    }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    if isinstance(value, SimpleNamespace) or hasattr(value, "__dict__"):
        return {
            str(key): _jsonable(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _validate_request_identity(payload: dict[str, Any], target: HermesRuntimeTarget) -> None:
    requested_model = _clean_text(payload.get("model"))
    requested_provider = _clean_text(payload.get("provider"))
    if requested_model and requested_model != target.model:
        raise ValueError(
            f"requested model {requested_model!r} does not match pinned Hermes runtime {target.model!r}"
        )
    if requested_provider and _canonical_provider(requested_provider) != _canonical_provider(target.provider):
        raise ValueError(
            f"requested provider {requested_provider!r} does not match pinned Hermes runtime {target.provider!r}"
        )


def build_call_spec(payload: dict[str, Any], target: HermesRuntimeTarget) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    _validate_request_identity(payload, target)

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")

    temperature = payload.get("temperature")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        temperature = None

    max_tokens = payload.get("max_tokens", payload.get("max_completion_tokens"))
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        max_tokens = None

    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else None
    # Preserve task controls (notably tool_choice) and reviewed vendor fields.
    # Transport/identity fields are owned by this adapter, never extra_body.
    owned = {"model", "provider", "messages", "temperature", "max_tokens",
             "max_completion_tokens", "tools", "timeout", "stream", "stream_options"}
    extra_body = {key: value for key, value in payload.items()
                  if key not in owned and value is not None}

    chat_template_kwargs = payload.get("chat_template_kwargs")
    reasoning_config = None
    if isinstance(chat_template_kwargs, dict):
        extra_body["chat_template_kwargs"] = dict(chat_template_kwargs)
        enabled = chat_template_kwargs.get("enable_thinking")
        if isinstance(enabled, bool):
            reasoning_config = {"enabled": enabled}

    route_info: dict[str, str] = {}
    return {
        "task": None,
        "provider": target.provider,
        "model": target.model,
        "base_url": target.runtime.get("base_url"),
        "api_key": target.runtime.get("api_key"),
        "main_runtime": target.runtime,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "tools": tools,
        "timeout": float(payload.get("timeout") or 180.0),
        "extra_body": extra_body,
        "reasoning_config": reasoning_config,
        "api_mode": target.runtime.get("api_mode"),
        "route_info": route_info,
        # Hermes' non-stream auxiliary path can switch provider/model on quota
        # exhaustion *before* our route check. The streaming path skips that
        # recovery ladder. Assemble it locally; never retry as non-stream.
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def collect_response(response: Any) -> dict[str, Any]:
    """Reassemble one raw completion, without tools, grading, retries or fallback.

    Some Hermes provider shims return a completed object even for stream=True.
    A broken stream must raise, not turn its partial answer into a scored sample.
    This bridge intentionally returns complete JSON, not client-side SSE timing.
    """
    if isinstance(response, dict) or hasattr(response, "choices"):
        result = _jsonable(response)
        if not isinstance(result, dict) or not result.get("choices"):
            raise RuntimeError("Hermes returned no completion choices")
        if any(not isinstance(c, dict) or not c.get("finish_reason")
               or not isinstance(c.get("message"), dict) for c in result["choices"]):
            raise RuntimeError("Hermes returned an unfinished completion")
        return result

    result: dict[str, Any] = {"object": "chat.completion", "choices": []}
    message: dict[str, Any] = {"role": "assistant", "content": ""}
    tool_calls: dict[int, dict[str, Any]] = {}
    finish = None
    size = 0
    try:
        for raw in response:
            chunk = _jsonable(raw)
            if not isinstance(chunk, dict):
                raise RuntimeError("Hermes returned a malformed stream chunk")
            if chunk.get("error"):
                raise RuntimeError("Hermes returned an upstream stream error")
            for key in ("id", "model", "created", "system_fingerprint", "usage", "timings"):
                if chunk.get(key) is not None:
                    result[key] = chunk[key]
            for choice in chunk.get("choices") or []:
                if choice.get("index", 0) != 0:
                    raise RuntimeError("Sixcat expects exactly one completion choice")
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    raise RuntimeError("Hermes returned a malformed completion delta")
                for key in ("content", "reasoning_content", "reasoning", "refusal"):
                    text = delta.get(key)
                    if isinstance(text, str):
                        size += len(text.encode("utf-8"))
                        message[key] = message.get(key, "") + text
                if isinstance(delta.get("reasoning_details"), list):
                    message.setdefault("reasoning_details", []).extend(delta["reasoning_details"])
                    size += len(json.dumps(delta["reasoning_details"]))
                for part in delta.get("tool_calls") or []:
                    index = part.get("index", 0)
                    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 128:
                        raise RuntimeError("Hermes returned an invalid tool-call index")
                    tool = tool_calls.setdefault(index, {"type": "function", "function": {"name": "", "arguments": ""}})
                    for key in ("id", "type"):
                        if part.get(key):
                            tool[key] = part[key]
                    for key in ("name", "arguments"):
                        fragment = (part.get("function") or {}).get(key)
                        if isinstance(fragment, str):
                            size += len(fragment.encode("utf-8"))
                            tool["function"][key] += fragment
                if choice.get("finish_reason") is not None:
                    finish = choice["finish_reason"]
            if size > 16 * 1024 * 1024:
                raise RuntimeError("Hermes completion exceeded the 16 MiB adapter limit")
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    if not finish:
        raise RuntimeError("Hermes stream ended before finish_reason; partial answer not scored")
    if tool_calls:
        message["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
    result["choices"] = [{"index": 0, "message": message, "finish_reason": finish}]
    return result


def call_target(
    payload: dict[str, Any],
    target: HermesRuntimeTarget,
    *,
    call_llm_fn: Callable[..., Any],
) -> dict[str, Any]:
    spec = build_call_spec(payload, target)
    # Fail before dispatch on older Hermes versions; silently dropping stream=True
    # would restore its provider-fallback ladder.
    parameters = inspect.signature(call_llm_fn).parameters
    if "stream" not in parameters and not any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    ):
        raise RuntimeError("This Hermes version lacks the pinned streaming call API; update Hermes")
    response = call_llm_fn(**spec)
    try:
        require_exact_route(spec["route_info"], expected_provider=target.provider,
                            expected_model=target.model)
    except BaseException:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise
    normalized = collect_response(response)
    require_exact_route(spec["route_info"], expected_provider=target.provider,
                        expected_model=target.model)
    normalized.setdefault("object", "chat.completion")
    normalized.setdefault("model", target.model)
    return normalized


def _safe_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    try:
        from agent.redact import redact_sensitive_text

        text = redact_sensitive_text(text, force=True)
    except Exception:
        text = re.sub(r"(?i)(api[_-]?key|token|authorization)\s*[=:]\s*\S+", r"\1=[REDACTED]", text)
    return text[:500]


def _handler_class(
    target: HermesRuntimeTarget,
    *,
    api_key: str,
    call_llm_fn: Callable[..., Any],
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SixcatHermesModelProxy/1.0"

        def log_message(self, _format: str, *args: Any) -> None:
            return

        def _authorized(self) -> bool:
            return self.headers.get("Authorization", "") == f"Bearer {api_key}"

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _require_auth(self) -> bool:
            if self._authorized():
                return True
            self._send_json(
                401,
                {"error": {"message": "Unauthorized", "type": "authentication_error"}},
            )
            return False

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            path = urlparse(self.path).path.rstrip("/")
            if path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            if path == "/v1/models":
                if not self._require_auth():
                    return
                self._send_json(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": target.model,
                                "object": "model",
                                "owned_by": f"hermes-profile:{target.profile}",
                                "root": target.model,
                                "parent": None,
                                "hermes_profile": target.profile,
                                "hermes_provider": target.provider,
                                "hermes_adapter": "pinned-stream-v1",
                                "target_kind": "hermes_runtime_model",
                            }
                        ],
                    },
                )
                return
            self._send_json(404, {"error": {"message": "Not found", "type": "not_found"}})

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            if urlparse(self.path).path.rstrip("/") != "/v1/chat/completions":
                self._send_json(404, {"error": {"message": "Not found", "type": "not_found"}})
                return
            if not self._require_auth():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 10_000_000:
                    raise ValueError("invalid request body size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                response = call_target(payload, target, call_llm_fn=call_llm_fn)
            except ValueError as exc:
                self._send_json(
                    400,
                    {"error": {"message": _safe_error(exc), "type": "invalid_request_error"}},
                )
                return
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if not isinstance(status, int) or isinstance(status, bool) or not 400 <= status <= 599:
                    status = 502
                self._send_json(
                    status,
                    {"error": {"message": _safe_error(exc), "type": "upstream_error"}},
                )
                return
            self._send_json(200, response)

    return Handler


@contextlib.contextmanager
def proxy_server(
    target: HermesRuntimeTarget,
    *,
    call_llm_fn: Callable[..., Any],
) -> Iterator[ProxyInfo]:
    api_key = secrets.token_urlsafe(32)
    handler = _handler_class(target, api_key=api_key, call_llm_fn=call_llm_fn)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="sixcat-hermes-proxy", daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        yield ProxyInfo(base_url=f"http://127.0.0.1:{port}/v1", api_key=api_key)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


def _base_hermes_home(current_home: Path) -> Path:
    if current_home.parent.name.casefold() == "profiles":
        return current_home.parent.parent
    return current_home


def resolve_profile_home(profile: str) -> tuple[str, Path]:
    current_home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser().resolve()
    if profile == "current" and not os.environ.get("HERMES_HOME"):
        # Match Hermes' sticky profile outside an already-running session.
        try:
            active = (current_home / "active_profile").read_text(encoding="utf-8-sig").strip()
        except FileNotFoundError:
            active = "default"
        if active and active != "default":
            profile = active
    if profile == "current":
        current_name = current_home.name if current_home.parent.name.casefold() == "profiles" else "default"
        return current_name, current_home
    if profile in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", profile):
        raise ValueError("invalid Hermes profile name")
    base_home = _base_hermes_home(current_home)
    target_home = base_home if profile == "default" else base_home / "profiles" / profile
    if not target_home.exists():
        raise ValueError(f"Hermes profile does not exist: {profile}")
    return profile, target_home.resolve()


def _load_profile_model_config(home: Path) -> tuple[str, str]:
    config_path = home / "config.yaml"
    try:
        import yaml

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise RuntimeError(f"cannot read Hermes profile config: {exc}") from exc
    model_cfg = config.get("model") if isinstance(config, dict) else None
    model_cfg = model_cfg if isinstance(model_cfg, dict) else {}
    return _clean_text(model_cfg.get("default")), _clean_text(model_cfg.get("provider"))


def resolve_runtime_target(
    *,
    profile: str,
    runtime_model: str | None = None,
    runtime_provider: str | None = None,
) -> HermesRuntimeTarget:
    profile_name, profile_home = resolve_profile_home(profile)
    os.environ["HERMES_HOME"] = str(profile_home)

    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv(hermes_home=profile_home)
    configured_model, configured_provider = _load_profile_model_config(profile_home)
    model = _clean_text(runtime_model) or configured_model
    provider = _clean_text(runtime_provider) or configured_provider
    if not model or not provider or provider.casefold() == "auto":
        raise RuntimeError("Hermes runtime target requires both an exact model and provider")

    from hermes_cli.runtime_provider import resolve_runtime_provider

    runtime = dict(resolve_runtime_provider(requested=provider, target_model=model) or {})
    runtime.setdefault("provider", provider)
    # An explicit Nous request must never silently become a different provider.
    # Other Hermes aliases can legitimately canonicalize; post-call route checks
    # still pin their resolved provider/model pair.
    if provider.casefold() == "nous" and _canonical_provider(runtime["provider"]) != "nous":
        raise RuntimeError("Hermes resolved a non-Nous provider for an explicit Nous target")
    runtime["model"] = model
    target = HermesRuntimeTarget(
        profile=profile_name,
        model=model,
        provider=_clean_text(runtime.get("provider")) or provider,
        runtime=runtime,
    )
    if not _auth_resolved(runtime):
        raise RuntimeError(f"Hermes could not resolve credentials for provider {target.provider}")
    return target


def inspect_target(target: HermesRuntimeTarget, *, policy_name: str = "vendor",
                   policy_family: str | None = None) -> dict[str, Any]:
    from sixcat.policy import resolve_policy

    receipt = public_target_receipt(target)
    policy = resolve_policy(policy_name, target.model, family=policy_family)
    receipt["recommended_policy"] = "vendor" if policy.name == "vendor" else "strict"
    receipt["resolved_policy"] = policy.to_dict()
    receipt["policy_source"] = policy.source
    receipt["policy_fingerprint"] = policy.fingerprint
    receipt["transport"] = "temporary_loopback_raw_model_proxy"
    receipt["inference_verified"] = False
    receipt["fallback_policy"] = "pinned_stream_no_auxiliary_fallback"
    receipt["billing_verified"] = False
    receipt["warning"] = (
        "Uses Hermes provider/auth resolution but bypasses the Hermes agent facade, "
        "tools, profile persona, memory, and context files."
    )
    return receipt


def _common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default="current")
    parser.add_argument("--runtime-model", default=None)
    parser.add_argument("--runtime-provider", default=None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description="Resolve a Hermes profile runtime and expose its exact model to Sixcat temporarily."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    _common_args(inspect_parser)
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.add_argument("--policy", choices=("strict", "vendor"), default="vendor")
    inspect_parser.add_argument("--policy-family", default=None)

    smoke_parser = subparsers.add_parser("smoke", help="One unscored live request; consumes provider quota")
    _common_args(smoke_parser)
    smoke_parser.add_argument("--json", action="store_true")

    preflight_parser = subparsers.add_parser("preflight", help="Context estimate, not live inference validation")
    _common_args(preflight_parser)
    preflight_parser.add_argument("sixcat_args", nargs=argparse.REMAINDER)

    run_parser = subparsers.add_parser("run")
    _common_args(run_parser)
    run_parser.add_argument("sixcat_args", nargs=argparse.REMAINDER)
    return parser


def _forward_args(args: list[str]) -> list[str]:
    args = list(args)
    if args and args[0] == "--":
        args.pop(0)
    forbidden = {"--base-url", "--model", "--api-key", "--transport"}
    # Core argparse also accepts abbreviations; do not allow --base=... to
    # override the pinned loopback route. Transport is always HTTP here.
    for item in args:
        flag = item.split("=", 1)[0]
        if flag.startswith("--") and any(option.startswith(flag) for option in forbidden):
            raise ValueError("Hermes runtime mode owns --base-url, --model, --api-key and --transport")
    return args


def _main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if sys.version_info < (3, 11):
        raise RuntimeError("Sixcat requires Python 3.11+; use the Python interpreter from your Hermes environment")
    forwarded = _forward_args(args.sixcat_args) if hasattr(args, "sixcat_args") else []
    target = resolve_runtime_target(profile=args.profile, runtime_model=args.runtime_model,
                                    runtime_provider=args.runtime_provider)
    if args.command == "inspect":
        receipt = inspect_target(target, policy_name=args.policy, policy_family=args.policy_family)
        print(json.dumps(receipt, indent=2, ensure_ascii=False) if args.json else receipt)
        return 0

    from agent.auxiliary_client import call_llm
    if args.command == "smoke":
        started = time.monotonic()
        response = call_target({
            "model": target.model,
            "messages": [{"role": "user", "content": "Reply with exactly SIXCAT_OK and nothing else."}],
            "max_tokens": 256, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
        }, target, call_llm_fn=call_llm)
        choice = response["choices"][0]
        text = (choice.get("message") or {}).get("content") or ""
        passed = isinstance(text, str) and text.strip() == "SIXCAT_OK" and choice.get("finish_reason") != "length"
        receipt = {**public_target_receipt(target), "inference_verified": True,
                   "smoke_passed": passed, "billing_verified": False,
                   "benchmark_score": None, "elapsed_seconds": time.monotonic() - started,
                   "finish_reason": choice.get("finish_reason"), "usage": response.get("usage"),
                   "response_model": response.get("model"), "response_text": text}
        print(json.dumps(receipt, indent=2, ensure_ascii=False) if args.json else receipt)
        return 0 if passed else 2

    from sixcat.__main__ import main as sixcat_main
    # Keep machine-readable --json output clean.
    print("HERMES_TARGET " + json.dumps(public_target_receipt(target), ensure_ascii=False),
          file=sys.stderr, flush=True)
    with proxy_server(target, call_llm_fn=call_llm) as proxy:
        command = ["preflight"] if args.command == "preflight" else []
        return sixcat_main([*command, f"--base-url={proxy.base_url}", f"--model={target.model}",
                            f"--api-key={proxy.api_key}", *forwarded])


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (RuntimeError, ValueError, ImportError, OSError) as exc:
        print("Sixcat Hermes: " + _safe_error(exc), file=sys.stderr)
        if isinstance(exc, ImportError):
            print("Use Python 3.11+ from the environment containing Hermes and Sixcat. "
                  "Do not use the system Python or copy Portal tokens into shell commands.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
