from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "router"))
import install
import settings


class InstallerTests(unittest.TestCase):
    def test_codex_configuration_preserves_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('model = "old"\ncustom_key = "keep"\n\n[projects."example"]\ntrust_level = "trusted"\n', encoding="utf-8")
            install.configure_codex(path, "claude-opus-5-5", "medium", Path(directory) / "mixed-models.json")
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["custom_key"], "keep")
            self.assertEqual(parsed["projects"]["example"]["trust_level"], "trusted")
            self.assertEqual(parsed["model"], "claude-opus-5-5")
            self.assertEqual(parsed["model_reasoning_effort"], "medium")
            self.assertEqual(parsed["model_providers"]["mixed"]["base_url"], "http://127.0.0.1:18765")
            self.assertEqual(parsed["model_catalog_json"], str(Path(directory) / "mixed-models.json"))
            self.assertTrue(parsed["agents"]["enabled"])
            self.assertTrue(list(Path(directory).glob("config.toml.backup-*")))

    def test_windows_catalog_path_remains_valid_toml(self):
        # Exercise a pre-existing single-quoted Windows path without depending on the host OS.
        original = r"model_catalog_json = 'C:\Old\mixed-models.json'" + "\n"
        expected = r"C:\New Folder\mixed-models.json"
        result = install._set_toml_key(original, "model_catalog_json", json.dumps(expected))
        self.assertEqual(tomllib.loads(result)["model_catalog_json"], expected)

    def test_default_model_uses_its_own_reasoning_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            install.configure_codex_for_settings(path, settings.default_settings(), Path(directory) / "mixed-models.json")
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["model"], "deepseek-v4.1-flash")
            self.assertEqual(parsed["model_reasoning_effort"], "high")

    def test_existing_mixed_provider_is_updated_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[model_providers.mixed]\nname = "old"\nbase_url = "old"\n\n[desktop]\nenabled-reasoning-efforts = ["low"]\n', encoding="utf-8")
            install.configure_codex(path, "k3.1-pro", "max", Path(directory) / "mixed-models.json")
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("[model_providers.mixed]"), 1)
            self.assertEqual(text.count("[desktop]"), 1)
            self.assertNotIn('"old"', text)


if __name__ == "__main__":
    unittest.main()
