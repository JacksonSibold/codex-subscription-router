"""Relay-owned Claude account OAuth with PKCE and manual code entry.

The token set is stored through Relay's current-user credential store. It is kept
separate from Codex and Claude Code configuration; an existing OpenCode token is
only used by the adapter as an optional fallback for older installations.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import hashlib
import base64
import secrets
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

import credentials

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload user:plugins"
CREDENTIAL_NAME = "RELAY_ANTHROPIC_OAUTH"
USER_AGENT = "Relay/0.3 Claude OAuth"
FLOW_LIFETIME_SECONDS = 10 * 60
REFRESH_BUFFER_MS = 5 * 60 * 1000
_lock = threading.Lock()


@dataclass(frozen=True)
class PendingFlow:
    verifier: str
    state: str
    created_at: float

    @property
    def expires_at(self) -> float:
        return self.created_at + FLOW_LIFETIME_SECONDS

    def expired(self) -> bool:
        return time.time() >= self.expires_at


def start() -> tuple[PendingFlow, str]:
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urllib.parse.urlencode({
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    return PendingFlow(verifier, state, time.time()), AUTHORIZE_URL + "?" + query


def _request_token(payload: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            document = json.load(response)
    except urllib.error.HTTPError as exc:
        # Provider error bodies can repeat request material. Keep only the status.
        raise RuntimeError(f"Claude token request was rejected with HTTP {exc.code}") from None
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Claude token request failed: {type(exc).__name__}") from None
    if not isinstance(document, dict):
        raise RuntimeError("Claude token endpoint returned an invalid response")
    return document


def _parse_code(value: str, expected_state: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        raise ValueError("Paste the authorization code copied from Claude")
    pasted = value.strip()
    code, separator, state = pasted.partition("#")
    code = code.strip()
    state = state.strip() if separator else expected_state
    if not code:
        raise ValueError("The authorization code is empty")
    if not secrets.compare_digest(state, expected_state):
        raise ValueError("The authorization state does not match. Start the sign-in again.")
    return code, state


def _token_document(data: dict[str, Any], previous_refresh: str | None = None) -> dict[str, Any]:
    access = data.get("access_token")
    refresh = data.get("refresh_token") or previous_refresh
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        raise RuntimeError("Claude returned an incomplete token set")
    lifetime = data.get("expires_in")
    lifetime = int(lifetime) if isinstance(lifetime, (int, float)) and lifetime > 0 else 3600
    refresh_lifetime = data.get("refresh_token_expires_in")
    now = int(time.time() * 1000)
    document: dict[str, Any] = {
        "access": access,
        "refresh": refresh,
        "expires": now + lifetime * 1000,
        "token_type": str(data.get("token_type") or "Bearer")[:40],
        "scope": str(data.get("scope") or SCOPES)[:1000],
    }
    if isinstance(refresh_lifetime, (int, float)) and refresh_lifetime > 0:
        document["refresh_expires"] = now + int(refresh_lifetime) * 1000
    return document


def save_tokens(document: dict[str, Any]) -> None:
    credentials.set_secret(CREDENTIAL_NAME, json.dumps(document, ensure_ascii=False, separators=(",", ":")))


def load_tokens() -> dict[str, Any] | None:
    value = credentials.get_secret(CREDENTIAL_NAME)
    if not value:
        return None
    try:
        document = json.loads(value)
    except ValueError:
        return None
    if not isinstance(document, dict) or not isinstance(document.get("access"), str) or not isinstance(document.get("refresh"), str):
        return None
    return document


def complete(flow: PendingFlow, pasted: str) -> dict[str, Any]:
    if flow.expired():
        raise ValueError("This Claude sign-in expired. Start it again.")
    code, state = _parse_code(pasted, flow.state)
    data = _request_token({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": flow.verifier,
        "state": state,
    })
    tokens = _token_document(data)
    save_tokens(tokens)
    return {"connected": True, "expires": tokens["expires"], "scope": tokens.get("scope", "")}


def refresh(document: dict[str, Any]) -> dict[str, Any]:
    data = _request_token({
        "grant_type": "refresh_token",
        "refresh_token": document["refresh"],
        "client_id": CLIENT_ID,
        "scope": SCOPES,
    })
    tokens = _token_document(data, previous_refresh=document["refresh"])
    save_tokens(tokens)
    return tokens


def access_token(log: Callable[[str], None]) -> str:
    with _lock:
        document = load_tokens()
        if not document:
            raise RuntimeError("Claude is not connected through Relay OAuth")
        expires = document.get("expires")
        if isinstance(expires, (int, float)) and expires > time.time() * 1000 + REFRESH_BUFFER_MS:
            return document["access"]
        log("Claude Relay OAuth credential refreshed")
        return str(refresh(document)["access"])


def credential_status() -> dict[str, Any] | None:
    document = load_tokens()
    if not document:
        return None
    expires = document.get("expires")
    expired = isinstance(expires, (int, float)) and expires <= time.time() * 1000
    return {"status": "credential_found", "expired": expired, "expires": expires}