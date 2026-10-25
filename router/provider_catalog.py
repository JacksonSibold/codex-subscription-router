"""Load live provider model catalogs without exposing provider credentials."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any
import urllib.error
import urllib.request

import anthropic_adapter
import credentials

CACHE_SECONDS = 5 * 60
OPENCODE_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "opencode" / "models.json"
FALLBACKS = {
    "openai": [
        {"id": "gpt-6.1-sol", "name": "GPT-6.1 Sol"},
        {"id": "gpt-6-luna", "name": "GPT-6 Luna"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"},
        {"id": "claude-opus-5-5", "name": "Claude Opus 5.5"},
    ],
    "kimi": [
        {"id": "k3.1-pro", "name": "Kimi K3.1 Pro"},
    ],
    "opencode": [],
}
_CACHE: dict[str, Any] | None = None
_CACHE_TIME = 0.0
_LOCK = threading.Lock()
_SECRET_ERROR = re.compile(r"(?i)(bearer\s+|access[_-]?token[=: ]+|refresh[_-]?token[=: ]+|api[_-]?key[=: ]+)[^\s,;\"']+")


def _safe_error(exc: Exception) -> str:
    """Keep catalog errors useful without echoing provider credential material."""
    message = str(exc).replace("\n", " ").strip()[:240]
    message = _SECRET_ERROR.sub(lambda match: match.group(1) + "[hidden]", message)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        model_id = row.get("id")
        if not isinstance(model_id, str):
            continue
        model_id = model_id.strip()[:240]
        if not model_id or model_id in seen:
            continue
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            name = model_id.replace("-", " ").replace("_", " ").title()
        output.append({"id": model_id, "name": name.strip()[:160]})
        seen.add(model_id)
    return output


def _json_models(raw: str) -> list[dict[str, str]]:
    try:
        document = json.loads(raw)
    except ValueError:
        return []
    rows = document.get("models") if isinstance(document, dict) else document
    if not isinstance(rows, list):
        return []
    return _clean_rows([
        {"id": row.get("slug") or row.get("id"), "name": row.get("display_name") or row.get("name")}
        for row in rows if isinstance(row, dict)
    ])


def _local_json_models(path: Path, *, slug: bool = False) -> list[dict[str, str]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = document.get("models") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        return []
    key = "slug" if slug else "id"
    return _clean_rows([
        {"id": row.get(key) or row.get("slug"), "name": row.get("display_name") or row.get("name")}
        for row in rows if isinstance(row, dict)
    ])


def _command_output(arguments: list[str], timeout: int = 12) -> str:
    executable = shutil.which(arguments[0])
    if not executable:
        raise RuntimeError(f"{arguments[0]} is not installed")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    result = subprocess.run(
        [executable, *arguments[1:]], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, creationflags=flags,
    )
    if result.returncode:
        raise RuntimeError(f"{arguments[0]} catalog command exited with code {result.returncode}")
    return result.stdout


def _openai_models(codex_home: Path, force: bool) -> tuple[list[dict[str, str]], str]:
    rows = _local_json_models(codex_home / "models_cache.json", slug=True)
    if force or not rows:
        try:
            rows = _json_models(_command_output(["codex", "debug", "models", "--bundled"])) + rows
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
    return _clean_rows(rows), "Codex model catalog"


def _anthropic_models() -> tuple[list[dict[str, str]], str]:
    token = anthropic_adapter.access_token(lambda _message: None)
    request = urllib.request.Request(
        os.environ.get("RELAY_ANTHROPIC_MODELS_URL") or "https://api.anthropic.com/v1/models?limit=1000",
        headers=anthropic_adapter._headers(token, "relay-provider-catalog"),
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        document = json.load(response)
    rows = document.get("data") if isinstance(document, dict) else None
    return _clean_rows([
        {"id": row.get("id"), "name": row.get("display_name") or row.get("name")}
        for row in rows if isinstance(row, dict)
    ] if isinstance(rows, list) else []), "Anthropic account catalog"


def _kimi_models() -> tuple[list[dict[str, str]], str]:
    token = credentials.get_secret("KIMI_API_KEY")
    if not token:
        raise RuntimeError("Kimi API key is not connected")
    base = (os.environ.get("KIMI_CODE_BASE_URL") or "https://api.kimi.ai/coding/v1").rstrip("/")
    request = urllib.request.Request(
        f"{base}/models", method="GET",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "Relay provider-catalog"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        document = json.load(response)
    rows = document.get("data") if isinstance(document, dict) else None
    return _clean_rows([
        {"id": row.get("id"), "name": row.get("name") or row.get("display_name")}
        for row in rows if isinstance(row, dict)
    ] if isinstance(rows, list) else []), "Kimi account catalog"


def parse_opencode_cache(path: Path = OPENCODE_CACHE) -> list[dict[str, str]]:
    """Return active OpenCode models and skip provider-marked deprecated entries."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    provider = document.get("opencode") if isinstance(document, dict) else None
    models = provider.get("models") if isinstance(provider, dict) else None
    if not isinstance(models, dict):
        return []
    rows = []
    for model_id, model in models.items():
        if not isinstance(model, dict) or model.get("status") == "deprecated":
            continue
        declared_id = model.get("id")
        rows.append({"id": declared_id if isinstance(declared_id, str) and declared_id else model_id,
                     "name": model.get("name")})
    return _clean_rows(rows)


def _opencode_models(codex_home: Path, force: bool) -> tuple[list[dict[str, str]], str]:
    if force:
        try:
            _command_output(["opencode", "models", "opencode", "--refresh"], timeout=30)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
    rows = parse_opencode_cache()
    if rows:
        return rows, "OpenCode active catalog"
    fallback = _local_json_models(codex_home / "opencode-go-models.json", slug=True)
    if fallback:
        return fallback, "OpenCode Relay fallback catalog"
    try:
        output = _command_output(["opencode", "models", "opencode"], timeout=20)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(str(exc)) from None
    parsed = []
    for line in output.splitlines():
        if line.startswith("opencode/") and "/" not in line[9:]:
            model_id = line.partition("/")[2]
            parsed.append({"id": model_id, "name": None})
    return _clean_rows(parsed), "OpenCode active catalog"


def collect(codex_home: Path, force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_TIME
    now = time.time()
    with _LOCK:
        if not force and _CACHE is not None and now - _CACHE_TIME < CACHE_SECONDS:
            return copy.deepcopy(_CACHE)
        previous = (_CACHE or {}).get("providers", {})
        providers: dict[str, Any] = {}
        fetchers = {
            "openai": lambda: _openai_models(codex_home, force),
            "anthropic": _anthropic_models,
            "kimi": _kimi_models,
            "opencode": lambda: _opencode_models(codex_home, force),
        }
        for provider, fetcher in fetchers.items():
            try:
                rows, source = fetcher()
                error = None
            except Exception as exc:
                rows, source = [], ""
                error = _safe_error(exc)
                old = previous.get(provider, {})
                rows = old.get("models") if isinstance(old.get("models"), list) else []
                source = str(old.get("source") or "")
            if not rows:
                rows = FALLBACKS.get(provider, [])
                source = source or "Relay built-in fallback"
            providers[provider] = {
                "models": _clean_rows(rows),
                "count": len(_clean_rows(rows)),
                "source": source,
                "error": error,
                "stale": bool(error and rows),
            }
        _CACHE = {
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "providers": providers,
            "total": sum(item["count"] for item in providers.values()),
        }
        _CACHE_TIME = now
        return copy.deepcopy(_CACHE)


def cached_snapshot() -> dict[str, Any] | None:
    with _LOCK:
        return copy.deepcopy(_CACHE) if _CACHE is not None else None
