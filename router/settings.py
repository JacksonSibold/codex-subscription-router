"""Validated, credential-free preferences for the Codex subscription router."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
PROVIDERS = ("openai", "opencode", "anthropic", "kimi", "local")
LOCAL_PROTOCOLS = ("openai_chat", "openai_responses")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
UPSTREAM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
CREDENTIAL_ENV = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
SECRET_NAME = re.compile(r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret)", re.I)
SECRET_VALUE = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|gho_[A-Za-z0-9]{20,}|Bearer\s+\S+)", re.I)
LEGACY_CLAUDE_NAMES = {
    "Claude Sonnet 5.5 — Claude Pro": "Claude Sonnet 5.5 — Claude",
    "Claude Opus 5.5 — Claude Pro": "Claude Opus 5.5 — Claude",
}


def _model(model_id: str, provider: str, name: str, default: str, efforts: list[str]) -> dict[str, Any]:
    return {
        "id": model_id,
        "upstream_id": model_id,
        "provider": provider,
        "display_name": name,
        "visible": True,
        "reasoning": {"default": default, "supported": efforts},
        "tools": {
            "shell": True,
            "computer_use": True,
            "web_search": provider == "openai",
            "connected_apps": provider == "openai",
        },
        "subagents": True,
    }


def default_settings() -> dict[str, Any]:
    """The original eleven-model picker, represented as editable preferences."""
    models = [
        _model("gpt-6.1-sol", "openai", "GPT-6.1 Sol — OpenAI", "medium", ["low", "medium", "high", "xhigh"]),
        _model("gpt-6-luna", "openai", "GPT-6 Luna — OpenAI", "medium", ["low", "medium", "high", "xhigh"]),
        _model("grok-4.7", "opencode", "Grok 4.7 — OpenCode Go", "medium", ["low", "medium", "high", "xhigh"]),
        _model("muse-spark-1.3-contributor", "opencode", "Muse Spark 1.3 Contributor — OpenCode Go", "medium", ["minimal", "low", "medium", "high", "xhigh"]),
        _model("deepseek-v4.1-flash", "opencode", "DeepSeek V4.1 Flash — OpenCode Go", "high", ["low", "high", "max"]),
        _model("beam-free", "opencode", "Beam Free — OpenCode Go", "medium", ["low", "medium", "high", "xhigh", "max"]),
        _model("glm-5.3-flash", "opencode", "GLM-5.3 Flash — OpenCode Go", "high", ["low", "high", "max"]),
        _model("kimi-k3.1-pro", "opencode", "Kimi K3.1 Pro — OpenCode Go", "max", ["low", "high", "max"]),
        _model("claude-sonnet-5-5", "anthropic", "Claude Sonnet 5.5 — Claude", "medium", list(EFFORTS[1:])),
        _model("claude-opus-5-5", "anthropic", "Claude Opus 5.5 — Claude", "medium", list(EFFORTS[1:])),
        _model("k3.1-pro", "kimi", "Kimi K3.1 Pro — Kimi Membership", "max", ["low", "high", "max"]),
    ]
    return {
        "version": SCHEMA_VERSION,
        "runtime": {"host": "127.0.0.1", "port": 18765, "default_model": "deepseek-v4.1-flash"},
        "providers": {
            "openai": {"enabled": True, "auth_method": "codex", "credential_env": None},
            "opencode": {"enabled": True, "auth_method": "api_key", "credential_env": "OPENCODE_API_KEY"},
            "anthropic": {"enabled": True, "auth_method": "relay_oauth", "credential_env": None},
            "kimi": {"enabled": True, "auth_method": "api_key", "credential_env": "KIMI_API_KEY"},
            "local": {"enabled": True, "auth_method": "none", "credential_env": None},
        },
        "models": models,
    }


def _upgrade_v1(document: Any) -> dict[str, Any]:
    """Add Relay-owned OAuth and the local-provider lane without losing preferences."""
    if not isinstance(document, dict) or document.get("version") != 1:
        return document
    upgraded = copy.deepcopy(document)
    upgraded["version"] = SCHEMA_VERSION
    providers = upgraded.setdefault("providers", {})
    if isinstance(providers, dict):
        providers.setdefault("local", {"enabled": True, "auth_method": "none", "credential_env": None})
        anthropic = providers.get("anthropic")
        if isinstance(anthropic, dict) and anthropic.get("auth_method") == "opencode_oauth":
            anthropic["auth_method"] = "relay_oauth"
    for model in upgraded.get("models", []):
        if isinstance(model, dict) and isinstance(model.get("id"), str):
            model.setdefault("upstream_id", model["id"])
    return upgraded


def normalize_local_endpoint(value: Any) -> str:
    """Return a loopback-only base URL for an OpenAI-compatible local server."""
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        _fail("model.local.endpoint", "expected an HTTP loopback URL")
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        _fail("model.local.endpoint", "invalid URL")
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        _fail("model.local.endpoint", "expected an http:// or https:// loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        _fail("model.local.endpoint", "credentials, query strings, and fragments are not allowed")
    try:
        loopback = parsed.hostname.lower() == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        _fail("model.local.endpoint", "only localhost or loopback IP addresses are allowed")
    try:
        port = parsed.port
    except ValueError:
        _fail("model.local.endpoint", "invalid port")
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    path = parsed.path.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if path.endswith(suffix):
            path = path[:-len(suffix)].rstrip("/")
            break
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _secret_scan(value: Any, path: str = "settings") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_NAME.search(str(key)) and child not in (None, "", "OPENCODE_API_KEY", "KIMI_API_KEY"):
                _fail(f"{path}.{key}", "credentials must be stored in the provider credential store, not settings")
            _secret_scan(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _secret_scan(child, f"{path}[{index}]")
    elif isinstance(value, str) and SECRET_VALUE.search(value):
        _fail(path, "possible credential value; settings must remain shareable")


def validate(document: Any) -> dict[str, Any]:
    document = _upgrade_v1(document)
    if not isinstance(document, dict):
        raise ValueError("settings: expected a JSON object")
    if document.get("version") != SCHEMA_VERSION:
        _fail("version", f"expected {SCHEMA_VERSION}")
    document = copy.deepcopy(document)
    for model in document.get("models", []):
        if isinstance(model, dict) and isinstance(model.get("id"), str):
            model.setdefault("upstream_id", model["id"])
    runtime = document.get("runtime")
    providers = document.get("providers")
    models = document.get("models")
    if not isinstance(runtime, dict) or not isinstance(providers, dict) or not isinstance(models, list):
        raise ValueError("settings: runtime, providers, and models are required")
    if runtime.get("host") != "127.0.0.1":
        _fail("runtime.host", "only loopback binding is allowed")
    port = runtime.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        _fail("runtime.port", "expected an integer from 1024 through 65535")
    for provider in PROVIDERS:
        config = providers.get(provider)
        if not isinstance(config, dict) or not isinstance(config.get("enabled"), bool):
            _fail(f"providers.{provider}", "expected an object with a boolean enabled field")
    seen: set[str] = set()
    visible: list[str] = []
    for index, model in enumerate(models):
        path = f"models[{index}]"
        if not isinstance(model, dict):
            _fail(path, "expected an object")
        model_id, provider = model.get("id"), model.get("provider")
        if not isinstance(model_id, str) or not MODEL_ID.fullmatch(model_id):
            _fail(path + ".id", "use 1-128 letters, numbers, dots, slashes, colons, underscores, or hyphens")
        if model_id in seen:
            _fail(path + ".id", "model IDs must be unique across providers")
        seen.add(model_id)
        upstream_id = model.get("upstream_id")
        if not isinstance(upstream_id, str) or not UPSTREAM_ID.fullmatch(upstream_id):
            _fail(path + ".upstream_id", "use 1-200 letters, numbers, dots, slashes, colons, underscores, or hyphens")
        if provider not in PROVIDERS:
            _fail(path + ".provider", "unknown provider")
        if provider == "local":
            local = model.get("local")
            if not isinstance(local, dict):
                _fail(path + ".local", "local models require endpoint and protocol")
            if local.get("protocol") not in LOCAL_PROTOCOLS:
                _fail(path + ".local.protocol", "expected openai_chat or openai_responses")
            normalize_local_endpoint(local.get("endpoint"))
            credential_env = local.get("credential_env")
            if credential_env is not None and (not isinstance(credential_env, str) or not CREDENTIAL_ENV.fullmatch(credential_env)):
                _fail(path + ".local.credential_env", "expected an uppercase credential variable name or null")
        name = model.get("display_name")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            _fail(path + ".display_name", "expected 1-120 non-whitespace characters")
        if provider == "anthropic" and name in LEGACY_CLAUDE_NAMES:
            name = LEGACY_CLAUDE_NAMES[name]
            model["display_name"] = name
        if not isinstance(model.get("visible"), bool) or not isinstance(model.get("subagents"), bool):
            _fail(path, "visible and subagents must be booleans")
        reasoning = model.get("reasoning")
        if not isinstance(reasoning, dict) or not isinstance(reasoning.get("supported"), list):
            _fail(path + ".reasoning", "expected default and supported levels")
        efforts = reasoning["supported"]
        if len(efforts) != len(set(efforts)) or any(effort not in EFFORTS for effort in efforts):
            _fail(path + ".reasoning.supported", "unknown or duplicate reasoning level")
        default = reasoning.get("default")
        if efforts and default not in efforts:
            _fail(path + ".reasoning.default", "default must be one of the supported levels")
        if not efforts and default is not None:
            _fail(path + ".reasoning.default", "use null when reasoning is unsupported")
        tools = model.get("tools")
        if not isinstance(tools, dict):
            _fail(path + ".tools", "expected an object")
        for tool in ("shell", "computer_use", "web_search", "connected_apps"):
            if not isinstance(tools.get(tool), bool):
                _fail(f"{path}.tools.{tool}", "expected a boolean")
        if provider != "openai" and (tools["web_search"] or tools["connected_apps"]):
            _fail(path + ".tools", "hosted web search and connected apps are currently OpenAI-only")
        if model["visible"]:
            visible.append(model_id)
    if not visible:
        _fail("models", "at least one model must be visible")
    default_model = runtime.get("default_model")
    if default_model not in seen:
        _fail("runtime.default_model", "model does not exist")
    selected = next(model for model in models if model["id"] == default_model)
    if not selected["visible"] or not providers[selected["provider"]]["enabled"]:
        _fail("runtime.default_model", "default model must be visible and use an enabled provider")
    _secret_scan(document)
    clean = document
    for model in clean["models"]:
        if model["provider"] == "local":
            model["local"]["endpoint"] = normalize_local_endpoint(model["local"]["endpoint"])
    return clean


def load(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return default_settings()
    with source.open(encoding="utf-8") as handle:
        return validate(json.load(handle))


def save(path: str | os.PathLike[str], document: Any, backups: int = 8) -> dict[str, Any]:
    """Validate and atomically replace settings, retaining timestamped local backups."""
    clean = validate(document)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = target.with_name(target.name + ".backup-" + stamp)
        backup.write_bytes(target.read_bytes())
        for old in sorted(target.parent.glob(target.name + ".backup-*"), reverse=True)[backups:]:
            old.unlink(missing_ok=True)
    payload = json.dumps(clean, ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return clean


def model_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {model["id"]: model for model in document["models"] if document["providers"][model["provider"]]["enabled"]}
