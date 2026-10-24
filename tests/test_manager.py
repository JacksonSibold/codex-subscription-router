from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import tomllib
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import manager


class ManagerTests(unittest.TestCase):
    def test_production_ui_and_local_api_are_served_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            static = home / "dist"
            static.mkdir()
            (static / "index.html").write_text("<html><body>Relay UI</body></html>", encoding="utf-8")
            safe_providers = {key: {"status": "credential_found", "detail": "hidden"} for key in manager.PROVIDERS}
            with patch.object(manager, "STATIC_DIR", static), \
                 patch.object(manager, "SETTINGS_PATH", home / "settings.json"), \
                 patch.object(manager, "provider_state", return_value=safe_providers), \
                 patch.object(manager, "router_health", return_value={"reachable": False}), \
                 patch.object(manager.router, "CODEX_HOME", str(home)):
                server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base = f"http://127.0.0.1:{server.server_port}"
                    with urllib.request.urlopen(base + "/") as response:
                        self.assertIn("Relay UI", response.read().decode())
                    with urllib.request.urlopen(base + "/api/state") as response:
                        state = json.load(response)
                    serialized = json.dumps(state)
                    self.assertNotIn("refresh", serialized.lower())
                    self.assertNotIn("access_token", serialized.lower())
                    self.assertEqual(len(state["settings"]["models"]), 11)
                    request = urllib.request.Request(base + "/api/settings", data=b"{}", method="POST")
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request)
                    self.assertEqual(caught.exception.code, 400)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()

    def test_development_provider_state_uses_isolated_stores(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text("{}", encoding="utf-8")
            opencode_auth = home / "opencode-auth.json"
            opencode_auth.write_text('{"anthropic": {"access": "hidden"}}', encoding="utf-8")
            with patch.object(manager.router, "CODEX_HOME", str(home)), \
                 patch.object(manager, "OPENCODE_AUTH_PATH", opencode_auth), \
                 patch.dict(os.environ, {"CODEX_ROUTER_DEV": "1"}), \
                 patch.object(manager, "_user_env") as user_env:
                providers = manager.provider_state()
            user_env.assert_not_called()
            self.assertEqual(providers["openai"]["status"], "credential_found")
            self.assertEqual(providers["anthropic"]["status"], "credential_found")
            self.assertEqual(providers["opencode"]["status"], "not_configured")
            self.assertEqual(providers["kimi"]["status"], "not_configured")

    def _post_apply(self, home: Path, document: dict) -> dict:
        with patch.object(manager, "SETTINGS_PATH", home / "router-settings.json"), \
             patch.object(manager.router, "CODEX_HOME", str(home)), \
             patch.object(manager.urllib.request, "urlopen", side_effect=manager.urllib.error.URLError("offline")):
            server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                payload = json.dumps({"settings": document})
                connection.request("POST", "/api/apply", body=payload, headers={
                    "Content-Type": "application/json", "X-Router-Manager": "1",
                })
                response = connection.getresponse()
                result = json.load(response)
                self.assertEqual(response.status, 200)
                connection.close()
                return result
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_live_apply_updates_only_codex_default_and_reconnects_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / "config.toml"
            config.write_text('model = "old"\nmodel_reasoning_effort = "low"\n\n[projects."example"]\ntrust_level = "trusted"\n', encoding="utf-8")
            document = manager.settings.default_settings()
            document["runtime"]["default_model"] = "k3.1-pro"
            with patch.dict(os.environ, {"CODEX_ROUTER_DEV": ""}):
                result = self._post_apply(home, document)
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertTrue(result["codex_default_updated"])
            self.assertFalse(result["router_reloaded"])
            self.assertEqual(parsed["model"], "k3.1-pro")
            self.assertEqual(parsed["model_reasoning_effort"], "max")
            self.assertEqual(parsed["projects"]["example"]["trust_level"], "trusted")
            self.assertTrue((home / "mixed-models.json").is_file())

    def test_development_apply_never_changes_codex_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / "config.toml"
            original = 'model = "old"\nmodel_reasoning_effort = "low"\n'
            config.write_text(original, encoding="utf-8")
            document = manager.settings.default_settings()
            document["runtime"]["default_model"] = "k3.1-pro"
            with patch.dict(os.environ, {"CODEX_ROUTER_DEV": "1"}):
                result = self._post_apply(home, document)
            self.assertFalse(result["codex_default_updated"])
            self.assertFalse(result["router_reloaded"])
            self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_diagnostic_redaction_hides_credential_shaped_values(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "router.log").write_text('Authorization: Bearer example-value\napi_key=another-example\n', encoding="utf-8")
            with patch.object(manager, "HERE", home):
                lines = manager.redacted_log()
            self.assertNotIn("example-value", "\n".join(lines))
            self.assertNotIn("another-example", "\n".join(lines))
            self.assertIn("[hidden]", lines[0])


if __name__ == "__main__":
    unittest.main()
