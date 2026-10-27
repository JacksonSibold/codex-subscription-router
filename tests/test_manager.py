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
import usage_store


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
                    self.assertNotIn("refresh_token", serialized.lower())
                    self.assertNotIn("access_token", serialized.lower())
                    self.assertEqual(len(state["settings"]["models"]), 11)
                    self.assertEqual(state["version"], manager.version.__version__)
                    self.assertGreaterEqual(len(state["usage"]["accounts"]), 5)
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
                 patch.dict(os.environ, {"CODEX_ROUTER_DEV": "1", "OPENCODE_AUTH_PATH": str(opencode_auth)}), \
                 patch.object(manager, "_user_env") as user_env:
                providers = manager.provider_state()
            user_env.assert_not_called()
            self.assertEqual(providers["openai"]["status"], "credential_found")
            self.assertEqual(providers["anthropic"]["status"], "credential_found")
            self.assertEqual(providers["opencode"]["status"], "not_configured")
            self.assertEqual(providers["kimi"]["status"], "not_configured")

    def test_development_credentials_are_read_only_from_the_isolated_override(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            credential_file = home / "credentials.json"
            credential_file.write_text('{"KIMI_API_KEY": "isolated-test-value"}', encoding="utf-8")
            with patch.object(manager.router, "CODEX_HOME", str(home)), \
                 patch.object(manager, "OPENCODE_AUTH_PATH", home / "opencode-auth.json"), \
                 patch.dict(os.environ, {"CODEX_ROUTER_DEV": "1", "CODEX_ROUTER_CREDENTIALS": str(credential_file)}), \
                 patch.object(manager.anthropic_oauth, "credential_status", return_value=None):
                providers = manager.provider_state()
            self.assertEqual(providers["kimi"]["status"], "credential_found")
            self.assertEqual(providers["opencode"]["status"], "not_configured")

    def test_usage_api_aggregates_all_provider_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = home / "usage.sqlite"
            usage_store.record(database, "anthropic", "Claude Relay OAuth", "claude-opus-5-5", 200,
                               {"input_tokens": 10, "output_tokens": 5})
            usage_store.record(database, "local", "Local · 127.0.0.1:11434", "local-llama", 200,
                               {"input_tokens": 7, "output_tokens": 3})
            providers = {
                "openai": {"status": "credential_found", "detail": "hidden"},
                "anthropic": {"status": "credential_found", "detail": "hidden"},
                "kimi": {"status": "not_configured", "detail": "hidden"},
                "opencode": {"status": "not_configured", "detail": "hidden"},
                "local": {"status": "ready", "detail": "hidden"},
            }
            with patch.dict(os.environ, {"CODEX_ROUTER_USAGE_DB": str(database)}), \
                 patch.object(manager, "provider_state", return_value=providers), \
                 patch.object(manager, "SETTINGS_PATH", home / "router-settings.json"):
                server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/usage?days=30") as response:
                        dashboard = json.load(response)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
            self.assertEqual(dashboard["totals"]["requests"], 2)
            self.assertEqual(dashboard["totals"]["total_tokens"], 25)
            self.assertEqual({row["provider"] for row in dashboard["providers"]}, {"anthropic", "local"})
            self.assertEqual(dashboard["connected_accounts"], 2)
            self.assertEqual({row["provider"] for row in dashboard["accounts"]}, {"openai", "anthropic", "kimi", "opencode", "local"})
            anthropic = next(row for row in dashboard["accounts"] if row["provider"] == "anthropic")
            self.assertEqual(anthropic["requests"], 1)
            self.assertFalse(anthropic["historical"])
            self.assertNotIn("test-access", json.dumps(dashboard))

    def test_usage_inventory_tracks_zero_usage_accounts_and_each_local_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            document = manager.settings.default_settings()
            for route_id, endpoint in (("local-one", "http://127.0.0.1:11434/v1"),
                                       ("local-two", "http://127.0.0.1:1234/v1")):
                route = manager.settings._model(route_id, "local", route_id, "medium", ["low", "medium", "high"])
                route["local"] = {"endpoint": endpoint, "protocol": "openai_chat", "credential_env": None}
                document["models"].append(route)
            settings_path = home / "router-settings.json"
            manager.settings.save(settings_path, document)
            database = home / "usage.sqlite"
            usage_store.record(database, "openai", manager.router.USAGE_ACCOUNT_LABELS["openai"], "gpt-test", 200,
                               {"input_tokens": 3, "output_tokens": 2})
            providers = {
                "openai": {"status": "credential_found", "detail": "Codex account"},
                "anthropic": {"status": "credential_found", "detail": "Claude OAuth"},
                "kimi": {"status": "credential_found", "detail": "Kimi key"},
                "opencode": {"status": "credential_found", "detail": "OpenCode key"},
                "local": {"status": "ready", "detail": "Two endpoints"},
            }
            with patch.object(manager, "SETTINGS_PATH", settings_path), \
                 patch.dict(os.environ, {"CODEX_ROUTER_USAGE_DB": str(database)}):
                dashboard = manager.usage_dashboard(30, providers)
            self.assertEqual(dashboard["connected_accounts"], 6)
            self.assertEqual(len(dashboard["accounts"]), 6)
            local_accounts = [row for row in dashboard["accounts"] if row["provider"] == "local"]
            self.assertEqual(len(local_accounts), 2)
            self.assertTrue(all(row["connected"] for row in local_accounts))
            codex = next(row for row in dashboard["accounts"]
                         if row["account"] == manager.router.USAGE_ACCOUNT_LABELS["openai"])
            self.assertEqual(codex["total_tokens"], 5)
            self.assertFalse(codex["historical"])
            self.assertTrue(all(row["total_tokens"] == 0 for row in dashboard["accounts"] if row is not codex))

    def test_subscription_usage_endpoint_is_sanitized_and_covers_all_lanes(self):
        snapshot = {
            "checked_at": "2030-01-01T00:00:00Z",
            "providers": [
                {"provider": provider, "account": "hidden account", "status": "unavailable",
                 "plan": None, "windows": [], "detail": "No allowance API."}
                for provider in manager.PROVIDERS
            ],
        }
        with patch.object(manager.subscription_usage, "collect", return_value=snapshot) as collect:
            server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/subscription-usage"
                ) as response:
                    result = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        collect.assert_called_once()
        self.assertEqual(len(result["providers"]), 5)
        self.assertNotIn("access_token", json.dumps(result).lower())
        self.assertNotIn("refresh", json.dumps(result).lower())

    def test_add_model_catalog_always_lists_openai_and_claude(self):
        with tempfile.TemporaryDirectory() as directory,              patch.object(manager.router, "CODEX_HOME", str(Path(directory))):
            models = manager.available_models()
        providers = {model["provider"] for model in models}
        self.assertIn("openai", providers)
        self.assertIn("anthropic", providers)
        self.assertIn("kimi", providers)
        self.assertEqual(len({(model["provider"], model["id"]) for model in models}), len(models))

    def test_codex_link_status_requires_the_exact_relay_provider_and_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            catalog = home / "mixed-models.json"
            catalog.write_text('{"models": []}', encoding="utf-8")
            config = home / "config.toml"

            def write_config(provider: str, base_url: str, catalog_path: Path) -> None:
                config.write_text(
                    f'model = "claude-opus-5-5"\nmodel_provider = "{provider}"\n'
                    f'model_catalog_json = {json.dumps(str(catalog_path))}\n\n'
                    f'[model_providers.mixed]\nbase_url = "{base_url}"\nwire_api = "responses"\n',
                    encoding="utf-8",
                )

            with patch.object(manager.router, "CODEX_HOME", str(home)), \
                 patch.object(manager.shutil, "which", return_value="codex"):
                write_config("mixed", "http://127.0.0.1:18765", catalog)
                self.assertTrue(manager.codex_link_status()["linked"])
                write_config("openai", "http://127.0.0.1:18765", catalog)
                self.assertFalse(manager.codex_link_status()["linked"])
                write_config("mixed", "http://127.0.0.1:19999", catalog)
                self.assertFalse(manager.codex_link_status()["linked"])
                write_config("mixed", "http://127.0.0.1:18765", home / "other-models.json")
                status = manager.codex_link_status()
                self.assertFalse(status["linked"])
                self.assertFalse(status["catalog_matches"])
                self.assertNotIn("access_token", json.dumps(status).lower())

    def test_codex_link_status_explains_a_replaced_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            catalog = home / "mixed-models.json"
            catalog.write_text('{"models": [{"slug": "gpt-6.1-sol"}]}', encoding="utf-8")
            (home / "config.toml").write_text(
                'model = "gpt-6.1-sol"\nmodel_provider = "openai"\n'
                f"model_catalog_json = {json.dumps(str(catalog))}\n",
                encoding="utf-8",
            )
            with patch.object(manager.router, "CODEX_HOME", str(home)), \
                 patch.object(manager.shutil, "which", return_value="codex"):
                status = manager.codex_link_status()
        self.assertFalse(status["linked"])
        self.assertIn("openai provider", status["reason"])
        self.assertIn("without resetting", status["action"])
        self.assertEqual(status["catalog_models"], 1)

    def test_route_health_surfaces_missing_credentials_and_unknown_models(self):
        document = manager.settings.default_settings()
        providers = {
            provider: {"status": "not_configured", "detail": "not connected"}
            for provider in manager.PROVIDERS
        }
        providers["openai"] = {"status": "unknown", "detail": "keyring only"}
        snapshot = {"providers": {
            "anthropic": {"models": [{"id": "claude-current", "name": "Claude Current"}]},
            "opencode": {"models": [{"id": "grok-4.7", "name": "Grok 4.7"}]},
        }}
        health = manager.route_health(document, providers, snapshot)
        self.assertEqual(health["status"], "error")
        self.assertTrue(any(error["code"] == "provider_not_connected" for error in health["errors"]))
        self.assertTrue(any(warning["code"] == "upstream_not_cataloged" for warning in health["warnings"]))

    def test_catalog_summary_counts_only_models_new_since_last_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            snapshot = {
                "checked_at": "2030-01-01T00:00:00Z",
                "providers": {
                    "openai": {
                        "models": [
                            {"id": "gpt-6.1-sol", "name": "GPT-6.1 Sol"},
                            {"id": "gpt-new", "name": "GPT New"},
                        ],
                        "new_models": [{"id": "gpt-new", "name": "GPT New"}],
                    },
                },
            }
            with patch.object(manager, "SETTINGS_PATH", home / "settings.json"), \
                 patch.object(manager.router, "CODEX_HOME", str(home)), \
                 patch.object(manager.provider_catalog, "cached_snapshot", return_value=snapshot):
                summary = manager.catalog_summary(snapshot)
        self.assertEqual(summary["new_count"], 1)
        self.assertEqual(summary["new_models"][0]["id"], "gpt-new")

    def test_link_codex_preserves_configuration_and_reports_router_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / "config.toml"
            config.write_text(
                'model = "old"\nmodel_provider = "existing"\n\n'
                '[model_providers.existing]\nbase_url = "http://127.0.0.1:9000"\n\n'
                '[projects."example"]\ntrust_level = "trusted"\n\n'
                '[[plugins]]\nname = "keep-this-plugin"\n',
                encoding="utf-8",
            )
            with patch.object(manager, "SETTINGS_PATH", home / "router-settings.json"), \
                 patch.object(manager.router, "CODEX_HOME", str(home)), \
                 patch.dict(os.environ, {"CODEX_ROUTER_DEV": ""}), \
                 patch.object(manager.urllib.request, "urlopen", side_effect=manager.urllib.error.URLError("offline")):
                result = manager.link_codex()
                status = manager.codex_link_status()
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertTrue(result["linked"])
            self.assertFalse(result["router_reloaded"])
            self.assertTrue(status["linked"])
            self.assertEqual(parsed["model_provider"], "mixed")
            self.assertEqual(parsed["model_providers"]["existing"]["base_url"], "http://127.0.0.1:9000")
            self.assertEqual(parsed["projects"]["example"]["trust_level"], "trusted")
            self.assertEqual(parsed["plugins"][0]["name"], "keep-this-plugin")
            self.assertTrue((home / "mixed-models.json").is_file())
            self.assertEqual(len(list(home.glob("config.toml.backup-*"))), 1)
            self.assertNotIn("access_token", json.dumps(result).lower())
            self.assertNotIn("refresh_token", json.dumps(result).lower())

    def test_link_codex_is_disabled_in_isolated_development_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(manager.router, "CODEX_HOME", str(home)), \
                 patch.dict(os.environ, {"CODEX_ROUTER_DEV": "1"}):
                with self.assertRaisesRegex(ValueError, "isolated preview"):
                    manager.link_codex()
            self.assertFalse((home / "config.toml").exists())

    def test_provider_models_api_returns_catalogs_without_credentials(self):
        snapshot = {
            "checked_at": "2030-01-01T00:00:00Z",
            "total": 4,
            "providers": {
                provider: {"models": [{"id": f"{provider}-model", "name": f"{provider.title()} Model"}],
                           "count": 1, "source": "live account catalog", "error": None, "stale": False}
                for provider in ("openai", "anthropic", "kimi", "opencode")
            },
        }
        with patch.object(manager.provider_catalog, "collect", return_value=snapshot) as collect:
            server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/provider-models?refresh=1"
                ) as response:
                    result = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        collect.assert_called_once()
        self.assertEqual(result["total"], 4)
        self.assertNotIn("access_token", json.dumps(result).lower())
        self.assertNotIn("refresh_token", json.dumps(result).lower())

    def test_relay_oauth_status_takes_precedence_over_opencode_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(manager.anthropic_oauth, "credential_status", return_value={
                "status": "credential_found", "expired": False, "expires": 9999999999999
            }), patch.object(manager, "_user_env", return_value=None):
                providers = manager.provider_state()
            self.assertEqual(providers["anthropic"]["status"], "credential_found")
            self.assertIn("Relay OAuth", providers["anthropic"]["detail"])

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
