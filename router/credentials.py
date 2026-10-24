"""Current-user credential storage for Relay API keys.

Windows uses the existing user environment registry. macOS and Linux use a
per-user JSON file with owner-only permissions. Codex's ChatGPT sign-in remains
in Codex's own credential store.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile

NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class CredentialError(ValueError):
    """Raised when a relay credential cannot be read or written."""


def store_path() -> Path:
    override = os.environ.get("CODEX_ROUTER_CREDENTIALS")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Relay" / "credentials.json"
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "relay" / "credentials.json"


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise CredentialError("Invalid credential name")


def _read_file(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict):
        return {}
    return {key: value for key, value in document.items() if isinstance(key, str) and isinstance(value, str)}


def _read_registry(name: str) -> str | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value if isinstance(value, str) and value else None
    except OSError:
        return None


def get_secret(name: str, *, file: Path | None = None) -> str | None:
    """Read a credential without returning any other stored value."""
    _check_name(name)
    value = os.environ.get(name)
    if file is not None:
        return value or _read_file(file).get(name)
    if os.environ.get("CODEX_ROUTER_CREDENTIALS"):
        # Development and tests are explicitly isolated from ambient live credentials.
        return _read_file(store_path()).get(name)
    if os.name == "nt":
        # The current-user registry is shared by the manager and router processes.
        # Reading it first lets key rotation take effect without restarting either.
        return _read_registry(name) or value
    return value or _read_file(store_path()).get(name)


def set_secret(name: str, value: str, *, file: Path | None = None) -> None:
    """Atomically store one credential in the current user's protected store."""
    _check_name(name)
    if not isinstance(value, str) or not value.strip():
        raise CredentialError("Credential value must not be empty")
    clean = value.strip()
    if len(clean) > 4096:
        raise CredentialError("Credential value is too long")
    if file is None and os.name == "nt" and not os.environ.get("CODEX_ROUTER_CREDENTIALS"):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, clean)
        os.environ[name] = clean
        return

    path = file or store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
    document = _read_file(path)
    document[name] = clean
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
