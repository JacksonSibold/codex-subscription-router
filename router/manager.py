"""Loopback-only management API for the subscription router GUI.

No endpoint returns a credential. API keys and Relay's Claude OAuth token set use
the current-user credential store; Codex's ChatGPT sign-in remains in Codex.
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
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import anthropic_oauth
import codex_config
import credentials
import local_adapter
import router
import settings
import subscription_usage
import usage_store
import version

HERE = Path(__file__).resolve().parent
SETTINGS_PATH = Path(os.environ.get("CODEX_ROUTER_SETTINGS") or HERE / "router-settings.json")
MANAGER_PORT = int(os.environ.get("CODEX_ROUTER_MANAGER_PORT") or 18766)
DEFAULT_STATIC = HERE.parent / "app" / "dist" if (HERE.parent / "app" / "dist").is_dir() else HERE / "app"
STATIC_DIR = Path(os.environ.get("CODEX_ROUTER_STATIC") or DEFAULT_STATIC).resolve()
OPENCODE_AUTH_PATH = Path(os.environ.get("OPENCODE_AUTH_PATH") or Path.home() / ".local" / "share" / "opencode" / "auth.json")
PROVIDERS = {
    "openai": {"name": "OpenAI", "auth": "Existing Codex / ChatGPT sign-in", "docs": "https://developers.openai.com/codex/auth"},
    "opencode": {"name": "OpenCode Go", "auth": "Personal API key", "docs": "https://opencode.ai/auth"},
    "anthropic": {"name": "Claude", "auth": "Relay-owned OAuth for eligible Claude plans", "docs": "https://docs.anthropic.com/en/docs/claude-code/overview"},
    "kimi": {"name": "Kimi Code", "auth": "Kimi Code membership API key", "docs": "https://www.kimi.com/code/docs/en/third-party-tools/codex"},
    "local": {"name": "Local models", "auth": "Loopback OpenAI-compatible endpoint", "docs": "https://platform.openai.com/docs/api-reference/chat"},
}
OAUTH_FLOWS: dict[str, anthropic_oauth.PendingFlow] = {}
OAUTH_LOCK = threading.Lock()
REDACT = re.compile(r"(?i)(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|bearer)([\s\"':=]+)[^\s,\"}]+")
BEARER = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*")


def _user_env(name: str) -> str | None:
    return credentials.get_secret(name)


def _set_user_env(name: str, value: str) -> None:
    credentials.set_secret(name, value)
    if os.name != "nt":
        return
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
    development = os.environ.get("CODEX_ROUTER_DEV") == "1"
    for provider, metadata in PROVIDERS.items():
        item = dict(metadata)
        item["status"] = "not_configured"
        item["detail"] = "No local credential found"
        if provider in ("opencode", "kimi"):
            variable = "OPENCODE_API_KEY" if provider == "opencode" else "KIMI_API_KEY"
            # The development UI reads only its explicit isolated file, never the live registry.
            if (not development or os.environ.get("CODEX_ROUTER_CREDENTIALS")) and _user_env(variable):
                item.update(status="credential_found", detail=f"{variable} found; value hidden")
        elif provider == "openai":
            if (Path(router.CODEX_HOME) / "auth.json").exists():
                item.update(status="credential_found", detail="Codex credential store found; account details hidden")
            else:
                item.update(status="unknown", detail="Check Codex's profile menu; keyring-only sign-in cannot be detected here")
        elif provider == "local":
            try:
                document = settings.load(SETTINGS_PATH)
                endpoints = sorted({model["local"]["endpoint"] for model in document["models"] if model["provider"] == "local"})
            except (OSError, ValueError, KeyError):
                endpoints = []
            if endpoints:
                item.update(status="ready", detail=f"{len(endpoints)} loopback endpoint(s) configured; no cloud credential required")
            else:
                item.update(status="unknown", detail="Add a local endpoint such as Ollama or LM Studio")
        elif provider == "anthropic":
            relay_status = None
            if not development or os.environ.get("CODEX_ROUTER_CREDENTIALS"):
                relay_status = anthropic_oauth.credential_status()
            if relay_status:
                suffix = " (refresh required)" if relay_status.get("expired") else ""
                item.update(status="credential_found", detail="Claude Relay OAuth found; tokens hidden" + suffix)
                result[provider] = item
                continue
            # A pre-existing OpenCode login is supported only as a legacy fallback.
            if development and not os.environ.get("OPENCODE_AUTH_PATH"):
                item.update(detail="Development mode will not read the live OpenCode credential store")
                result[provider] = item
                continue
            auth_path = OPENCODE_AUTH_PATH
            try:
                with auth_path.open(encoding="utf-8") as handle:
                    document = json.load(handle)
                token = document.get("anthropic") or {}
                if token.get("access") or token.get("refresh"):
                    expires = token.get("expires")
                    expired = isinstance(expires, (int, float)) and expires <= time.time() * 1000
                    item.update(status="credential_found", detail="Legacy OpenCode Anthropic OAuth found; tokens hidden" + (" (refresh may be required)" if expired else ""))
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


BUILTIN_MODELS = (
    {"id": "gpt-6.1-sol", "provider": "openai", "name": "GPT-6.1 Sol"},
    {"id": "gpt-6-luna", "provider": "openai", "name": "GPT-6 Luna"},
    {"id": "claude-sonnet-5-5", "provider": "anthropic", "name": "Claude Sonnet 5.5"},
    {"id": "claude-opus-5-5", "provider": "anthropic", "name": "Claude Opus 5.5"},
    {"id": "k3.1-pro", "provider": "kimi", "name": "Kimi K3.1 Pro"},
)


def available_models() -> list[dict[str, str]]:
    """Return built-in, configured, and locally cached provider models for the add menu.

    The menu must remain useful before a provider cache exists and after a user
    edits an upstream ID. Configured routes and the shipped defaults therefore
    supplement the live Codex/OpenCode catalogs.
    """
    output = [dict(model) for model in BUILTIN_MODELS]
    for document in (settings.default_settings(),):
        output.extend({
            "id": model["upstream_id"],
            "provider": model["provider"],
            "name": model["display_name"],
        } for model in document["models"])
    try:
        configured = settings.load(SETTINGS_PATH)
    except (OSError, ValueError):
        configured = None
    if configured:
        output.extend({
            "id": model["upstream_id"],
            "provider": model["provider"],
            "name": model["display_name"],
        } for model in configured["models"] if model["provider"] != "local")
    for filename, provider in (("models_cache.json", "openai"), ("opencode-go-models.json", "opencode")):
        path = Path(router.CODEX_HOME) / filename
        try:
            with path.open(encoding="utf-8") as handle:
                models = json.load(handle).get("models") or []
            output.extend({"id": model["slug"], "provider": provider, "name": model.get("display_name") or model["slug"]}
                          for model in models if isinstance(model.get("slug"), str))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for model in output:
        key = (model["provider"], model["id"])
        if key not in seen:
            seen.add(key)
            unique.append(model)
    return unique


def usage_path() -> Path:
    return Path(os.environ.get("CODEX_ROUTER_USAGE_DB") or router.USAGE_PATH)


def usage_account_inventory(document: dict[str, Any] | None = None,
                           providers: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Describe every provider account and local endpoint, including zero-usage ones."""
    document = document or settings.load(SETTINGS_PATH)
    providers = providers or provider_state()
    inventory: list[dict[str, Any]] = []
    labels = {
        "openai": router.USAGE_ACCOUNT_LABELS["openai"],
        "opencode": router.USAGE_ACCOUNT_LABELS["opencode"],
        "anthropic": router.USAGE_ACCOUNT_LABELS["anthropic"],
        "kimi": router.USAGE_ACCOUNT_LABELS["kimi"],
    }
    for provider in PROVIDERS:
        state = providers.get(provider, {})
        status = str(state.get("status") or "unknown")
        if provider == "anthropic" and str(state.get("detail") or "").startswith("Legacy OpenCode"):
            account = router.USAGE_ACCOUNT_LABELS["anthropic_fallback"]
        elif provider == "local":
            routes = [model for model in document["models"] if model["provider"] == "local"]
            endpoints: dict[str, dict[str, Any]] = {}
            for model in routes:
                account = router.usage_account("local", model)
                endpoints.setdefault(account, model)
            if not endpoints:
                endpoints["Local endpoints"] = None
            for account, model in endpoints.items():
                inventory.append({
                    "provider": provider,
                    "account": account,
                    "status": status,
                    "detail": state.get("detail"),
                    "connected": bool(endpoints and model is not None and status == "ready"),
                    "provider_enabled": bool(document["providers"][provider]["enabled"]),
                    "historical": False,
                })
            continue
        else:
            account = labels[provider]
        inventory.append({
            "provider": provider,
            "account": account,
            "status": status,
            "detail": state.get("detail"),
            "connected": status == "credential_found",
            "provider_enabled": bool(document["providers"][provider]["enabled"]),
            "historical": False,
        })
    return inventory


def usage_dashboard(days: int, providers: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Merge configured account inventory with routed activity from the ledger."""
    result = usage_store.dashboard(usage_path(), days)
    document = settings.load(SETTINGS_PATH)
    inventory = usage_account_inventory(document, providers)
    activity = {(row["provider"], row["account"]): row for row in result.get("providers", [])}
    accounts: list[dict[str, Any]] = []
    order = {provider: index for index, provider in enumerate(PROVIDERS)}
    zero = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "last_used": None}
    for item in inventory:
        row = activity.pop((item["provider"], item["account"]), {})
        accounts.append({**zero, **item, **row, "connected": item["connected"], "historical": False})
    for row in activity.values():
        accounts.append({**row, "connected": False, "provider_enabled": False, "historical": True,
                         "status": "historical", "detail": "This account appears in earlier routed activity."})
    accounts.sort(key=lambda row: (
        not row.get("connected", False), row.get("historical", False), order.get(row.get("provider"), 99),
        str(row.get("account") or ""),
    ))
    result["accounts"] = accounts
    result["connected_accounts"] = sum(1 for row in accounts if row.get("connected"))
    return result


def start_claude_oauth() -> dict[str, Any]:
    flow, url = anthropic_oauth.start()
    now = time.time()
    with OAUTH_LOCK:
        for state, pending in list(OAUTH_FLOWS.items()):
            if pending.expired() or len(OAUTH_FLOWS) >= 8:
                OAUTH_FLOWS.pop(state, None)
        OAUTH_FLOWS[flow.state] = flow
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return {"auth_url": url, "expires_at": flow.expires_at, "message": "Finish sign-in in your browser, then paste the authorization code Claude shows here."}


def complete_claude_oauth(pasted: Any) -> dict[str, Any]:
    if not isinstance(pasted, str) or not pasted.strip():
        raise ValueError("Paste the authorization code copied from Claude")
    state = pasted.partition("#")[2].strip()
    with OAUTH_LOCK:
        for key, pending in list(OAUTH_FLOWS.items()):
            if pending.expired():
                OAUTH_FLOWS.pop(key, None)
        if state:
            flow = OAUTH_FLOWS.get(state)
        else:
            flow = next(iter(OAUTH_FLOWS.values())) if len(OAUTH_FLOWS) == 1 else None
    if flow is None:
        raise ValueError("No matching Claude sign-in was found. Start the sign-in again.")
    result = anthropic_oauth.complete(flow, pasted)
    with OAUTH_LOCK:
        OAUTH_FLOWS.pop(flow.state, None)
    return result


def discover_local(endpoint: Any) -> list[dict[str, str]]:
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("Enter a loopback endpoint such as http://127.0.0.1:11434/v1")
    return local_adapter.discover(endpoint.strip())


def state() -> dict[str, Any]:
    document = settings.load(SETTINGS_PATH)
    providers = provider_state()
    catalog_path = Path(router.CODEX_HOME) / "mixed-models.json"
    try:
        with catalog_path.open(encoding="utf-8") as handle:
            catalog = json.load(handle).get("models") or []
    except (OSError, ValueError):
        catalog = []
    return {
        "version": version.__version__,
        "settings": document,
        "providers": providers,
        "router": router_health(),
        "catalog": [{"id": m.get("slug"), "name": m.get("display_name")} for m in catalog],
        "available_models": available_models(),
        "settings_location": str(SETTINGS_PATH),
        "catalog_location": str(catalog_path),
        "usage_location": str(usage_path()),
        "usage": usage_dashboard(30, providers),
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
        raise ValueError("Use Relay's Claude sign-in flow; OpenCode is not required")
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
        static_root = STATIC_DIR.resolve()
        try:
            source = (static_root / relative).resolve()
            source.relative_to(static_root)
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
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/state":
                self.reply(200, state())
            elif parsed.path == "/api/usage":
                query = urllib.parse.parse_qs(parsed.query)
                try:
                    days = max(1, min(365, int((query.get("days") or ["30"])[0])))
                except ValueError:
                    raise ValueError("Usage days must be an integer from 1 through 365") from None
                self.reply(200, usage_dashboard(days))
            elif parsed.path == "/api/subscription-usage":
                self.reply(200, subscription_usage.collect(router.CODEX_HOME))
            elif parsed.path == "/api/diagnostics":
                self.reply(200, {"router": router_health(), "log": redacted_log()})
            elif parsed.path.startswith("/api/"):
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
            elif self.path == "/api/oauth/anthropic/start":
                self.reply(200, start_claude_oauth())
            elif self.path == "/api/oauth/anthropic/complete":
                self.reply(200, complete_claude_oauth(body.get("code")))
            elif self.path == "/api/local/discover":
                models = discover_local(body.get("endpoint"))
                self.reply(200, {"ok": True, "models": models})
            elif self.path == "/api/credential":
                provider = body.get("provider")
                expected = {"opencode": "OPENCODE_API_KEY", "kimi": "KIMI_API_KEY"}.get(str(provider))
                value = body.get("key")
                if not expected or not isinstance(value, str) or not 8 <= len(value.strip()) <= 4096:
                    raise ValueError("Choose Kimi or OpenCode and enter a valid API key")
                _set_user_env(expected, value.strip())
                self.reply(200, {"ok": True, "message": f"{expected} saved in the current-user credential store. The value was not retained by the GUI."})
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
