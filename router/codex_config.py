"""Small, preservation-focused updates to Codex's top-level model selection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime, timezone
import tomllib


def _set_key(header: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
    line = f"{key} = {value}"
    if pattern.search(header):
        return pattern.sub(lambda _match: line, header, count=1)
    return header.rstrip() + ("\n" if header.strip() else "") + line + "\n"


def _remove_key(header: str, key: str) -> str:
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*(?:\r?\n)?")
    return pattern.sub("", header, count=1)


def _set_table(document: str, table: str, values: dict[str, str]) -> str:
    """Merge selected keys into one TOML table without touching neighboring tables."""
    pattern = re.compile(rf"(?ms)^\[{re.escape(table)}\]\s*\n.*?(?=^\[|\Z)")
    match = pattern.search(document)
    body = f"[{table}]\n"
    if match:
        body = match.group(0)
    for key, value in values.items():
        body = _set_key(body, key, value)
    if match:
        return document[:match.start()] + body.rstrip() + "\n\n" + document[match.end():]
    return document.rstrip() + "\n\n" + body


def _write_with_backup(path: Path, original: str, result: str) -> None:
    tomllib.loads(result)
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        shutil.copy2(path, path.with_name(path.name + ".backup-" + stamp))
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(result)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure_relay(path: Path, catalog_path: Path, model: str, effort: str | None, base_url: str = "http://127.0.0.1:18765") -> None:
    """Point Codex at Relay while preserving every unrelated configuration section."""
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    if original:
        tomllib.loads(original)
    split = re.search(r"(?m)^\[", original)
    header = original[:split.start()] if split else original
    rest = original[split.start():] if split else ""
    for key, value in {
        "model": json.dumps(model),
        "model_provider": json.dumps("mixed"),
        "model_catalog_json": json.dumps(str(catalog_path)),
    }.items():
        header = _set_key(header, key, value)
    if effort:
        header = _set_key(header, "model_reasoning_effort", json.dumps(effort))
    else:
        header = _remove_key(header, "model_reasoning_effort")
    result = header.rstrip() + "\n\n" + rest.lstrip("\n")
    result = _set_table(result, "model_providers.mixed", {
        "name": json.dumps("Relay — OpenAI + Claude + Kimi + OpenCode + Local"),
        "base_url": json.dumps(base_url),
        "wire_api": json.dumps("responses"),
        "requires_openai_auth": "true",
        "supports_websockets": "false",
    })
    result = _set_table(result, "desktop", {
        "enabled-reasoning-efforts": json.dumps(["minimal", "low", "medium", "high", "xhigh", "max"]),
    })
    result = _set_table(result, "agents", {"enabled": "true"})
    _write_with_backup(path, original, result)


def set_default_model(path: Path, model: str, effort: str | None) -> None:
    """Change no provider, project, plugin, or credential settings."""
    original = path.read_text(encoding="utf-8")
    tomllib.loads(original)
    split = re.search(r"(?m)^\[", original)
    header = original[:split.start()] if split else original
    rest = original[split.start():] if split else ""
    header = _set_key(header, "model", json.dumps(model))
    if effort:
        header = _set_key(header, "model_reasoning_effort", json.dumps(effort))
    else:
        header = _remove_key(header, "model_reasoning_effort")
    result = header.rstrip() + "\n\n" + rest.lstrip("\n")
    _write_with_backup(path, original, result)
