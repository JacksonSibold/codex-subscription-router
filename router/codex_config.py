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
    tomllib.loads(result)
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
