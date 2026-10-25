from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import codex_config


class CodexConfigTests(unittest.TestCase):
    def test_default_update_preserves_projects_plugins_and_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            original = '''model = "old"
model_reasoning_effort = "low"
custom = 42

[model_providers.mixed]
base_url = "http://127.0.0.1:18765"
wire_api = "responses"

[projects."example"]
trust_level = "trusted"
'''
            path.write_text(original, encoding="utf-8")
            codex_config.set_default_model(path, "k3.1-pro", "max")
            result = path.read_text(encoding="utf-8")
            parsed = tomllib.loads(result)
            self.assertEqual(parsed["model"], "k3.1-pro")
            self.assertEqual(parsed["model_reasoning_effort"], "max")
            self.assertEqual(parsed["custom"], 42)
            self.assertEqual(parsed["model_providers"]["mixed"], tomllib.loads(original)["model_providers"]["mixed"])
            self.assertEqual(parsed["projects"], tomllib.loads(original)["projects"])
            self.assertEqual(len(list(Path(directory).glob("config.toml.backup-*"))), 1)

    def test_clearing_reasoning_removes_stale_effort(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('model = "old"\nmodel_reasoning_effort = "high"\n', encoding="utf-8")
            codex_config.set_default_model(path, "new", None)
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["model"], "new")
            self.assertNotIn("model_reasoning_effort", parsed)

    def test_relay_link_preserves_unrelated_configuration_and_updates_mixed_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            catalog = root / "mixed-models.json"
            catalog.write_text('{"models": []}', encoding="utf-8")
            original = '''model = "old-model"
model_provider = "existing"
model_reasoning_effort = "low"
custom = "keep"

[model_providers.existing]
base_url = "http://127.0.0.1:9000"
wire_api = "responses"

[model_providers.mixed]
base_url = "http://127.0.0.1:9999"
wire_api = "responses"
custom_header = "preserve-me"

[desktop]
enabled-reasoning-efforts = ["low"]
other-desktop-setting = true

[agents]
enabled = false

[projects."example"]
trust_level = "trusted"

[[plugins]]
name = "existing-plugin"
'''
            path.write_text(original, encoding="utf-8")
            codex_config.configure_relay(path, catalog, "claude-opus-5-5", "high")
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["model"], "claude-opus-5-5")
            self.assertEqual(parsed["model_provider"], "mixed")
            self.assertEqual(parsed["model_reasoning_effort"], "high")
            self.assertEqual(parsed["model_catalog_json"], str(catalog))
            self.assertEqual(parsed["custom"], "keep")
            self.assertEqual(parsed["model_providers"]["existing"]["base_url"], "http://127.0.0.1:9000")
            self.assertEqual(parsed["model_providers"]["mixed"]["base_url"], "http://127.0.0.1:18765")
            self.assertEqual(parsed["model_providers"]["mixed"]["custom_header"], "preserve-me")
            self.assertEqual(parsed["desktop"]["other-desktop-setting"], True)
            self.assertTrue(parsed["agents"]["enabled"])
            self.assertEqual(parsed["projects"]["example"]["trust_level"], "trusted")
            self.assertEqual(parsed["plugins"][0]["name"], "existing-plugin")
            self.assertEqual(len(list(root.glob("config.toml.backup-*"))), 1)

    def test_relay_link_handles_windows_catalog_path_without_invalid_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            catalog = Path("C:/Users/example/.codex/mixed-models.json")
            codex_config.configure_relay(path, catalog, "gpt-test", None)
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["model_catalog_json"], str(catalog))
            self.assertNotIn("model_reasoning_effort", parsed)


if __name__ == "__main__":
    unittest.main()
