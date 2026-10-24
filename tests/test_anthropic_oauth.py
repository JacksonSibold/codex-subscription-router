from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import anthropic_oauth
import manager


class AnthropicOAuthTests(unittest.TestCase):
    def test_pkce_authorization_url_and_code_exchange(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "CODEX_ROUTER_CREDENTIALS": str(Path(directory) / "credentials.json"),
            anthropic_oauth.CREDENTIAL_NAME: ""
        }):
            flow, url = anthropic_oauth.start()
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual(query["code_challenge_method"], ["S256"])
            expected = base64.urlsafe_b64encode(hashlib.sha256(flow.verifier.encode()).digest()).rstrip(b"=").decode()
            self.assertEqual(query["code_challenge"], [expected])
            self.assertEqual(query["state"], [flow.state])
            self.assertNotIn(flow.verifier, url)
            token_response = {
                "access_token": "test-access-value", "refresh_token": "test-refresh-value",
                "expires_in": 3600, "token_type": "Bearer", "scope": anthropic_oauth.SCOPES,
            }
            with patch.object(anthropic_oauth, "_request_token", return_value=token_response) as request:
                result = anthropic_oauth.complete(flow, "test-code#" + flow.state)
            self.assertTrue(result["connected"])
            sent = request.call_args.args[0]
            self.assertEqual(sent["grant_type"], "authorization_code")
            self.assertEqual(sent["code"], "test-code")
            self.assertEqual(sent["code_verifier"], flow.verifier)
            stored = anthropic_oauth.load_tokens()
            self.assertEqual(stored["access"], "test-access-value")
            self.assertEqual(stored["refresh"], "test-refresh-value")

    def test_state_mismatch_does_not_exchange_or_store_tokens(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "CODEX_ROUTER_CREDENTIALS": str(Path(directory) / "credentials.json"),
            anthropic_oauth.CREDENTIAL_NAME: ""
        }):
            flow, _ = anthropic_oauth.start()
            with patch.object(anthropic_oauth, "_request_token") as request:
                with self.assertRaisesRegex(ValueError, "state"):
                    anthropic_oauth.complete(flow, "test-code#wrong-state")
            request.assert_not_called()
            self.assertIsNone(anthropic_oauth.load_tokens())

    def test_refresh_rotates_access_and_keeps_refresh_when_omitted(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "CODEX_ROUTER_CREDENTIALS": str(Path(directory) / "credentials.json"),
            anthropic_oauth.CREDENTIAL_NAME: ""
        }):
            anthropic_oauth.save_tokens({
                "access": "expired-access", "refresh": "keep-refresh",
                "expires": int(time.time() * 1000) - 1000,
            })
            with patch.object(anthropic_oauth, "_request_token", return_value={
                "access_token": "fresh-access", "expires_in": 3600, "token_type": "Bearer"
            }):
                token = anthropic_oauth.access_token(lambda message: None)
            self.assertEqual(token, "fresh-access")
            stored = anthropic_oauth.load_tokens()
            self.assertEqual(stored["refresh"], "keep-refresh")

    def test_manager_keeps_pending_flow_only_in_memory(self):
        manager.OAUTH_FLOWS.clear()
        flow = anthropic_oauth.PendingFlow("verifier", "state-value", time.time())
        url = anthropic_oauth.AUTHORIZE_URL + "?state=state-value"
        with patch.object(anthropic_oauth, "start", return_value=(flow, url)), \
             patch.object(manager.webbrowser, "open") as opened:
            result = manager.start_claude_oauth()
        self.assertEqual(result["auth_url"], url)
        self.assertIn(flow.state, manager.OAUTH_FLOWS)
        self.assertNotIn("verifier", json.dumps(result))
        opened.assert_called_once_with(url)
        with patch.object(anthropic_oauth, "complete", return_value={"connected": True}):
            self.assertTrue(manager.complete_claude_oauth("code#" + flow.state)["connected"])
        self.assertNotIn(flow.state, manager.OAUTH_FLOWS)


if __name__ == "__main__":
    unittest.main()