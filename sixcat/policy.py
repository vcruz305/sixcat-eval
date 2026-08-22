from __future__ import annotations

import copy
import hashlib
import json
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlparse


STRICT_BUDGETS: dict[str, int] = {
    "knowledge": 768,
    "math": 1197,
    "truth": 64,
    "instruct": 1281,
    "code": 1024,
    "tools": 256,
}

THINKING_BUDGETS: dict[str, int] = {
    "knowledge": 1597,
    "math": 2048,
    "truth": 1892,
    "instruct": 6767,
    "code": 3072,
    "tools": 768,
}

VENDOR_DEFAULT_SEED = 1

DEFAULT_POLICY_FILE = Path(__file__).with_name("model-policies.json")

_PROTECTED_EXTRA_FIELDS = frozenset(
    {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "min_p",
        "enable_thinking",
        "chat_template_kwargs",
        "tools",
        "tool_choice",
    }
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return copy.deepcopy(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True)
class Policy:
    """Fully resolved inference policy carried by every sixcat score."""

    name: str
    temperature: float
    top_p: float | None
    top_k: int | None
    min_p: float | None
    thinking: bool
    budgets: Mapping[str, int]
    extra: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)) or self.temperature < 0:
            raise ValueError("policy temperature must be a non-negative number")
        for field_name in ("top_p", "min_p"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1
            ):
                raise ValueError(f"policy {field_name} must be between 0 and 1")
        if self.top_k is not None and (
            isinstance(self.top_k, bool) or not isinstance(self.top_k, int) or self.top_k < 0
        ):
            raise ValueError("policy top_k must be a non-negative integer")
        if not isinstance(self.thinking, bool):
            raise ValueError("policy thinking must be a boolean")
        if not isinstance(self.budgets, dict) or any(
            category not in STRICT_BUDGETS
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for category, value in self.budgets.items()
        ):
            raise ValueError("policy budgets must contain positive integer category budgets")
        if not isinstance(self.extra, dict):
            raise ValueError("policy extra must be an object")
        protected = sorted(_PROTECTED_EXTRA_FIELDS.intersection(self.extra))
        if protected:
            raise ValueError(f"policy extra contains protected request fields: {protected}")
        object.__setattr__(self, "budgets", _freeze(self.budgets))
        object.__setattr__(self, "extra", _freeze(self.extra))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "min_p": self.min_p,
            "thinking": self.thinking,
            "budgets": _thaw(self.budgets),
            "extra": _thaw(self.extra),
            "source": self.source,
        }

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()[:12]


def _with_seed(extra: dict[str, Any], seed: int | None, default: int | None = None) -> dict[str, Any]:
    resolved = dict(extra)
    if seed is not None:
        resolved["seed"] = seed
    elif default is not None and "seed" not in resolved:
        resolved["seed"] = default
    return resolved


def strict_policy(
    budget_overrides: dict[str, int] | None = None,
    *,
    seed: int | None = None,
    source: str = "builtin-strict",
) -> Policy:
    return Policy(
        name="strict",
        temperature=0.0,
        top_p=None,
        top_k=None,
        min_p=None,
        thinking=False,
        budgets={**STRICT_BUDGETS, **(budget_overrides or {})},
        extra=_with_seed({}, seed),
        source=source,
    )


def custom_policy(
    *,
    temperature: float,
    top_p: float | None = None,
    top_k: int | None = None,
    min_p: float | None = None,
    thinking: bool = False,
    seed: int | None = None,
    budget_overrides: dict[str, int] | None = None,
) -> Policy:
    """Build an explicit user-selected sampling policy without hidden defaults."""
    base_budgets = THINKING_BUDGETS if thinking else STRICT_BUDGETS
    return Policy(
        name="custom",
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        min_p=min_p,
        thinking=thinking,
        budgets={**base_budgets, **(budget_overrides or {})},
        extra=_with_seed({}, seed),
        source="user-custom",
    )


def override_thinking(policy: Policy, enabled: bool) -> Policy:
    """Apply an explicit thinking choice while preserving sampling controls."""
    source_defaults = THINKING_BUDGETS if policy.thinking else STRICT_BUDGETS
    target_defaults = THINKING_BUDGETS if enabled else STRICT_BUDGETS
    explicit_overrides = {
        category: value
        for category, value in policy.budgets.items()
        if category not in source_defaults or value != source_defaults[category]
    }
    budgets = {**target_defaults, **explicit_overrides}
    return Policy(
        name=policy.name,
        temperature=policy.temperature,
        top_p=policy.top_p,
        top_k=policy.top_k,
        min_p=policy.min_p,
        thinking=enabled,
        budgets=budgets,
        extra=policy.to_dict()["extra"],
        source=f"{policy.source}|thinking={'on' if enabled else 'off'}:user",
    )


def _load_policy_entries(policy_file: Path | None) -> tuple[list[dict[str, Any]], str]:
    path = Path(policy_file) if policy_file is not None else DEFAULT_POLICY_FILE
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load policy file {path}: {exc}") from exc
    if document.get("schema_version") != 1 or not isinstance(document.get("policies"), list):
        raise ValueError(f"unsupported policy file schema in {path}")
    for index, entry in enumerate(document["policies"]):
        if not isinstance(entry, dict):
            raise ValueError(f"policy entry {index} in {path} must be an object")
        if not isinstance(entry.get("reviewed_date"), str) or not entry["reviewed_date"].strip():
            raise ValueError(f"policy entry {index} in {path} requires reviewed_date")
        source_url = entry.get("source_url")
        try:
            parsed_source = urlparse(source_url) if isinstance(source_url, str) else None
        except ValueError:
            parsed_source = None
        if (
            parsed_source is None
            or parsed_source.scheme.casefold() != "https"
            or not parsed_source.hostname
            or not parsed_source.hostname.strip()
        ):
            raise ValueError(f"policy entry {index} in {path} requires an https source_url")
        required = ("family", "patterns", "verified", "temperature", "top_p", "top_k", "min_p", "thinking", "extra")
        missing = [key for key in required if key not in entry]
        if missing:
            raise ValueError(f"policy entry {index} in {path} missing required setting {missing[0]}")
        if entry["verified"] is not True:
            raise ValueError(f"policy entry {index} in {path} requires verified to be boolean true")
        if not isinstance(entry["family"], str) or not entry["family"].strip():
            raise ValueError(f"policy entry {index} in {path} requires a non-empty string family")
        patterns = entry["patterns"]
        if (
            not isinstance(patterns, list)
            or not patterns
            or any(not isinstance(pattern, str) or not pattern.strip() for pattern in patterns)
        ):
            raise ValueError(
                f"policy entry {index} in {path} requires patterns to be a non-empty list of non-empty strings"
            )
        exclude_patterns = entry.get("exclude_patterns", [])
        if (
            not isinstance(exclude_patterns, list)
            or any(not isinstance(pattern, str) or not pattern.strip() for pattern in exclude_patterns)
        ):
            raise ValueError(
                f"policy entry {index} in {path} requires exclude_patterns to be a list of non-empty strings"
            )
        required_patterns = entry.get("required_patterns")
        if required_patterns is not None and (
            not isinstance(required_patterns, list)
            or not required_patterns
            or any(not isinstance(pattern, str) or not pattern.strip() for pattern in required_patterns)
        ):
            raise ValueError(
                f"policy entry {index} in {path} requires required_patterns to be a non-empty list of non-empty strings"
            )
        try:
            Policy(
                name="vendor",
                temperature=entry["temperature"],
                top_p=entry["top_p"],
                top_k=entry["top_k"],
                min_p=entry["min_p"],
                thinking=entry["thinking"],
                budgets={**THINKING_BUDGETS, **(entry.get("budgets") or {})},
                extra=entry["extra"],
                source=f"validation:{entry['family']}",
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid policy entry {index} in {path}: {exc}") from exc
    return document["policies"], str(document.get("reviewed_date") or "unreviewed")


def resolve_policy(
    name: str,
    model: str,
    *,
    budget_overrides: dict[str, int] | None = None,
    seed: int | None = None,
    policy_file: Path | None = None,
) -> Policy:
    if name == "strict":
        return strict_policy(budget_overrides, seed=seed)
    if name != "vendor":
        raise ValueError(f"unknown policy {name!r}")

    entries, _ = _load_policy_entries(policy_file)
    model_key = model.casefold()
    for entry in entries:
        patterns = entry.get("patterns") or []
        exclude_patterns = entry.get("exclude_patterns") or []
        required_patterns = entry.get("required_patterns") or []
        if not entry.get("verified") or not any(str(pattern).casefold() in model_key for pattern in patterns):
            continue
        if required_patterns and not any(str(pattern).casefold() in model_key for pattern in required_patterns):
            continue
        if any(str(pattern).casefold() in model_key for pattern in exclude_patterns):
            continue
        source_url = entry.get("source_url")
        if not source_url:
            continue
        required = ("family", "temperature", "top_p", "top_k", "thinking")
        if any(key not in entry for key in required):
            continue
        source = (
            f"vendor:{entry['family']}|source={source_url}|reviewed={entry['reviewed_date']}"
        )
        base_budgets = THINKING_BUDGETS if entry["thinking"] else STRICT_BUDGETS
        return Policy(
            name="vendor",
            temperature=entry["temperature"],
            top_p=entry["top_p"],
            top_k=entry["top_k"],
            min_p=entry["min_p"],
            thinking=entry["thinking"],
            budgets={
                **base_budgets,
                **(entry.get("budgets") or {}),
                **(budget_overrides or {}),
            },
            extra=_with_seed(entry.get("extra") or {}, seed, default=VENDOR_DEFAULT_SEED),
            source=source,
        )

    warnings.warn(
        f"unknown model {model!r} or unverified vendor mapping; falling back to strict",
        RuntimeWarning,
        stacklevel=2,
    )
    return strict_policy(
        budget_overrides,
        seed=seed,
        source="unknown-model-fallback",
    )


_INLINE_THINK = re.compile(r"<think>(.*?)</think>", re.IGNORECASE | re.DOTALL)
_POLICY_PROBE_PROMPT = (
    "What is 17 multiplied by 23? Work it out internally as appropriate, "
    "then give the final integer."
)


def probe_policy(client: Any) -> dict[str, Any]:
    """Verify the server honors this client's thinking toggle before scoring."""
    expected_thinking = bool(client.policy.thinking)
    try:
        out = client.complete(_POLICY_PROBE_PROMPT, max_tokens=256)
    except Exception as exc:
        return {
            "status": "failed",
            "expected_thinking": expected_thinking,
            "reason": f"probe request failed: {exc}",
        }

    dedicated = str(out.get("reasoning_content") or "").strip()
    inline_matches = _INLINE_THINK.findall(str(out.get("text") or ""))
    inline = "\n".join(match.strip() for match in inline_matches if match.strip())
    reasoning_chars = len(dedicated)
    inline_chars = len(inline)
    visible_reasoning = reasoning_chars + inline_chars

    if expected_thinking and visible_reasoning == 0:
        status = "failed"
        reason = "thinking requested but no reasoning_content or inline <think> trace was returned"
    elif not expected_thinking and (reasoning_chars > 0 or inline_chars > 0):
        status = "failed"
        reason = "thinking disabled but the server returned a reasoning trace"
    else:
        status = "ok"
        reason = "thinking toggle observed"

    usage = out.get("usage") or {}
    return {
        "status": status,
        "expected_thinking": expected_thinking,
        "reason": reason,
        "reasoning_chars": reasoning_chars,
        "inline_reasoning_chars": inline_chars,
        "finish": out.get("finish"),
        "completion_tokens": usage.get("completion_tokens"),
        "request_params": out.get("request_params"),
    }
