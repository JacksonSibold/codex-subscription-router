"""Local model router for the ChatGPT (Codex) desktop app.

The app talks to a single model provider. This router is that provider: it listens on
127.0.0.1 and sends each request upstream by the request's "model":

  * OpenAI models -> OpenAI's Codex backend on Codex's attached ChatGPT login.
  * OpenCode Go, Kimi, Claude, and local models -> their isolated lanes and credentials.
  * The ChatGPT login is never forwarded to a third-party or local endpoint.

Requests bound for OpenCode are trimmed to what a standard Responses API accepts, and
reasoning items one lane produced are not replayed to the other.
"""
import copy
import hashlib
import http.client
import json
import os
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

import anthropic_adapter
import anthropic_oauth
import credentials
import error_explainer
import local_adapter
from loopback_server import LoopbackHTTPServer
import namespace_tools
import settings as router_settings
import usage_store
import version

HERE = os.path.dirname(os.path.abspath(__file__))
CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.dirname(HERE)
SETTINGS_PATH = os.environ.get("CODEX_ROUTER_SETTINGS") or os.path.join(HERE, "router-settings.json")
ACTIVE_SETTINGS = router_settings.load(SETTINGS_PATH)
HOST = "127.0.0.1"
PORT = int(os.environ.get("CODEX_ROUTER_PORT") or ACTIVE_SETTINGS["runtime"]["port"])
LOG_PATH = os.environ.get("CODEX_ROUTER_LOG") or os.path.join(HERE, "router.log")
ORIGINS_PATH = os.environ.get("CODEX_ROUTER_ORIGINS") or os.path.join(HERE, "reasoning-origins.json")
USAGE_PATH = os.environ.get("CODEX_ROUTER_USAGE_DB") or os.path.join(HERE, "router-usage.sqlite")


def reload_settings(document=None):
    """Swap validated preferences atomically; in-flight handler threads keep their snapshot."""
    global ACTIVE_SETTINGS
    ACTIVE_SETTINGS = document or router_settings.load(SETTINGS_PATH)
    return ACTIVE_SETTINGS


def enabled_models(provider=None):
    return {model["id"]: model for model in ACTIVE_SETTINGS["models"]
            if ACTIVE_SETTINGS["providers"][model["provider"]]["enabled"]
            and (provider is None or model["provider"] == provider)}


# Third-party endpoints speak the standard Responses API, not OpenAI's internal variants.
OPENCODE_CATALOG_OVERRIDES = {"use_responses_lite": False, "tool_mode": "direct", "apply_patch_tool_type": None,
                              "supports_search_tool": False, "supports_image_detail_original": False,
                              "experimental_supported_tools": [], "supports_reasoning_effort_updates": True}

LANES = {
    "openai": ("chatgpt.com", "/backend-api/codex"),
    "opencode": ("opencode.ai", "/inference/go/openai/v1"),
    "anthropic": ("api.anthropic.com", "/v1/messages?beta=true"),
    "kimi": ("api.kimi.ai", "/coding/v1"),
}
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
              "trailer", "transfer-encoding", "upgrade", "host", "content-length", "accept-encoding"}
UPSTREAM_HEADERS = {"content-type", "accept", "user-agent", "openai-beta", "originator", "session-id", "thread-id"}
# OpenAI-only tool types: connected-app namespaces (~100K tokens of schemas per request, and
# some upstreams such as xAI reject them) and OpenAI's hosted web search.
OPENAI_ONLY_TOOLS = ("namespace", "web_search")
SSL_CTX = ssl.create_default_context()
HTTPS_CONNECTION = http.client.HTTPSConnection
MAX_ORIGINS = 20000

log_lock = threading.Lock()
origins_lock = threading.Lock()


def log(msg):
    with log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def reasoning_levels(efforts):
    descriptions = {
        "minimal": "Minimal reasoning for the fastest responses",
        "low": "Light reasoning for simpler tasks",
        "medium": "Balanced speed and reasoning depth",
        "high": "Enhanced reasoning for complex tasks",
        "xhigh": "Extra-high reasoning for long-horizon tasks",
        "max": "Maximum reasoning depth",
    }
    return [{"effort": effort, "description": descriptions[effort]} for effort in efforts]


def opencode_models(document=None):
    document = document or ACTIVE_SETTINGS
    return {m["id"] for m in document["models"]
            if m["provider"] == "opencode" and document["providers"]["opencode"]["enabled"]}


def _read_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


BASE_INSTRUCTIONS = (
    "You are Codex, an AI coding assistant. Help the user with software development tasks in their "
    "workspace. Follow system and repository instructions, use available tools when needed, and be "
    "clear about what you changed and what you verified."
)

GENERIC_CATALOG_MODEL = {
    "base_instructions": BASE_INSTRUCTIONS,
    "description": "Model routed through Relay",
    "default_reasoning_level": "medium",
    "supported_reasoning_levels": [],
    "shell_type": "unified_exec",
    "visibility": "list",
    "supported_in_api": True,
    "availability_nux": None,
    "upgrade": None,
    "include_skills_usage_instructions": False,
    "include_plugin_usage_instructions": False,
    "include_apps_usage_instructions": False,
    "default_reasoning_summary": "none",
    "support_verbosity": False,
    "default_verbosity": "medium",
    "apply_patch_tool_type": "freeform",
    "web_search_tool_type": "text_and_image",
    "truncation_policy": {"mode": "bytes", "limit": 10000},
    "supports_image_detail_original": False,
    "context_window": 200000,
    "max_context_window": 200000,
    "comp_hash": "0",
    "effective_context_window_percent": 95,
    "experimental_supported_tools": [],
    "input_modalities": ["text", "image"],
    "supports_search_tool": False,
    "supports_experimental_context": False,
    "use_responses_lite": True,
    "supports_reasoning_effort_updates": True,
    "node_repl_auto_review_required": False,
    "node_repl_disabled": False,
    "tool_mode": "code_mode_only",
    "multi_agent_version": "disabled",
}


def _catalog_base(provider, upstream_id, cache, go):
    """Return provider-appropriate metadata even for a model absent from local caches.

    Provider catalogs change frequently, and users can deliberately enter an
    upstream ID that the local cache does not know yet. Falling back to another
    entry from the same provider keeps Codex wire behavior consistent; the final
    slug, names, reasoning, tools, and subagent settings are always overwritten
    from Relay preferences below.
    """
    generic = copy.deepcopy(GENERIC_CATALOG_MODEL)
    if provider == "openai":
        return copy.deepcopy(cache.get(upstream_id) or next(iter(cache.values()), None) or generic)
    if provider == "opencode":
        item = copy.deepcopy(go.get(upstream_id) or next(iter(go.values()), None) or generic)
        item.update(OPENCODE_CATALOG_OVERRIDES)
        return item
    return generic


def _catalog_map(filename):
    document = _read_json(os.path.join(CODEX_HOME, filename), {"models": []})
    models = document.get("models") if isinstance(document, dict) else None
    if not isinstance(models, list):
        return {}
    return {
        item["slug"]: item
        for item in models
        if isinstance(item, dict) and isinstance(item.get("slug"), str) and item["slug"]
    }


def build_catalog(document=None, output_path=None):
    """Build the ordered picker without changing Codex's configuration or restarting it."""
    document = document or ACTIVE_SETTINGS
    cache = _catalog_map("models_cache.json")
    go = _catalog_map("opencode-go-models.json")
    picks = []
    descriptions = {
        "openai": "OpenAI model through your existing Codex sign-in",
        "opencode": "OpenCode Go subscription model",
        "anthropic": "Claude subscription through Relay-owned OAuth",
        "kimi": "Kimi Code membership through the native Kimi Responses API",
        "local": "Local model through a loopback OpenAI-compatible endpoint",
    }
    for preference in document["models"]:
        provider = preference["provider"]
        if not preference["visible"] or not document["providers"][provider]["enabled"]:
            continue
        slug = preference["id"]
        upstream_id = preference["upstream_id"]
        item = _catalog_base(provider, upstream_id, cache, go)
        if provider != "openai":
            item.update({"supported_in_api": True, "input_modalities": ["text", "image"],
                         "supports_reasoning_effort_updates": True, "supports_search_tool": False, "tool_mode": "direct", "use_responses_lite": False})
            if provider == "anthropic":
                item.update({"context_window": 200000, "max_context_window": 1000000})
            elif provider == "local":
                item.update({"shell_type": "shell_command", "apply_patch_tool_type": "freeform",
                             "input_modalities": ["text"], "context_window": 131072,
                             "max_context_window": 131072,
                             "truncation_policy": {"mode": "bytes", "limit": 10000},
                             "supports_reasoning_summaries": True, "default_reasoning_summary": "none",
                             "support_verbosity": False})
            else:
                item.update({"shell_type": "shell_command", "apply_patch_tool_type": "freeform",
                             "context_window": 1048576, "max_context_window": 1048576,
                             "truncation_policy": {"mode": "bytes", "limit": 10000},
                             "supports_reasoning_summaries": True, "default_reasoning_summary": "none",
                             "support_verbosity": False})
        reasoning = preference["reasoning"]
        tools = preference["tools"]
        item.update({
            "slug": slug, "display_name": preference["display_name"], "description": descriptions[provider],
            "default_reasoning_level": reasoning["default"],
            "supported_reasoning_levels": reasoning_levels(reasoning["supported"]),
            "supports_reasoning_effort_updates": bool(reasoning["supported"]),
            "supports_search_tool": tools["web_search"],
            "node_repl_disabled": not tools["computer_use"],
            "multi_agent_version": "v2" if preference["subagents"] else "disabled",
        })
        if not tools["shell"]:
            item["shell_type"] = None
            item["apply_patch_tool_type"] = None
        picks.append(item)
    for index, model in enumerate(picks, 1):
        model["priority"], model["visibility"] = index, "list"
    path = output_path or os.path.join(CODEX_HOME, "mixed-models.json")
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump({"models": picks}, handle, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)
    return [m["slug"] for m in picks]


def _required_key(name):
    key = credentials.get_secret(name)
    if not key:
        raise credentials.CredentialError(f"{name} is not configured")
    return key


def opencode_key():
    return _required_key("OPENCODE_API_KEY")


def kimi_key():
    return _required_key("KIMI_API_KEY")


USAGE_ACCOUNT_LABELS = {
    "openai": "Codex account",
    "opencode": "OpenCode API key",
    "kimi": "Kimi API key",
    "anthropic": "Claude Relay OAuth",
    "anthropic_fallback": "OpenCode fallback",
}


def usage_account(lane, preference=None):
    """Return a stable, non-secret account label for the usage ledger."""
    if lane == "anthropic":
        return USAGE_ACCOUNT_LABELS["anthropic"] if anthropic_oauth.load_tokens() else USAGE_ACCOUNT_LABELS["anthropic_fallback"]
    if lane in USAGE_ACCOUNT_LABELS:
        return USAGE_ACCOUNT_LABELS[lane]
    if lane == "local" and preference:
        endpoint = preference.get("local", {}).get("endpoint", "")
        host = urlsplit(endpoint).netloc or "local endpoint"
        return "Local · " + host
    return lane


def record_usage(preference, lane, model, status, usage):
    try:
        provider = preference["provider"] if preference else lane
        usage_store.record(USAGE_PATH, provider, usage_account(lane, preference),
                           str(model or "unknown"), status, usage)
    except Exception as exc:
        log(f"ERROR usage ledger: {type(exc).__name__}")


def load_origins():
    try:
        with open(ORIGINS_PATH, encoding="utf-8") as f:
            return dict(json.load(f))
    except (OSError, ValueError):
        return {}


ORIGINS = load_origins()  # reasoning fingerprint -> lane that produced it


def fingerprint(item):
    blob = item.get("encrypted_content") or item.get("id") or ""
    return hashlib.sha1(blob.encode()).hexdigest() if blob else None


def remember_origins(found, lane):
    if not found:
        return
    with origins_lock:
        for fp in found:
            ORIGINS.pop(fp, None)
            ORIGINS[fp] = lane
        while len(ORIGINS) > MAX_ORIGINS:
            ORIGINS.pop(next(iter(ORIGINS)))
        tmp = ORIGINS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(ORIGINS.items()), f)
        os.replace(tmp, ORIGINS_PATH)


def drop_foreign_reasoning(body, lane):
    items = body.get("input")
    if not isinstance(items, list):
        return 0
    kept = [i for i in items
            if not (isinstance(i, dict) and i.get("type") == "reasoning"
                    and ORIGINS.get(fingerprint(i), lane) != lane)]
    body["input"] = kept
    return len(items) - len(kept)


def tidy_for_opencode(body):
    """Make a Codex request acceptable to OpenCode Go's standard Responses endpoint."""
    changed = False
    # Beam Free's portable route rejects verbosity; omit it and use the upstream default.
    if body.get("model") == "beam-free" and "verbosity" in body:
        body.pop("verbosity")
        changed = True
    tools = body.get("tools")
    if isinstance(tools, list):
        plain = [t for t in tools if not (isinstance(t, dict) and t.get("type") in OPENAI_ONLY_TOOLS)]
        changed = len(plain) != len(tools)
        body["tools"] = plain
        if not plain:
            body.pop("tools")
            body.pop("tool_choice", None)
    items = body.get("input")
    if isinstance(items, list):
        # OpenAI-lane turns leave "additional_tools" declarations (responses-lite) in the history.
        kept = [i for i in items if not (isinstance(i, dict) and i.get("type") == "additional_tools")]
        changed |= len(kept) != len(items)
        body["input"] = kept
    for item in body.get("input") or []:
        # Codex replays reasoning with "content": null; xAI rejects the whole blob over it.
        if isinstance(item, dict) and item.get("type") == "reasoning" and "content" in item \
                and item["content"] is None:
            del item["content"]
            changed = True
    return changed


def apply_tool_policy(body, preference):
    """Enforce the selected model's tool policy before any provider sees the request."""
    tools = preference["tools"]
    changed = False

    def allowed(tool):
        if not isinstance(tool, dict):
            return True
        kind = tool.get("type")
        name = str(tool.get("name") or "")
        if kind == "namespace":
            computer = name.startswith(namespace_tools.ALLOWED_PREFIXES)
            return tools["computer_use"] if computer else tools["connected_apps"]
        if kind == "web_search" or (isinstance(kind, str) and kind.startswith("web_search")):
            return tools["web_search"]
        if kind == "local_shell" or name in {"shell", "exec_command", "unified_exec", "write_stdin", "apply_patch"}:
            return tools["shell"]
        return True

    if isinstance(body.get("tools"), list):
        kept = [tool for tool in body["tools"] if allowed(tool)]
        changed = len(kept) != len(body["tools"])
        body["tools"] = kept
    for item in body.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "additional_tools" and isinstance(item.get("tools"), list):
            kept = [tool for tool in item["tools"] if allowed(tool)]
            changed |= len(kept) != len(item["tools"])
            item["tools"] = kept
    if not body.get("tools"):
        body.pop("tools", None)
        body.pop("tool_choice", None)
    return changed


class SseReasoningScanner:
    """Collect reasoning fingerprints and terminal token usage from Responses SSE."""

    def __init__(self):
        self.buf = b""
        self.found = []
        self.usage = {}

    def _event(self, event):
        for line in event.split(b"\n"):
            if not line.startswith(b"data:"):
                continue
            try:
                data = json.loads(line[5:])
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            kind = data.get("type")
            if kind in ("response.completed", "response.incomplete", "response.failed", "response.done"):
                response = data.get("response") if isinstance(data.get("response"), dict) else data
                usage = response.get("usage")
                if isinstance(usage, dict):
                    self.usage = usage
            item = data.get("item")
            if kind == "response.output_item.done" and isinstance(item, dict) \
                    and item.get("type") == "reasoning":
                fp = fingerprint(item)
                if fp:
                    self.found.append(fp)

    def feed(self, chunk):
        self.buf += chunk
        *events, self.buf = self.buf.split(b"\n\n")
        for event in events:
            self._event(event)

    def finish(self):
        rest, self.buf = self.buf, b""
        if rest:
            self._event(rest)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def read_body(self):
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            out = b""
            while True:
                size = int(self.rfile.readline().split(b";")[0], 16)
                if size == 0:
                    self.rfile.readline()
                    return out
                out += self.rfile.read(size)
                self.rfile.readline()
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def respond_json(self, status, value):
        msg = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)

    def do_GET(self):
        if self.path == "/__router_health":
            self.respond_json(200, {"namespace_bridge": namespace_tools.VERSION, "pid": os.getpid(),
                                    "models": len(enabled_models()), "settings_version": ACTIVE_SETTINGS["version"],
                                    "relay_version": version.__version__})
            return
        self.route(b"")

    def do_POST(self):
        raw = self.read_body()
        if self.path == "/__router_reload":
            try:
                document = reload_settings()
                models = build_catalog(document)
                self.respond_json(200, {"ok": True, "models": models})
            except Exception as exc:
                log(f"ERROR settings reload: {exc!r}")
                self.respond_json(400, {"ok": False, "error": str(exc)})
            return
        self.route(raw)

    def do_DELETE(self):
        self.route(self.read_body())

    def bridge_start(self, status, headers):
        self._bridge_chunked = not any(k.lower() == "content-length" for k, _ in headers)
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        if self._bridge_chunked:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def bridge_emit(self, event_type, data):
        payload = ("event: " + event_type + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode()
        self.wfile.write(b"%x\r\n%s\r\n" % (len(payload), payload))
        self.wfile.flush()

    def bridge_raw(self, data):
        if self._bridge_chunked:
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()
        else:
            self.wfile.write(data)
            self.wfile.flush()

    def route_anthropic(self, body, model, preference, started, dropped):
        status, sent, usage = anthropic_adapter.run(
            body, self.bridge_start, self.bridge_emit, self.bridge_raw, log)
        if getattr(self, "_bridge_chunked", False):
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        record_usage(preference, "anthropic", model, status, usage)
        log(f"{self.command} {self.path} model={model} lane=anthropic status={status} bytes={sent} "
            f"dropped_reasoning={dropped} {time.time() - started:.1f}s")

    def route_local(self, body, model, preference, started, dropped, ns_map):
        local = preference.get("local") or {}
        if local.get("protocol") == "openai_chat":
            status, sent, usage = local_adapter.run_chat(
                body, local, self.bridge_start, self.bridge_emit, self.bridge_raw, log,
                local.get("endpoint", ""), ns_map)
        else:
            status, sent, usage = local_adapter.run_responses(
                body, local, self.bridge_start, self.bridge_raw, log,
                local.get("endpoint", ""), ns_map)
        if getattr(self, "_bridge_chunked", False):
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        record_usage(preference, "local", model, status, usage)
        log(f"{self.command} {self.path} model={model} lane=local protocol={local.get('protocol')} "
            f"status={status} bytes={sent} dropped_reasoning={dropped} {time.time() - started:.1f}s")

    def route(self, raw):
        started = time.time()
        model, body, lane, dropped, ns_map = None, None, "openai", 0, {}
        encoded = self.headers.get("Content-Encoding", "identity").lower() not in ("", "identity")
        if raw and not encoded:
            try:
                body = json.loads(raw)
                model = body.get("model") if isinstance(body, dict) else None
            except ValueError:
                body = None
        snapshot = ACTIVE_SETTINGS
        preference = next((m for m in snapshot["models"] if m["id"] == model), None)
        if preference and not snapshot["providers"][preference["provider"]]["enabled"]:
            self.respond_json(400, {"error": {"message": f"Provider is disabled for model: {model}"}})
            record_usage(preference, preference["provider"], model, 400, {})
            return
        if preference:
            lane = preference["provider"]
        if isinstance(body, dict):
            if preference:
                # Codex sees the stable picker slug; providers receive their own model identifier.
                body["model"] = preference["upstream_id"]
            dropped = drop_foreign_reasoning(body, lane)
            policy_changed = apply_tool_policy(body, preference) if preference else False
            if lane == "anthropic":
                return self.route_anthropic(body, model, preference, started, dropped)
            flattened = False
            if lane in ("opencode", "kimi", "local"):
                # Flatten Computer Use before removing unsupported connected-app namespaces.
                ns_map, flattened = namespace_tools.flatten_request(body)
            tidied = tidy_for_opencode(body) if lane in ("opencode", "kimi", "local") else False
            if dropped or tidied or flattened or policy_changed or preference:
                raw = json.dumps(body).encode()
            if lane == "local":
                if not preference:
                    self.respond_json(400, {"error": {"message": f"Unknown local model: {model}"}})
                    return
                return self.route_local(body, model, preference, started, dropped, ns_map)

        try:
            host, prefix = LANES[lane]
            if lane in ("opencode", "kimi"):
                # Forward Codex's real User-Agent, but never forward its ChatGPT credential.
                headers = {k: v for k, v in self.headers.items() if k.lower() in UPSTREAM_HEADERS}
                headers["Authorization"] = "Bearer " + (opencode_key() if lane == "opencode" else kimi_key())
                if lane == "opencode":
                    # Go wants one stable id per conversation for routing and prompt caching.
                    session = self.headers.get("thread-id") or self.headers.get("session-id")
                    if session:
                        headers["x-opencode-session"] = session
            else:
                headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            headers["Accept-Encoding"] = "identity"
            if raw:
                headers["Content-Length"] = str(len(raw))
        except Exception as exc:
            explanation = error_explainer.explain(lane, 401, str(exc).encode())
            explanation["message"] = (
                f"Relay: the {error_explainer.PROVIDER_NAMES.get(lane, lane)} credential is unavailable. "
                f"Reconnect that account in Relay Connections. Provider detail: "
                f"{error_explainer.provider_detail(str(exc))}"
            )
            explanation["code"] = "credential_unavailable"
            self.respond_json(502, {"error": explanation})
            record_usage(preference, lane, model, 502, {})
            log(f"ERROR code=credential_unavailable lane={lane} model={model}")
            return

        status, sent, scanner = 502, 0, SseReasoningScanner()
        rewriter = namespace_tools.SseRewriter(ns_map)
        response_started = False
        try:
            conn = HTTPS_CONNECTION(host, timeout=600, context=SSL_CTX)
            conn.request(self.command, prefix + self.path, body=raw or None, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            if status >= 400:
                error_body = resp.read(1_000_000)
                explanation = error_explainer.explain(lane, status, error_body)
                self.respond_json(status, {"error": explanation})
                conn.close()
                record_usage(preference, lane, model, status, {})
                log(
                    f"ERROR code={explanation['code']} lane={lane} model={model} "
                    f"status={status} detail={explanation['detail']!r}"
                )
                return
            self.send_response(status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_BY_HOP and not (ns_map and k.lower() == "content-length"):
                    self.send_header(k, v)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            response_started = True
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                sent += len(chunk)
                scanner.feed(chunk)
                chunk = rewriter.feed(chunk)
                if chunk:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
            tail = rewriter.flush()
            if tail:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(tail), tail))
            scanner.finish()
            self.wfile.write(b"0\r\n\r\n")
            conn.close()
        except Exception as e:  # upstream unreachable, or the app hung up mid-stream
            if not response_started:
                status = 502
                explanation = error_explainer.explain(lane, status, str(e).encode())
                explanation["code"] = "upstream_unreachable"
                msg = json.dumps({"error": explanation}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            log(
                f"ERROR code=upstream_unreachable lane={lane} path={self.path} "
                f"model={model}: {error_explainer.provider_detail(str(e))}"
            )
        record_usage(preference, lane, model, status, scanner.usage)
        if os.environ.get("ROUTER_DUMP_DIR"):  # debugging aid: keep the exact request sent upstream
            with open(os.path.join(os.environ["ROUTER_DUMP_DIR"], f"{lane}-{model}-{int(started * 1000)}.json"), "wb") as f:
                f.write(raw)
        remember_origins(scanner.found, lane)
        log(f"{self.command} {self.path} model={model} lane={lane} status={status} bytes={sent} "
            f"ns_tools={len(ns_map)} dropped_reasoning={dropped}{' ENCODED-BODY' if encoded else ''} {time.time() - started:.1f}s")

def main():
    log(f"router service starting; pid={os.getpid()} port={PORT}")
    try:
        namespace_tools.self_test()
        log("namespace bridge self-test passed")
    except Exception as e:
        log(f"FATAL namespace bridge self-test failed, refusing to start: {e!r}")
        sys.exit(1)
    log(f"binding router on {HOST}:{PORT}")
    try:
        server = LoopbackHTTPServer((HOST, PORT), Handler)
    except OSError:
        sys.exit(0)  # already running
    log(f"router bound on {HOST}:{PORT}")
    if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 2_000_000:
        os.replace(LOG_PATH, LOG_PATH + ".old")
    log(f"namespace bridge v{namespace_tools.VERSION} ok; listening on {HOST}:{PORT}; enabled models: {sorted(enabled_models())}")
    try:
        log(f"rebuilt mixed-models.json: {build_catalog()}")
    except Exception as e:  # keep serving with the existing catalog
        log(f"ERROR rebuilding mixed-models.json: {e!r}")
    server.serve_forever()


if __name__ == "__main__":
    main()
