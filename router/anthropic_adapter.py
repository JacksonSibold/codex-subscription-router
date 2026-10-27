"""Bridge Codex Responses requests to Anthropic Messages.

Relay owns the primary Claude OAuth connection. Existing OpenCode Anthropic
tokens are accepted as a fallback for installations that already used them.
"""
from __future__ import annotations

import http.client
import json
import hashlib
import re
import os
import platform
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

import anthropic_oauth
import error_explainer

ANTHROPIC_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}

AUTH_PATH = Path(os.environ.get("OPENCODE_AUTH_PATH") or Path.home() / ".local" / "share" / "opencode" / "auth.json")
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload user:plugins"
USER_AGENT = "claude-cli/2.1.296 (external, sdk-cli)"
BETAS = ",".join([
    "claude-code-20250219",
    "oauth-2025-04-20",
    "interleaved-thinking-2025-05-14",
    "thinking-token-count-2026-05-13",
    "context-management-2025-06-27",
    "prompt-caching-scope-2026-01-05",
    "mid-conversation-system-2026-04-07",
    "per-turn-control-2026-07-01",
    "mid-conversation-tool-changes-2026-07-01",
    "inline-tools-2026-09-15",
    "advisor-tool-2026-03-01",
    "effort-2025-11-24",
    "extended-cache-ttl-2025-04-11",
])
IDENTITY = "You are a Claude agent, built on Anthropic's Claude Agent SDK."
REFRESH_BUFFER_MS = 5 * 60 * 1000
_auth_lock = threading.Lock()


def _read_auth() -> dict[str, Any]:
    with AUTH_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _refresh_auth(log: Callable[[str], None]) -> str:
    auth = _read_auth()
    token = auth.get("anthropic") or {}
    refresh = token.get("refresh")
    if not refresh:
        raise RuntimeError("Anthropic OAuth refresh token is missing; reconnect Anthropic in OpenCode")
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": CLIENT_ID,
        "scope": SCOPES,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        log(f"ERROR anthropic token refresh status={exc.code} detail={detail}")
        raise RuntimeError(f"Anthropic token refresh failed with HTTP {exc.code}") from None
    access = data.get("access_token")
    if not isinstance(access, str) or not access:
        raise RuntimeError("Anthropic token refresh returned no access token")
    next_refresh = data.get("refresh_token") if isinstance(data.get("refresh_token"), str) else refresh
    lifetime = data.get("expires_in") if isinstance(data.get("expires_in"), (int, float)) else 3600
    expires = int(time.time() * 1000 + lifetime * 1000)
    token.update({"type": "oauth", "refresh": next_refresh, "access": access, "expires": expires})
    auth["anthropic"] = token
    tmp = AUTH_PATH.with_name(AUTH_PATH.name + ".tmp-" + uuid.uuid4().hex)
    tmp.write_text(json.dumps(auth, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, AUTH_PATH)
    log("anthropic OAuth credential refreshed")
    return access


def access_token(log: Callable[[str], None]) -> str:
    """Prefer Relay's own OAuth token, then fall back to a pre-existing OpenCode token."""
    try:
        return anthropic_oauth.access_token(log)
    except RuntimeError as relay_error:
        try:
            with _auth_lock:
                auth = _read_auth()
                token = auth.get("anthropic") or {}
                access = token.get("access")
                expires = token.get("expires")
                if isinstance(access, str) and access and isinstance(expires, (int, float)) and expires > time.time() * 1000 + REFRESH_BUFFER_MS:
                    return access
                return _refresh_auth(log)
        except FileNotFoundError:
            raise RuntimeError("Claude is not connected. Connect it in Relay's Connections page.") from relay_error


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


# MCP server tools arrive as {"type": "namespace", "name": "mcp__node_repl", "tools": [...]}.
# Anthropic has no namespaces, so allowed groups are flattened to "<namespace>__<tool>" and
# mapped back on the way out. Connector app namespaces stay excluded (huge schemas).
from namespace_tools import ALLOWED_PREFIXES as NAMESPACE_PREFIXES, join_name as _join_name

LAST_SKIPPED_NAMESPACES: list[str] = []
namespaced: dict[str, tuple[str, str]] = {}


def _tool_definitions(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    raw_tools: list[dict[str, Any]] = []

    def add_tool(tool: Any) -> None:
        if isinstance(tool, dict):
            raw_tools.append(tool)

    def add_group(group: Any) -> None:
        if not isinstance(group, dict):
            return
        if group.get("type") != "namespace":
            add_tool(group)
            return
        ns = group.get("name")
        if not (isinstance(ns, str) and ns.startswith(NAMESPACE_PREFIXES)):
            if isinstance(ns, str):
                skipped.append(ns)
            return
        for child in group.get("tools") or []:
            if isinstance(child, dict) and isinstance(child.get("name"), str):
                flat = dict(child)
                flat["name"] = _join_name(ns, child["name"])
                namespaced[flat["name"]] = (ns, child["name"])
                add_tool(flat)

    skipped: list[str] = []
    for tool in body.get("tools") or []:
        add_group(tool)
    for item in body.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            for group in item.get("tools") or []:
                if not isinstance(group, dict):
                    continue
                add_group(group)

    if skipped:
        LAST_SKIPPED_NAMESPACES[:] = sorted(set(skipped))
    tools: list[dict[str, Any]] = []
    kinds: dict[str, str] = {}
    seen: set[str] = set()
    for tool in raw_tools:
        name = tool.get("name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        kind = tool.get("type")
        if kind == "custom":
            description = str(tool.get("description") or "")
            fmt = tool.get("format")
            if fmt:
                description += "\n\nTool input format:\n" + json.dumps(fmt, ensure_ascii=False)
            description += (
                "\n\nThis is a freeform tool. Call it with a JSON object containing exactly one "
                "string field named `input`. Put the complete raw tool input in that string; do not "
                "JSON-encode or wrap the tool input again."
            )
            schema = {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "The complete raw freeform input for this tool.",
                    }
                },
                "required": ["input"],
                "additionalProperties": False,
            }
            kinds[name] = "custom"
        elif kind == "function":
            description = str(tool.get("description") or "")
            schema = tool.get("parameters") or {"type": "object", "properties": {}}
            if not isinstance(schema, dict) or schema.get("type") != "object":
                schema = {"type": "object", "properties": {}}
            kinds[name] = "function"
        else:
            continue
        tools.append({"name": name, "description": description, "input_schema": schema})
    return tools, kinds


def _append_message(messages: list[dict[str, Any]], role: str, blocks: list[dict[str, Any]]) -> None:
    if not blocks:
        return
    if messages and messages[-1].get("role") == role:
        messages[-1].setdefault("content", []).extend(blocks)
    else:
        messages.append({"role": role, "content": blocks})


def build_payload(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    system_parts = [IDENTITY]
    messages: list[dict[str, Any]] = []
    tools, tool_kinds = _tool_definitions(body)

    for item in body.get("input") or []:
        if not isinstance(item, dict):
            continue
        typ = item.get("type")
        if typ == "additional_tools":
            continue
        if typ == "message":
            role = item.get("role")
            text = _text_from_content(item.get("content"))
            if not text:
                continue
            if role in ("system", "developer"):
                system_parts.append(text)
            elif role == "assistant":
                _append_message(messages, "assistant", [{"type": "text", "text": text}])
            elif role == "user":
                _append_message(messages, "user", [{"type": "text", "text": text}])
        elif typ == "custom_tool_call":
            call_id = item.get("call_id") or ("call_" + uuid.uuid4().hex)
            name = item.get("name")
            raw = item.get("input")
            if not isinstance(raw, str):
                raw = json.dumps(raw, ensure_ascii=False) if raw is not None else ""
            if isinstance(name, str) and name:
                _append_message(messages, "assistant", [{
                    "type": "tool_use", "id": call_id, "name": name, "input": {"input": raw}
                }])
        elif typ == "function_call":
            call_id = item.get("call_id") or ("call_" + uuid.uuid4().hex)
            name = item.get("name")
            if isinstance(item.get("namespace"), str) and isinstance(name, str):
                name = _join_name(item["namespace"], name)
            raw = item.get("arguments")
            if isinstance(raw, str):
                try:
                    args = json.loads(raw) if raw.strip() else {}
                except ValueError:
                    args = {"input": raw}
            elif isinstance(raw, dict):
                args = raw
            else:
                args = {}
            if isinstance(name, str) and name:
                _append_message(messages, "assistant", [{
                    "type": "tool_use", "id": call_id, "name": name, "input": args
                }])
        elif typ in ("custom_tool_call_output", "function_call_output"):
            call_id = item.get("call_id")
            output = item.get("output")
            if not isinstance(output, str):
                output = json.dumps(output, ensure_ascii=False) if output is not None else ""
            if isinstance(call_id, str) and call_id:
                _append_message(messages, "user", [{
                    "type": "tool_result", "tool_use_id": call_id, "content": output
                }])
        # Reasoning/compaction items are intentionally not replayed to Anthropic.

    if not messages:
        messages = [{"role": "user", "content": [{"type": "text", "text": "Continue."}]}]
    if messages[0]["role"] == "assistant":
        messages.insert(0, {"role": "user", "content": [{"type": "text", "text": "Continue."}]})

    payload: dict[str, Any] = {
        "model": body.get("model"),
        "max_tokens": 64000,
        "stream": True,
        "system": [{"type": "text", "text": text} for text in system_parts if isinstance(text, str) and text],
        "messages": messages,
    }
    reasoning = body.get("reasoning")
    effort = reasoning.get("effort") if isinstance(reasoning, dict) else None
    if effort in {"low", "medium", "high", "xhigh", "max"}:
        payload["output_config"] = {"effort": effort}
    if tools:
        payload["tools"] = tools
        choice = body.get("tool_choice")
        if choice == "required":
            payload["tool_choice"] = {"type": "any"}
        elif choice == "none":
            payload["tool_choice"] = {"type": "none"}
        elif isinstance(choice, dict) and choice.get("type") == "function" and isinstance(choice.get("name"), str):
            payload["tool_choice"] = {"type": "tool", "name": choice["name"]}
        else:
            payload["tool_choice"] = {"type": "auto"}
        if body.get("parallel_tool_calls") is False:
            payload["tool_choice"]["disable_parallel_tool_use"] = True
    return payload, tool_kinds


def _platform_headers() -> tuple[str, str]:
    system = platform.system().strip().lower()
    if system.startswith("win"):
        os_name = "Windows"
    elif system == "darwin" or system == "macos":
        os_name = "MacOS"
    elif system.startswith("linux"):
        os_name = "Linux"
    else:
        os_name = platform.system().strip() or "Unknown"
    machine = platform.machine().strip().lower()
    architecture = {
        "x86_64": "x64", "amd64": "x64", "x64": "x64",
        "aarch64": "arm64", "arm64": "arm64",
        "i386": "x86", "i686": "x86", "x86": "x86",
    }.get(machine, machine or "unknown")
    return os_name, architecture


def _headers(token: str, session_id: str) -> dict[str, str]:
    os_name, architecture = _platform_headers()
    return {
        "authorization": "Bearer " + token,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": BETAS,
        "user-agent": USER_AGENT,
        "x-app": "cli",
        "x-claude-code-session-id": session_id,
        "content-type": "application/json",
        "accept": "text/event-stream",
        "anthropic-dangerous-direct-browser-access": "true",
        "x-stainless-arch": architecture,
        "x-stainless-lang": "js",
        "x-stainless-os": os_name,
        "x-stainless-package-version": "0.128.0",
        "x-stainless-retry-count": "0",
        "x-stainless-runtime": "node",
        "x-stainless-runtime-version": "v26.3.0",
        "x-stainless-timeout": "600",
    }


class ResponsesTranslator:
    def __init__(self, model: str, tool_kinds: dict[str, str], emit: Callable[[str, dict[str, Any]], None]):
        self.model = model
        self.tool_kinds = tool_kinds
        self.emit = emit
        self.seq = 0
        self.created_at = int(time.time())
        self.response_id = "resp_" + uuid.uuid4().hex
        self.output: list[dict[str, Any]] = []
        self.blocks: dict[int, dict[str, Any]] = {}
        self.next_output_index = 0
        self.usage: dict[str, Any] = {}
        self.completed = False
        self.started = False
        self.stop_reason: str | None = None

    def send(self, event_type: str, data: dict[str, Any]) -> None:
        data = {"type": event_type, "sequence_number": self.seq, **data}
        self.seq += 1
        self.emit(event_type, data)

    def response_object(self, status: str, output: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        usage = None
        if status in ("completed", "incomplete", "failed"):
            inv = int(self.usage.get("input_tokens") or 0)
            outv = int(self.usage.get("output_tokens") or 0)
            cached = int(self.usage.get("cache_read_input_tokens") or 0)
            usage = {
                "input_tokens": inv,
                "input_tokens_details": {"cached_tokens": cached},
                "output_tokens": outv,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": inv + outv,
            }
        return {
            "id": self.response_id,
            "object": "response",
            "created_at": self.created_at,
            "completed_at": int(time.time()) if status != "in_progress" else None,
            "status": status,
            "background": False,
            "model": self.model,
            "output": output or [],
            "error": None,
            "incomplete_details": None,
            "usage": usage,
        }

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self.send("response.created", {"response": self.response_object("in_progress")})
        self.send("response.in_progress", {"response": self.response_object("in_progress")})

    def block_start(self, index: int, block: dict[str, Any]) -> None:
        self.start()
        typ = block.get("type")
        out_index = self.next_output_index
        self.next_output_index += 1
        if typ == "text":
            item_id = "msg_" + uuid.uuid4().hex
            item = {
                "type": "message", "id": item_id, "role": "assistant", "status": "in_progress",
                "content": [], "phase": "final_answer",
            }
            self.blocks[index] = {"kind": "text", "output_index": out_index, "item_id": item_id, "text": "", "item": item}
            self.send("response.output_item.added", {"output_index": out_index, "item": item})
            self.send("response.content_part.added", {
                "item_id": item_id, "output_index": out_index, "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": [], "logprobs": []},
            })
        elif typ == "tool_use":
            name = str(block.get("name") or "")
            call_id = str(block.get("id") or ("call_" + uuid.uuid4().hex))
            kind = self.tool_kinds.get(name, "function")
            if kind == "custom":
                item_id = "ctc_" + uuid.uuid4().hex
                item = {
                    "type": "custom_tool_call", "id": item_id, "call_id": call_id, "name": name,
                    "input": "", "status": "in_progress",
                }
            else:
                item_id = "fc_" + uuid.uuid4().hex
                item = {
                    "type": "function_call", "id": item_id, "call_id": call_id, "name": name,
                    "arguments": "", "status": "in_progress",
                }
                if name in namespaced:
                    item["namespace"], item["name"] = namespaced[name]
            self.blocks[index] = {
                "kind": kind, "output_index": out_index, "item_id": item_id,
                "call_id": call_id, "name": name, "raw": "", "item": item,
            }
            self.send("response.output_item.added", {"output_index": out_index, "item": item})

    def block_delta(self, index: int, delta: dict[str, Any]) -> None:
        state = self.blocks.get(index)
        if not state:
            return
        if state["kind"] == "text":
            text = delta.get("text")
            if isinstance(text, str) and text:
                state["text"] += text
                self.send("response.output_text.delta", {
                    "item_id": state["item_id"], "output_index": state["output_index"],
                    "content_index": 0, "delta": text, "logprobs": [],
                })
        elif delta.get("type") == "input_json_delta":
            part = delta.get("partial_json")
            if isinstance(part, str):
                state["raw"] += part

    def block_stop(self, index: int) -> None:
        state = self.blocks.pop(index, None)
        if not state:
            return
        out_index = state["output_index"]
        item = state["item"]
        if state["kind"] == "text":
            text = state["text"]
            self.send("response.output_text.done", {
                "item_id": state["item_id"], "output_index": out_index, "content_index": 0,
                "text": text, "logprobs": [],
            })
            part = {"type": "output_text", "text": text, "annotations": [], "logprobs": []}
            self.send("response.content_part.done", {
                "item_id": state["item_id"], "output_index": out_index, "content_index": 0, "part": part,
            })
            item.update({"status": "completed", "content": [part]})
            self.send("response.output_item.done", {"output_index": out_index, "item": item})
        elif state["kind"] == "custom":
            raw_json = state["raw"]
            try:
                parsed = json.loads(raw_json) if raw_json.strip() else {}
            except ValueError:
                parsed = {"input": raw_json}
            if isinstance(parsed, dict):
                value = parsed.get("input")
                if not isinstance(value, str):
                    value = next((v for v in parsed.values() if isinstance(v, str)), raw_json)
            else:
                value = raw_json
            if value:
                self.send("response.custom_tool_call_input.delta", {
                    "item_id": state["item_id"], "output_index": out_index, "delta": value,
                })
            self.send("response.custom_tool_call_input.done", {
                "item_id": state["item_id"], "output_index": out_index, "input": value,
            })
            item.update({"status": "completed", "input": value})
            self.send("response.output_item.done", {"output_index": out_index, "item": item})
        else:
            arguments = state["raw"] or "{}"
            self.send("response.function_call_arguments.delta", {
                "item_id": state["item_id"], "output_index": out_index, "delta": arguments,
            })
            self.send("response.function_call_arguments.done", {
                "item_id": state["item_id"], "output_index": out_index, "arguments": arguments,
            })
            item.update({"status": "completed", "arguments": arguments})
            self.send("response.output_item.done", {"output_index": out_index, "item": item})
        self.output.append(item)

    def message_start(self, message: dict[str, Any]) -> None:
        self.start()
        mid = message.get("id")
        if isinstance(mid, str) and mid:
            self.response_id = "resp_" + mid.replace("msg_", "")
        usage = message.get("usage")
        if isinstance(usage, dict):
            self.usage.update(usage)

    def message_delta(self, data: dict[str, Any]) -> None:
        usage = data.get("usage")
        if isinstance(usage, dict):
            self.usage.update(usage)
        delta = data.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
            self.stop_reason = delta["stop_reason"]

    def finish(self) -> None:
        if self.completed:
            return
        self.start()
        for index in list(self.blocks):
            self.block_stop(index)
        status = "incomplete" if self.stop_reason == "max_tokens" else "completed"
        response = self.response_object(status, self.output)
        if status == "incomplete":
            response["incomplete_details"] = {"reason": "max_output_tokens"}
        self.send("response." + status, {"response": response})
        self.completed = True

    def fail(self, message: str) -> None:
        if self.completed:
            return
        self.start()
        response = self.response_object("failed", self.output)
        response["error"] = {"code": "upstream_error", "message": message}
        self.send("response.failed", {"response": response})
        self.completed = True


def _sse_blocks(resp: http.client.HTTPResponse):
    buf = ""
    while True:
        chunk = resp.read1(65536)
        if not chunk:
            break
        buf += chunk.decode("utf-8", "replace").replace("\r\n", "\n")
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            event = None
            data_lines: list[str] = []
            for line in block.split("\n"):
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if data_lines:
                yield event, "\n".join(data_lines)


def run(
    body: dict[str, Any],
    start: Callable[[int, list[tuple[str, str]]], None],
    emit: Callable[[str, dict[str, Any]], None],
    write_raw: Callable[[bytes], None],
    log: Callable[[str], None],
) -> tuple[int, int, dict[str, Any]]:
    payload, tool_kinds = build_payload(body)
    token = access_token(log)
    session_id = str(body.get("prompt_cache_key") or uuid.uuid4())
    raw = json.dumps(payload, ensure_ascii=False).encode()
    conn = http.client.HTTPSConnection("api.anthropic.com", timeout=600)
    sent = 0
    try:
        conn.request("POST", "/v1/messages?beta=true", body=raw, headers=_headers(token, session_id))
        resp = conn.getresponse()
        if resp.status != 200:
            error = resp.read(1_000_000)
            explanation = error_explainer.explain("anthropic", resp.status, error)
            payload = json.dumps({"error": explanation}, ensure_ascii=False).encode()
            start(resp.status, [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))])
            write_raw(payload)
            log(
                f"ERROR code={explanation['code']} lane=anthropic status={resp.status} "
                f"detail={explanation['detail']!r}"
            )
            return resp.status, len(payload), {}

        start(200, [("Content-Type", "text/event-stream; charset=utf-8")])
        translator = ResponsesTranslator(str(body.get("model")), tool_kinds, emit)
        for event, data_text in _sse_blocks(resp):
            sent += len(data_text)
            try:
                data = json.loads(data_text)
            except ValueError:
                continue
            event = event or data.get("type")
            if event == "message_start":
                translator.message_start(data.get("message") or {})
            elif event == "content_block_start":
                translator.block_start(int(data.get("index", 0)), data.get("content_block") or {})
            elif event == "content_block_delta":
                translator.block_delta(int(data.get("index", 0)), data.get("delta") or {})
            elif event == "content_block_stop":
                translator.block_stop(int(data.get("index", 0)))
            elif event == "message_delta":
                translator.message_delta(data)
            elif event == "message_stop":
                translator.finish()
            elif event == "error":
                err = data.get("error") or {}
                explanation = error_explainer.explain(
                    "anthropic", 502, json.dumps(err, ensure_ascii=False).encode()
                )
                translator.fail(explanation["message"])
                log(
                    f"ERROR code={explanation['code']} lane=anthropic stream "
                    f"detail={explanation['detail']!r}"
                )
        translator.finish()
        return 200, sent, dict(translator.usage)
    except Exception as exc:
        explanation = error_explainer.explain("anthropic", 502, str(exc).encode())
        log(f"ERROR code=upstream_unreachable lane=anthropic stream detail={explanation['detail']!r}")
        try:
            error = json.dumps({"error": explanation}, ensure_ascii=False).encode()
            start(502, [("Content-Type", "application/json"), ("Content-Length", str(len(error)))])
            write_raw(error)
        except Exception:
            pass
        return 502, sent, {}
    finally:
        conn.close()
