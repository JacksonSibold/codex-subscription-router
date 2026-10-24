"""Credential-free local usage ledger for every Relay model route."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalized_usage(usage: Any) -> dict[str, int]:
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _int(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = _int(usage.get("output_tokens") or usage.get("completion_tokens"))
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    out_details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
    cached = _int(details.get("cached_tokens") if isinstance(details, dict) else 0)
    cached += _int(usage.get("cache_read_input_tokens"))
    reasoning = _int(out_details.get("reasoning_tokens") if isinstance(out_details, dict) else 0)
    total = _int(usage.get("total_tokens")) or input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }


def _connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            provider TEXT NOT NULL,
            account TEXT NOT NULL,
            model TEXT NOT NULL,
            status INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            cached_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            reasoning_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS usage_events_created ON usage_events(created_at)")
    return connection


def record(path: Path, provider: str, account: str, model: str, status: int, usage: Any) -> None:
    path = Path(path)
    values = normalized_usage(usage)
    with closing(_connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO usage_events(created_at,provider,account,model,status,input_tokens,cached_tokens,output_tokens,reasoning_tokens,total_tokens) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), provider, account, model, int(status), values["input_tokens"],
             values["cached_tokens"], values["output_tokens"], values["reasoning_tokens"], values["total_tokens"]),
        )


def _empty_totals() -> dict[str, int]:
    return {"requests": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}


def dashboard(path: Path, days: int = 30) -> dict[str, Any]:
    path = Path(path)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result: dict[str, Any] = {
        "available": False,
        "days": days,
        "since": since,
        "totals": _empty_totals(),
        "providers": [],
        "models": [],
        "daily": [],
        "recent": [],
    }
    if not path.exists():
        return result
    try:
        with closing(_connect(path)) as connection:
            connection.row_factory = sqlite3.Row
            total = connection.execute("""
                SELECT COUNT(*) requests, COALESCE(SUM(input_tokens),0) input_tokens,
                       COALESCE(SUM(cached_tokens),0) cached_tokens, COALESCE(SUM(output_tokens),0) output_tokens,
                       COALESCE(SUM(reasoning_tokens),0) reasoning_tokens, COALESCE(SUM(total_tokens),0) total_tokens
                FROM usage_events WHERE created_at >= ?
            """, (since,)).fetchone()
            result["totals"] = dict(total)
            result["providers"] = [dict(row) for row in connection.execute("""
                SELECT provider, account, COUNT(*) requests, COALESCE(SUM(total_tokens),0) total_tokens,
                       COALESCE(SUM(input_tokens),0) input_tokens, COALESCE(SUM(output_tokens),0) output_tokens,
                       MAX(created_at) last_used
                FROM usage_events WHERE created_at >= ?
                GROUP BY provider, account ORDER BY total_tokens DESC, requests DESC
            """, (since,))]
            result["models"] = [dict(row) for row in connection.execute("""
                SELECT provider, model, COUNT(*) requests, COALESCE(SUM(total_tokens),0) total_tokens,
                       COALESCE(SUM(input_tokens),0) input_tokens, COALESCE(SUM(output_tokens),0) output_tokens,
                       MAX(created_at) last_used
                FROM usage_events WHERE created_at >= ?
                GROUP BY provider, model ORDER BY total_tokens DESC, requests DESC LIMIT 50
            """, (since,))]
            result["daily"] = [dict(row) for row in connection.execute("""
                SELECT substr(created_at,1,10) day, COUNT(*) requests, COALESCE(SUM(total_tokens),0) total_tokens
                FROM usage_events WHERE created_at >= ?
                GROUP BY substr(created_at,1,10) ORDER BY day
            """, (since,))]
            result["recent"] = [dict(row) for row in connection.execute("""
                SELECT created_at, provider, account, model, status, total_tokens
                FROM usage_events WHERE created_at >= ? ORDER BY id DESC LIMIT 40
            """, (since,))]
            result["available"] = True
    except sqlite3.Error:
        return result
    return result
