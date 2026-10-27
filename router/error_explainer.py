"""Turn provider failures into stable, actionable Relay diagnostics."""
from __future__ import annotations

import json
import re
from typing import Any

PROVIDER_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Claude",
    "kimi": "Kimi Code",
    "opencode": "OpenCode Go",
    "local": "the local model endpoint",
}

_SECRET = re.compile(
    r"(?i)(bearer\s+|api[_-]?key[=: ]+|access[_-]?token[=: ]+|refresh[_-]?token[=: ]+)"
    r"[^\s,;\"'}]+"
)
_MODEL = re.compile(
    r"(?i)\b((?:gpt|claude|kimi|k[0-9]|gemini|grok|deepseek|glm|qwen|minimax|muse|codex)"
    r"[a-z0-9._:/-]{1,160})\b"
)


def _provider_name(lane: str) -> str:
    return PROVIDER_NAMES.get(lane, lane or "provider")


def _text_from_document(value: Any) -> str:
    """Extract a useful provider message without serializing unrelated fields."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    for key in ("message", "detail", "error_description", "reason"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    for key in ("error", "errors", "response"):
        candidate = value.get(key)
        if isinstance(candidate, (dict, str)):
            message = _text_from_document(candidate)
            if message:
                return message
    return ""


def provider_detail(body: bytes | str, limit: int = 600) -> str:
    """Return a bounded, credential-free explanation from an upstream response."""
    if isinstance(body, bytes):
        text = body[:200_000].decode("utf-8", errors="replace")
    else:
        text = body[:200_000]
    text = text.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    detail = _text_from_document(parsed) if parsed is not None else text
    if not detail:
        detail = text
    detail = " ".join(detail.replace("\x00", "").split())
    detail = _SECRET.sub(lambda match: match.group(1) + "[hidden]", detail)
    return detail[:limit]


def explain(lane: str, status: int | None, body: bytes | str = "") -> dict[str, Any]:
    """Classify an upstream failure into a message that names the next action."""
    provider = _provider_name(lane)
    detail = provider_detail(body)
    lowered = detail.lower()
    code = "provider_error"
    action = "Check Diagnostics, then retry. If it repeats, verify the provider connection."

    if status in (401, 403):
        code = "authentication"
        action = f"Reconnect {provider} in Relay Connections, then start a new Codex conversation."
        summary = f"{provider} rejected the saved sign-in or subscription access."
    elif status == 404 or any(marker in lowered for marker in (
        "model not found", "unknown model", "does not exist", "not available", "no such model",
    )):
        code = "model_unavailable"
        match = _MODEL.search(detail)
        model_hint = f" ({match.group(1)})" if match else ""
        action = (
            f"Edit this route's Upstream model ID{model_hint}, or refresh the model catalog. "
            "The provider may have renamed or retired that model."
        )
        summary = f"{provider} does not recognize this model."
    elif status == 429 or any(marker in lowered for marker in (
        "rate limit", "too many requests", "quota", "usage limit", "insufficient_quota",
    )):
        code = "rate_or_usage_limit"
        action = f"Wait for the {provider} allowance to reset, switch to another route, or review Usage in Relay."
        summary = f"{provider} is rate-limited or the account allowance is exhausted."
    elif any(marker in lowered for marker in (
        "context length", "context window", "too many tokens", "maximum context",
    )):
        code = "context_limit"
        action = "Compact or shorten the conversation, or switch to a route with a larger context window."
        summary = f"The conversation is larger than {provider} accepts for this model."
    elif any(marker in lowered for marker in (
        "unsupported tool", "unknown tool", "tool call", "function calling", "tool_choice",
    )):
        code = "tool_incompatible"
        action = (
            "Turn off unsupported tools for this route in Model picker, or choose a model "
            "with matching tool support."
        )
        summary = f"{provider} rejected a tool format used by this conversation."
    elif status is not None and status >= 500:
        code = "provider_unavailable"
        action = f"Retry in a moment. If every retry fails, check whether {provider} is reporting an outage."
        summary = f"{provider} is temporarily unavailable."
    elif status == 400:
        code = "request_rejected"
        action = "Check the provider detail below, then adjust the selected model, reasoning level, or tools."
        summary = f"{provider} rejected the request."
    else:
        summary = f"{provider} returned an unexpected error."

    message = f"Relay: {summary} {action}"
    if detail and detail.lower() not in summary.lower():
        message += f" Provider detail: {detail}"
    return {
        "message": message,
        "type": "relay_provider_error",
        "code": code,
        "provider": lane,
        "status": status,
        "action": action,
        "detail": detail,
    }
