from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
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
    extra_body: dict[str, Any] = {}
    for key in (
        "top_p",
        "top_k",
        "min_p",
        "seed",
        "presence_penalty",
        "frequency_penalty",
        "stop",
    ):
        if key in payload and payload[key] is not None:
            extra_body[key] = payload[key]

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
    }


def call_target(
    payload: dict[str, Any],
    target: HermesRuntimeTarget,
    *,
    call_llm_fn: Callable[..., Any],
) -> dict[str, Any]:
    spec = build_call_spec(payload, target)
    response = call_llm_fn(**spec)
    require_exact_route(
        spec["route_info"],
        expected_provider=target.provider,
        expected_model=target.model,
    )
    normalized = _jsonable(response)
    if not isinstance(normalized, dict) or not isinstance(normalized.get("choices"), list):
        raise RuntimeError("Hermes direct model call returned no OpenAI-compatible choices")
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
                self._send_json(
                    502,
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
    if profile == "current":
        current_name = current_home.name if current_home.parent.name.casefold() == "profiles" else "default"
        return current_name, current_home
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", profile):
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
    if not model or not provider:
        raise RuntimeError("Hermes runtime target requires both an exact model and provider")

    from hermes_cli.runtime_provider import resolve_runtime_provider

    runtime = dict(resolve_runtime_provider(requested=provider, target_model=model) or {})
    runtime.setdefault("provider", provider)
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


def inspect_target(target: HermesRuntimeTarget) -> dict[str, Any]:
    from sixcat.policy import resolve_policy

    receipt = public_target_receipt(target)
    policy = resolve_policy("vendor", target.model)
    receipt["recommended_policy"] = "vendor" if policy.name == "vendor" else "strict"
    receipt["resolved_policy"] = policy.to_dict()
    receipt["policy_source"] = policy.source
    receipt["policy_fingerprint"] = policy.fingerprint
    receipt["transport"] = "temporary_loopback_raw_model_proxy"
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
        description="Resolve a Hermes profile runtime and expose its exact model to Sixcat temporarily."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    _common_args(inspect_parser)
    inspect_parser.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run")
    _common_args(run_parser)
    run_parser.add_argument("sixcat_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    target = resolve_runtime_target(
        profile=args.profile,
        runtime_model=args.runtime_model,
        runtime_provider=args.runtime_provider,
    )
    if args.command == "inspect":
        receipt = inspect_target(target)
        print(json.dumps(receipt, indent=2, ensure_ascii=False) if args.json else receipt)
        return 0

    from agent.auxiliary_client import call_llm
    from sixcat.__main__ import main as sixcat_main

    sixcat_args = list(args.sixcat_args)
    if sixcat_args and sixcat_args[0] == "--":
        sixcat_args = sixcat_args[1:]
    forbidden = {"--base-url", "--model", "--api-key"}
    if any(item.split("=", 1)[0] in forbidden for item in sixcat_args):
        raise SystemExit("Hermes runtime mode owns --base-url, --model, and --api-key")

    print("HERMES_TARGET " + json.dumps(public_target_receipt(target), ensure_ascii=False), flush=True)
    with proxy_server(target, call_llm_fn=call_llm) as proxy:
        return sixcat_main(
            [
                "--base-url",
                proxy.base_url,
                "--model",
                target.model,
                "--api-key",
                proxy.api_key,
                *sixcat_args,
            ]
        )


if __name__ == "__main__":
    raise SystemExit(main())
