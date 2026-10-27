from __future__ import annotations

import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import provider_catalog


class ProviderCatalogTests(unittest.TestCase):
    def setUp(self):
        provider_catalog._CACHE = None
        provider_catalog._CACHE_TIME = 0.0

    def tearDown(self):
        provider_catalog._CACHE = None
        provider_catalog._CACHE_TIME = 0.0

    def test_opencode_cache_excludes_deprecated_entries_and_normalizes_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.json"
            path.write_text(json.dumps({"opencode": {"models": {
                "gpt-active": {"id": "gpt-active", "name": "GPT Active"},
                "claude-old": {"id": "claude-old", "name": "Claude Old", "status": "deprecated"},
                "local-active": {"id": "local-active", "name": ""},
                "gpt-active-copy": {"id": "gpt-active", "name": "Duplicate"},
            }}}), encoding="utf-8")
            models = provider_catalog.parse_opencode_cache(path)
        self.assertEqual([row["id"] for row in models], ["gpt-active", "local-active"])
        self.assertEqual(models[0]["name"], "GPT Active")
        self.assertEqual(models[1]["name"], "Local Active")

    def test_collect_keeps_cached_rows_stale_and_sanitizes_errors(self):
        healthy = {
            "openai": lambda *_args: ([{"id": "gpt-live", "name": "GPT Live"}], "Codex catalog"),
            "anthropic": lambda: ([{"id": "claude-live", "name": "Claude Live"}], "Anthropic catalog"),
            "kimi": lambda: ([{"id": "kimi-live", "name": "Kimi Live"}], "Kimi catalog"),
            "opencode": lambda *_args: ([{"id": "opencode-live", "name": "OpenCode Live"}], "OpenCode catalog"),
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(provider_catalog, "CACHE_PATH", Path(directory) / "catalog-cache.json"), \
             patch.multiple(provider_catalog,
                            _openai_models=healthy["openai"],
                            _anthropic_models=healthy["anthropic"],
                            _kimi_models=healthy["kimi"],
                            _opencode_models=healthy["opencode"]):
            first = provider_catalog.collect(Path(directory), force=True)
            self.assertEqual(first["total"], 4)
            self.assertFalse(any(row["error"] for row in first["providers"].values()))

        def fail():
            raise RuntimeError("Authorization: Bearer top-secret-value")

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(provider_catalog, "CACHE_PATH", Path(directory) / "catalog-cache.json"), \
             patch.multiple(provider_catalog,
                            _openai_models=healthy["openai"],
                            _anthropic_models=fail,
                            _kimi_models=healthy["kimi"],
                            _opencode_models=healthy["opencode"]):
            second = provider_catalog.collect(Path(directory), force=True)
        anthropic = second["providers"]["anthropic"]
        self.assertTrue(anthropic["stale"])
        self.assertEqual(anthropic["models"][0]["id"], "claude-live")
        self.assertIn("RuntimeError", anthropic["error"])
        self.assertNotIn("top-secret-value", json.dumps(second))

    def test_collect_uses_built_in_fallback_when_provider_is_unavailable(self):
        def fail(*_args):
            raise RuntimeError("provider unavailable")

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(provider_catalog, "CACHE_PATH", Path(directory) / "catalog-cache.json"), \
                 patch.multiple(provider_catalog,
                                _openai_models=fail,
                                _anthropic_models=fail,
                                _kimi_models=fail,
                                _opencode_models=fail):
                snapshot = provider_catalog.collect(Path(directory), force=True)
        self.assertGreater(snapshot["providers"]["openai"]["count"], 0)
        self.assertGreater(snapshot["providers"]["anthropic"]["count"], 0)
        self.assertGreater(snapshot["providers"]["kimi"]["count"], 0)
        self.assertEqual(snapshot["providers"]["opencode"]["count"], 0)
        self.assertTrue(all(row["error"] for row in snapshot["providers"].values()))

    def test_catalog_cache_survives_a_manager_restart_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "provider-catalog-cache.json"
            providers = {
                provider: (lambda *_args, provider=provider: (
                    [{"id": f"{provider}-new", "name": f"{provider.title()} New"}],
                    f"{provider.title()} catalog",
                ))
                for provider in ("openai", "anthropic", "kimi", "opencode")
            }
            with patch.object(provider_catalog, "CACHE_PATH", cache_path), \
                 patch.multiple(provider_catalog,
                                _openai_models=providers["openai"],
                                _anthropic_models=providers["anthropic"],
                                _kimi_models=providers["kimi"],
                                _opencode_models=providers["opencode"]):
                first = provider_catalog.collect(Path(directory), force=True)
            self.assertTrue(cache_path.is_file())
            self.assertEqual(first["total"], 4)
            provider_catalog._CACHE = None
            provider_catalog._CACHE_TIME = 0.0
            with patch.object(provider_catalog, "CACHE_PATH", cache_path):
                restored = provider_catalog.cached_snapshot()
            self.assertEqual(restored["total"], 4)
            self.assertEqual(restored["providers"]["openai"]["models"][0]["id"], "openai-new")
            self.assertNotIn("key", cache_path.read_text(encoding="utf-8").lower())

    def test_new_model_markers_compare_against_the_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "catalog-cache.json"
            first = {
                provider: (lambda *_args, provider=provider: (
                    [{"id": f"{provider}-old", "name": f"{provider.title()} Old"}],
                    f"{provider.title()} catalog",
                ))
                for provider in ("openai", "anthropic", "kimi", "opencode")
            }
            second = {
                provider: (lambda *_args, provider=provider: (
                    [
                        {"id": f"{provider}-old", "name": f"{provider.title()} Old"},
                        {"id": f"{provider}-new", "name": f"{provider.title()} New"},
                    ],
                    f"{provider.title()} catalog",
                ))
                for provider in ("openai", "anthropic", "kimi", "opencode")
            }
            with patch.object(provider_catalog, "CACHE_PATH", cache_path), \
                 patch.multiple(provider_catalog,
                                _openai_models=first["openai"],
                                _anthropic_models=first["anthropic"],
                                _kimi_models=first["kimi"],
                                _opencode_models=first["opencode"]):
                initial = provider_catalog.collect(Path(directory), force=True)
            self.assertTrue(all(not row["new_models"] for row in initial["providers"].values()))
            with patch.object(provider_catalog, "CACHE_PATH", cache_path), \
                 patch.multiple(provider_catalog,
                                _openai_models=second["openai"],
                                _anthropic_models=second["anthropic"],
                                _kimi_models=second["kimi"],
                                _opencode_models=second["opencode"]):
                refreshed = provider_catalog.collect(Path(directory), force=True)
            self.assertEqual(
                [row["id"] for row in refreshed["providers"]["openai"]["new_models"]],
                ["openai-new"],
            )


if __name__ == "__main__":
    unittest.main()
