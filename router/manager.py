"""Loopback-only management API for the subscription router GUI.

No endpoint returns a credential. API keys are accepted write-only and stored in
Windows' current-user environment; OAuth remains in Codex's or OpenCode's own store.
"""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import codex_config
import router
import settings

HERE = Path(__file__).resolve().parent
SETTINGS_PATH = Path(os.environ.get("CODEX_ROUTER_SETTINGS") or HERE / "router-settings.json")
MANAGER_PORT = int(os.environ.get("CODEX_ROUTER_MANAGER_PORT") or 18766)
DEFAULT_STATIC = HERE.parent / "app" / "dist" if (HERE.parent / "app" / "dist").is_dir() else HERE / "app"
STATIC_DIR = Path(os.environ.get("CODEX_ROUTER_STATIC") or DEFAULT_STATIC).resolve()
OPENCODE_AUTH_PATH = Path(os.environ.get("OPENCODE_AUTH_PATH") or Path.home() / ".local" / "share" / "opencode" / "auth.json")
PROVIDERS = {
    "openai": {"name": "OpenAI", "auth": "Existing Codex / ChatGPT sign-in", "docs": "https://developers.openai.com/codex/auth"},
    "opencode": {"name": "OpenCode Go", "auth": "Personal API key", "docs": "https://opencode.ai/auth"},
    "anthropic": {"name": "Claude Pro", "auth": "OpenCode Anthropic OAuth", "docs": "https://opencode.ai/docs/providers/#anthropic"},
    "kimi": {"name": "Kimi Code", "auth": "Kimi Code membership API key", "docs": "https://www.kimi.com/code/docs/en/third-party-tools/codex"},
}
REDACT = re.compile(r"(?i)(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|bearer)([\s\"':=]+)[^\s,\"}]+")
BEARER = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*")


def _user_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    if os.name != "nt":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value if isinstance(value, str) and value else None
    except OSError:
        return None


def _set_user_env(name: str, value: str) -> None:
    if os.name != "nt":
        raise RuntimeError("The graphical credential store currently supports Windows only")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    os.environ[name] = value
    # Ask Explorer and other well-behaved apps to refresh their environment. Existing
    # processes are not killed or restarted; the router also reads this store per request.
    try:
        import ctypes
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 1000, ctypes.byref(result))
    except Exception:
        pass


def provider_state() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for provider, metadata in PROVIDERS.items():
        item = dict(metadata)
        item["status"] = "not_configured"
        item["detail"] = "No local credential found"
        if provider in ("opencode", "kimi"):
            variable = "OPENCODE_API_KEY" if provider == "opencode" else "KIMI_API_KEY"
            # The development UI is isolated from the machine's live credential stores.
            if os.environ.get("CODEX_ROUTER_DEV") != "1" and _user_env(variable):
                item.update(status="credential_found", detail=f"{variable} found; value hidden")
        elif provider == "openai":
            if (Path(router.CODEX_HOME) / "auth.json").exists():
                item.update(status="credential_found", detail="Codex credential store found; account details hidden")
            else:
                item.update(status="unknown", detail="Check Codex's profile menu; keyring-only sign-in cannot be detected here")
        else:
            auth_path = OPENCODE_AUTH_PATH
            try:
                with auth_path.open(encoding="utf-8") as handle:
                    document = json.load(handle)
                token = document.get("anthropic") or {}
                if token.get("access") or token.get("refresh"):
                    expires = token.get("expires")
                    expired = isinstance(expires, (int, float)) and expires <= time.time() * 1000
                    item.update(status="credential_found", detail="OpenCode Anthropic OAuth found; tokens hidden" + (" (refresh may be required)" if expired else ""))
            except (OSError, ValueError):
                pass
        result[provider] = item
    return result


def router_health() -> dict[str, Any]:
    url = f"http://127.0.0.1:{router.PORT}/__router_health"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return {"reachable": True, **json.load(response)}
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"reachable": False, "detail": f"Not reachable on 127.0.0.1:{router.PORT}", "error_type": type(exc).__name__}


def available_models() -> list[dict[str, str]]:
    output = []
    for filename, provider in (("models_cache.json", "openai"), ("opencode-go-models.json", "opencode")):
        path = Path(router.CODEX_HOME) / filename
        try:
            with path.open(encoding="utf-8") as handle:
                models = json.load(handle).get("models") or []
            output.extend({"id": model["slug"], "provider": provider, "name": model.get("display_name") or model["slug"]}
                          for model in models if isinstance(model.get("slug"), str))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return output


def state() -> dict[str, Any]:
    document = settings.load(SETTINGS_PATH)
    catalog_path = Path(router.CODEX_HOME) / "mixed-models.json"
    try:
        with catalog_path.open(encoding="utf-8") as handle:
            catalog = json.load(handle).get("models") or []
    except (OSError, ValueError):
        catalog = []
    return {
        "settings": document,
        "providers": provider_state(),
        "router": router_health(),
        "catalog": [{"id": m.get("slug"), "name": m.get("display_name")} for m in catalog],
        "available_models": available_models(),
        "settings_location": str(SETTINGS_PATH),
        "catalog_location": str(catalog_path),
        "live_apply": os.environ.get("CODEX_ROUTER_DEV") != "1",
    }


def redacted_log() -> list[str]:
    path = HERE / "router.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]
    except OSError:
        return []
    return [REDACT.sub(lambda match: match.group(1) + match.group(2) + "[hidden]", BEARER.sub("Bearer [hidden]", line)) for line in lines]


def launch_login(provider: str) -> dict[str, Any]:
    if provider == "openai":
        executable = shutil.which("codex")
        arguments = [executable, "login"] if executable else None
        instruction = "Complete ChatGPT sign-in in the Codex window. This does not restart Codex."
    elif provider == "anthropic":
        executable = shutil.which("opencode")
        arguments = [executable, "auth", "login"] if executable else None
        instruction = "Choose Anthropic, then Claude Pro/Max in OpenCode. Your separate Claude Code configuration is not changed."
    else:
        raise ValueError("This provider uses an API key, not interactive sign-in")
    if not arguments:
        return {"launched": False, "message": "Provider CLI was not found on PATH. Open the provider's normal app or terminal sign-in instead."}
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
    subprocess.Popen(arguments, creationflags=flags, close_fds=True)
    return {"launched": True, "message": instruction}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _headers(self, status: int, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def reply(self, status: int, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode()
        self._headers(status, len(payload))
        self.wfile.write(payload)

    def body(self) -> dict[str, Any]:
        if self.headers.get("X-Router-Manager") != "1":
            raise ValueError("Missing local manager request header")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise ValueError("Request is too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    def serve_static(self):
        relative = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/") or "index.html"
        try:
            source = (STATIC_DIR / relative).resolve()
            source.relative_to(STATIC_DIR)
        except ValueError:
            self.reply(403, {"error": "Invalid static path"})
            return
        if not source.is_file():
            self.reply(404, {"error": "Interface not built. Run npm run build in app, or use npm run dev."})
            return
        payload = source.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(source.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        try:
            if self.path == "/api/state":
                self.reply(200, state())
            elif self.path == "/api/diagnostics":
                self.reply(200, {"router": router_health(), "log": redacted_log()})
            elif self.path.startswith("/api/"):
                self.reply(404, {"error": "Not found"})
            else:
                self.serve_static()
        except Exception as exc:
            self.reply(500, {"error": str(exc)})

    def do_POST(self):
        try:
            body = self.body()
            if self.path == "/api/settings":
                clean = settings.save(SETTINGS_PATH, body.get("settings"))
                self.reply(200, {"ok": True, "settings": clean})
            elif self.path == "/api/preview":
                clean = settings.validate(body.get("settings"))
                with tempfile.TemporaryDirectory(prefix="router-preview-") as directory:
                    output = Path(directory) / "catalog.json"
                    models = router.build_catalog(clean, str(output))
                    with output.open(encoding="utf-8") as handle:
                        catalog = json.load(handle)["models"]
                self.reply(200, {"ok": True, "models": models, "included": catalog})
            elif self.path == "/api/apply":
                clean = settings.validate(body.get("settings"))
                # Build once in a temporary location before replacing any preferences.
                with tempfile.TemporaryDirectory(prefix="router-apply-") as directory:
                    router.build_catalog(clean, str(Path(directory) / "catalog.json"))
                clean = settings.save(SETTINGS_PATH, clean)
                models = router.build_catalog(clean)
                development = os.environ.get("CODEX_ROUTER_DEV") == "1"
                reloaded, default_updated = False, False
                message = "Catalog written. Start the updated router when convenient; Codex was not restarted."
                if not development:
                    config_path = Path(router.CODEX_HOME) / "config.toml"
                    if config_path.is_file():
                        selected = next(model for model in clean["models"] if model["id"] == clean["runtime"]["default_model"])
                        try:
                            codex_config.set_default_model(config_path, selected["id"], selected["reasoning"]["default"])
                            default_updated = True
                        except (OSError, ValueError) as exc:
                            message = f"Catalog saved, but the Codex default was not updated: {exc}"
                    try:
                        request = urllib.request.Request(f"http://127.0.0.1:{router.PORT}/__router_reload", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(request, timeout=4) as response:
                            result = json.load(response)
                        reloaded = bool(result.get("ok"))
                        if reloaded and default_updated:
                            message = "Router and Codex default updated without restarting Codex. Picker changes may appear in new chats."
                    except (OSError, ValueError, urllib.error.URLError):
                        pass
                self.reply(200, {"ok": True, "models": models, "router_reloaded": reloaded, "codex_default_updated": default_updated, "message": message})
            elif self.path == "/api/credential":
                provider = body.get("provider")
                expected = {"opencode": "OPENCODE_API_KEY", "kimi": "KIMI_API_KEY"}.get(str(provider))
                value = body.get("key")
                if not expected or not isinstance(value, str) or not 8 <= len(value.strip()) <= 4096:
                    raise ValueError("Choose Kimi or OpenCode and enter a valid API key")
                _set_user_env(expected, value.strip())
                self.reply(200, {"ok": True, "message": f"{expected} saved in the current-user environment. The value was not retained by the GUI."})
            elif self.path == "/api/login":
                self.reply(200, launch_login(str(body.get("provider"))))
            elif self.path == "/api/open-docs":
                provider = str(body.get("provider"))
                if provider not in PROVIDERS:
                    raise ValueError("Unknown provider")
                webbrowser.open(PROVIDERS[provider]["docs"])
                self.reply(200, {"ok": True})
            else:
                self.reply(404, {"error": "Not found"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            self.reply(500, {"error": str(exc)})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", MANAGER_PORT), Handler)
    address = f"http://127.0.0.1:{MANAGER_PORT}"
    print(f"Router manager listening on {address}", flush=True)
    if "--open" in sys.argv:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
