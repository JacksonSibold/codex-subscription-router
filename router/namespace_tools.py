"""Expose Codex namespace tool groups (MCP servers such as Computer Use) to non-OpenAI models.

Codex sends MCP tools as {"type": "namespace", "name": "mcp__node_repl__", "tools": [...]}
and expects calls back as {"type": "function_call", "namespace": ..., "name": "js"}.
Standard Responses / Anthropic endpoints only know flat function tools, so requests are
flattened to "<namespace><tool>" names here and responses are mapped back.

Every non-OpenAI lane in router.py goes through flatten_request(); router.py runs
self_test() at startup and logs loudly if this bridge is missing or broken.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# Namespaces passed through. Connector app namespaces (Gmail, Drive, ...) stay excluded:
# they add ~100K tokens of schemas per request and some upstreams reject them.
ALLOWED_PREFIXES = ("mcp__node_repl", "mcp__cua_repl")
VERSION = 1


def join_name(ns: str, name: str) -> str:
    joined = ns + name if ns.endswith("__") else ns + "__" + name
    joined = re.sub(r"[^a-zA-Z0-9_-]", "_", joined)
    if len(joined) > 64:
        joined = joined[:55] + "_" + hashlib.sha1(joined.encode()).hexdigest()[:8]
    return joined


def _flatten_group(group: dict[str, Any], mapping: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    ns = group.get("name")
    if not (isinstance(ns, str) and ns.startswith(ALLOWED_PREFIXES)):
        return []
    out = []
    for child in group.get("tools") or []:
        if isinstance(child, dict) and isinstance(child.get("name"), str):
            flat = {k: v for k, v in child.items() if k != "defer_loading"}
            flat["type"] = flat.get("type") or "function"
            flat["name"] = join_name(ns, child["name"])
            mapping[flat["name"]] = (ns, child["name"])
            out.append(flat)
    return out


def flatten_request(body: dict[str, Any]) -> tuple[dict[str, tuple[str, str]], bool]:
    """Rewrite body in place. Returns (flat name -> (namespace, name), changed)."""
    mapping: dict[str, tuple[str, str]] = {}
    changed = False
    tools = body.get("tools")
    new_tools: list[Any] = []
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and tool.get("type") == "namespace":
                new_tools.extend(_flatten_group(tool, mapping))
                changed = True
            else:
                new_tools.append(tool)
    # responses-lite declares tools inside "additional_tools" input items.
    for item in body.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            for group in item.get("tools") or []:
                if isinstance(group, dict) and group.get("type") == "namespace":
                    new_tools.extend(_flatten_group(group, mapping))
                    changed = True
    if changed:
        seen, deduped = set(), []
        for t in new_tools:
            key = t.get("name") if isinstance(t, dict) else None
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            deduped.append(t)
        body["tools"] = deduped
    for item in body.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "function_call" and isinstance(item.get("namespace"), str):
            item["name"] = join_name(item.pop("namespace"), str(item.get("name") or ""))
            changed = True
    return mapping, changed


def restore_item(item: Any, mapping: dict[str, tuple[str, str]]) -> bool:
    if isinstance(item, dict) and item.get("type") == "function_call" and item.get("name") in mapping:
        item["namespace"], item["name"] = mapping[item["name"]]
        return True
    return False


def restore_event(data: Any, mapping: dict[str, tuple[str, str]]) -> bool:
    """Map flattened names back in one Responses stream event (or full response object)."""
    if not mapping or not isinstance(data, dict):
        return False
    hit = restore_item(data.get("item"), mapping)
    for holder in (data, data.get("response")):
        if isinstance(holder, dict) and isinstance(holder.get("output"), list):
            for item in holder["output"]:
                hit |= restore_item(item, mapping)
    return hit


class SseRewriter:
    """Streams SSE bytes through, rewriting events that mention a flattened tool name."""

    def __init__(self, mapping: dict[str, tuple[str, str]]):
        self.mapping = mapping
        self.needles = [n.encode() for n in mapping]
        self.buf = b""

    def feed(self, chunk: bytes) -> bytes:
        if not self.mapping:
            return chunk
        self.buf += chunk
        *events, self.buf = self.buf.split(b"\n\n")
        return b"".join(self._fix(ev) + b"\n\n" for ev in events)

    def flush(self) -> bytes:
        rest, self.buf = self.buf, b""
        return self._fix(rest) if rest else b""

    def _fix(self, ev: bytes) -> bytes:
        if not any(n in ev for n in self.needles):
            return ev
        lines = ev.split(b"\n")
        for i, line in enumerate(lines):
            if line.startswith(b"data:"):
                try:
                    data = json.loads(line[5:])
                except ValueError:
                    continue
                if restore_event(data, self.mapping):
                    lines[i] = b"data: " + json.dumps(data, ensure_ascii=False).encode()
        return b"\n".join(lines)


def self_test() -> None:
    body = {"tools": [{"type": "function", "name": "exec_command"},
                      {"type": "namespace", "name": "mcp__node_repl__",
                       "tools": [{"type": "function", "name": "js", "parameters": {"type": "object"}}]},
                      {"type": "namespace", "name": "mcp__gmail", "tools": [{"type": "function", "name": "send"}]}],
            "input": [{"type": "function_call", "namespace": "mcp__node_repl__", "name": "js", "call_id": "c"}]}
    mapping, _ = flatten_request(body)
    names = [t["name"] for t in body["tools"]]
    assert names == ["exec_command", "mcp__node_repl__js"], names
    assert body["input"][0]["name"] == "mcp__node_repl__js" and "namespace" not in body["input"][0]
    sse = SseRewriter(mapping)
    ev = b'event: x\ndata: {"item":{"type":"function_call","name":"mcp__node_repl__js"}}\n\n'
    out = sse.feed(ev[:20]) + sse.feed(ev[20:]) + sse.flush()
    assert b'"namespace": "mcp__node_repl__"' in out and b'"name": "js"' in out, out
