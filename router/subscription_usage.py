"""Read provider-reported subscription allowances without persisting secrets.

Relay only returns non-secret plan names, percentages, and reset times. Provider
credentials are read for the duration of a request, never logged, and never
forwarded across a redirect.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
import urllib.error
import urllib.request

import anthropic_oauth
import credentials

TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 1_000_000
OPENAI_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
ANTHROPIC_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
KIMI_DEFAULT_BASE_URL = "https://api.kimi.ai/coding/v1"
USER_AGENT = "Relay/0.3 subscription-usage"


class UsageRequestError(RuntimeError):
    """A sanitized provider usage failure."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        if status == 401:
            raise UsageRequestError("Credential was rejected; reconnect this account.", status) from None
        if status == 403:
            raise UsageRequestError("This account cannot read provider usage.", status) from None
        if status == 404:
            raise UsageRequestError("Provider usage endpoint is not available for this account.", status) from None
        raise UsageRequestError(f"Provider usage request failed with HTTP {status}.", status) from None
    except (OSError, ValueError) as exc:
        raise UsageRequestError(f"Provider usage request failed: {type(exc).__name__}.") from None
    if len(payload) > MAX_RESPONSE_BYTES:
        raise UsageRequestError("Provider usage response was too large.")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, ValueError):
        raise UsageRequestError("Provider usage response was not valid JSON.") from None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _percent(value: Any, *, ratio: bool = False) -> float | None:
    number = _number(value)
    if number is None:
        return None
    if ratio:
        number *= 100
    return round(min(100.0, max(0.0, number)), 1)


def _iso_time(value: Any, *, relative_seconds: Any = None) -> str | None:
    number = _number(value)
    if number is not None:
        seconds = number / 1000 if number > 10_000_000_000 else number
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        return value.strip()[:80]
    relative = _number(relative_seconds)
    if relative is not None and relative >= 0:
        return datetime.fromtimestamp(time.time() + relative, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def _duration_label(seconds: Any, fallback: str) -> str:
    value = _number(seconds)
    if value is None or value <= 0:
        return fallback
    minutes = round(value / 60)
    if minutes in (300, 18000 // 60):
        return "5-hour limit"
    if minutes in (10_080, 604_800 // 60):
        return "Weekly limit"
    if minutes >= 40_320 and minutes % 43_200 <= 60:
        return "30-day limit"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}-day limit"
    if minutes % 60 == 0:
        return f"{minutes // 60}-hour limit"
    return f"{minutes}-minute limit"


def _window(label: str, used_percent: Any, resets_at: Any = None, *, ratio: bool = False,
            relative_seconds: Any = None, duration_seconds: Any = None) -> dict[str, Any] | None:
    percent = _percent(used_percent, ratio=ratio)
    if percent is None:
        return None
    return {
        "label": label,
        "used_percent": percent,
        "remaining_percent": round(100.0 - percent, 1),
        "resets_at": _iso_time(resets_at, relative_seconds=relative_seconds),
        "duration_seconds": int(_number(duration_seconds) or 0) or None,
    }


def _provider(provider: str, account: str, status: str, *, plan: str | None = None,
              windows: list[dict[str, Any]] | None = None, detail: str | None = None) -> dict[str, Any]:
    return {
        "provider": provider,
        "account": account,
        "status": status,
        "plan": plan,
        "windows": windows or [],
        "detail": detail,
    }


def _openai_auth(codex_home: Path) -> tuple[str, str | None] | None:
    try:
        with (Path(codex_home) / "auth.json").open(encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return None
    tokens = document.get("tokens") if isinstance(document, dict) else None
    if not isinstance(tokens, dict):
        return None
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        return None
    account_id = tokens.get("account_id")
    return access, account_id if isinstance(account_id, str) and account_id else None


def _codex_windows(bucket: Any, prefix: str = "") -> list[dict[str, Any]]:
    if not isinstance(bucket, dict):
        return []
    result: list[dict[str, Any]] = []
    for key, fallback in (("primary", "Primary limit"), ("primary_window", "Primary limit"),
                          ("secondary", "Secondary limit"), ("secondary_window", "Secondary limit")):
        entry = bucket.get(key)
        if not isinstance(entry, dict):
            continue
        duration = entry.get("limit_window_seconds") or entry.get("window_duration_mins")
        if entry.get("limit_window_seconds") is not None:
            duration = _number(entry.get("limit_window_seconds"))
        elif entry.get("window_duration_mins") is not None:
            minutes = _number(entry.get("window_duration_mins"))
            duration = minutes * 60 if minutes is not None else None
        label = prefix + _duration_label(duration, fallback)
        item = _window(label, entry.get("used_percent"), entry.get("reset_at") or entry.get("resets_at"),
                       relative_seconds=entry.get("reset_after_seconds"), duration_seconds=duration)
        if item:
            result.append(item)
    return result


def _parse_openai(payload: Any) -> tuple[str | None, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return None, []
    plan = payload.get("plan_type") if isinstance(payload.get("plan_type"), str) else None
    windows = _codex_windows(payload.get("rate_limit"))
    by_id = payload.get("rate_limits_by_limit_id")
    if isinstance(by_id, dict):
        for name, bucket in by_id.items():
            windows.extend(_codex_windows(bucket, f"{name} · " if isinstance(name, str) else ""))
    additional = payload.get("additional_rate_limits")
    if isinstance(additional, list):
        for entry in additional:
            if not isinstance(entry, dict):
                continue
            label = entry.get("limit_name") or entry.get("limit_id") or entry.get("name") or "Additional"
            windows.extend(_codex_windows(entry.get("rate_limit") or entry, f"{label} · "))
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in windows:
        key = (item["label"], item["used_percent"], item["resets_at"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return plan, unique


def _collect_openai(codex_home: Path) -> dict[str, Any]:
    auth = _openai_auth(codex_home)
    if not auth:
        return _provider("openai", "Codex sign-in", "not_connected",
                         detail="Codex sign-in was not found in a readable auth store.")
    token, account_id = auth
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": USER_AGENT}
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    try:
        payload = _get_json(os.environ.get("RELAY_OPENAI_USAGE_URL") or OPENAI_USAGE_URL, headers)
    except UsageRequestError as exc:
        return _provider("openai", "Codex sign-in", "error", detail=str(exc))
    plan, windows = _parse_openai(payload)
    if not windows:
        return _provider("openai", "Codex sign-in", "unavailable", plan=plan,
                         detail="Codex returned no subscription allowance windows.")
    return _provider("openai", "Codex sign-in", "available", plan=plan, windows=windows)


def _parse_anthropic(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    result: list[dict[str, Any]] = []
    labels = (
        ("five_hour", "5-hour limit"),
        ("seven_day", "Weekly limit"),
        ("seven_day_oauth_apps", "Weekly · OAuth apps"),
        ("seven_day_opus", "Weekly · Opus"),
        ("seven_day_sonnet", "Weekly · Sonnet"),
    )
    for key, label in labels:
        entry = payload.get(key)
        if not isinstance(entry, dict):
            continue
        item = _window(label, entry.get("utilization"), entry.get("resets_at"))
        if item:
            result.append(item)
    extra = payload.get("extra_usage")
    if isinstance(extra, dict):
        used_percent = extra.get("utilization")
        used_credits = _number(extra.get("used_credits"))
        monthly_limit = _number(extra.get("monthly_limit"))
        if used_credits is not None and monthly_limit and monthly_limit > 0:
            used_percent = used_credits / monthly_limit * 100
        item = _window("Extra usage", used_percent, extra.get("resets_at"))
        if item:
            result.append(item)
    return result


def _collect_anthropic() -> dict[str, Any]:
    try:
        token = anthropic_oauth.access_token(lambda _message: None)
    except RuntimeError:
        return _provider("anthropic", "Relay Claude OAuth", "not_connected",
                         detail="Claude is not connected through Relay OAuth.")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "claude-cli/2.1.296 (external, sdk-cli)",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
    }
    try:
        payload = _get_json(os.environ.get("RELAY_ANTHROPIC_USAGE_URL") or ANTHROPIC_USAGE_URL, headers)
    except UsageRequestError as exc:
        return _provider("anthropic", "Relay Claude OAuth", "error", detail=str(exc))
    windows = _parse_anthropic(payload)
    if not windows:
        return _provider("anthropic", "Relay Claude OAuth", "unavailable",
                         detail="Claude returned no subscription allowance windows.")
    return _provider("anthropic", "Relay Claude OAuth", "available", windows=windows)


def _parse_kimi(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    result: list[dict[str, Any]] = []
    usages = payload.get("usages")
    if isinstance(usages, dict):
        for key, label in (("limit_5h", "5-hour limit"), ("limit_7d", "Weekly limit"),
                           ("limit_month_total", "Monthly limit"), ("limit_month_code", "Monthly · Kimi Code")):
            entry = usages.get(key)
            if not isinstance(entry, dict):
                continue
            item = _window(label, entry.get("used_ratio"), entry.get("reset_time"), ratio=True)
            if item:
                result.append(item)
    usage = payload.get("usage")
    if isinstance(usage, dict):
        used = _number(usage.get("used"))
        limit = _number(usage.get("limit"))
        if used is not None and limit and limit > 0:
            item = _window(str(usage.get("name") or "Weekly limit"), used / limit * 100,
                           usage.get("reset_at") or usage.get("reset_time"), ratio=False)
            if item:
                result.append(item)
    limits = payload.get("limits")
    if isinstance(limits, list):
        for index, raw in enumerate(limits):
            if not isinstance(raw, dict):
                continue
            detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else raw
            used = _number(detail.get("used"))
            limit = _number(detail.get("limit"))
            remaining = _number(detail.get("remaining"))
            if used is None and remaining is not None and limit is not None:
                used = limit - remaining
            if used is None or not limit or limit <= 0:
                continue
            item = _window(str(detail.get("name") or raw.get("name") or raw.get("title") or f"Limit {index + 1}"),
                           used / limit * 100, detail.get("reset_at") or detail.get("reset_time"))
            if item:
                result.append(item)
    return result


def _collect_kimi() -> dict[str, Any]:
    token = credentials.get_secret("KIMI_API_KEY")
    if not token:
        return _provider("kimi", "Kimi Code API key", "not_connected",
                         detail="Kimi Code is not connected.")
    base = (os.environ.get("KIMI_CODE_BASE_URL") or KIMI_DEFAULT_BASE_URL).rstrip("/")
    url = os.environ.get("RELAY_KIMI_USAGE_URL") or f"{base}/usages"
    try:
        payload = _get_json(url, {"Authorization": f"Bearer {token}", "Accept": "application/json"})
    except UsageRequestError as exc:
        return _provider("kimi", "Kimi Code API key", "error", detail=str(exc))
    windows = _parse_kimi(payload)
    if not windows:
        return _provider("kimi", "Kimi Code API key", "unavailable",
                         detail="Kimi returned no subscription allowance windows for this key.")
    return _provider("kimi", "Kimi Code API key", "available", windows=windows)


def _static_unavailable(provider: str, account: str, detail: str, credential_name: str | None = None) -> dict[str, Any]:
    if credential_name and not credentials.get_secret(credential_name):
        return _provider(provider, account, "not_connected", detail=f"{account} is not connected.")
    return _provider(provider, account, "unavailable", detail=detail)


def collect(codex_home: str | os.PathLike[str]) -> dict[str, Any]:
    """Collect all provider plan snapshots concurrently using non-secret outputs."""
    home = Path(codex_home)
    tasks: dict[str, Callable[[], dict[str, Any]]] = {
        "openai": lambda: _collect_openai(home),
        "anthropic": _collect_anthropic,
        "kimi": _collect_kimi,
        "opencode": lambda: _static_unavailable(
            "opencode", "OpenCode API key", "OpenCode does not expose subscription allowance through Relay.",
            "OPENCODE_API_KEY"),
        "local": lambda: _provider("local", "Local endpoints", "unavailable",
                                   detail="Local models have no subscription allowance; their routed tokens appear in the ledger."),
    }
    result: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="relay-usage") as pool:
        futures = {provider: pool.submit(task) for provider, task in tasks.items()}
        for provider, future in futures.items():
            try:
                result[provider] = future.result()
            except Exception as exc:
                result[provider] = _provider(provider, "Relay account", "error",
                                             detail=f"Usage lookup failed: {type(exc).__name__}.")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "providers": [result[name] for name in ("openai", "anthropic", "kimi", "opencode", "local")],
    }