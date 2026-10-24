from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import settings


class SettingsTests(unittest.TestCase):
    def test_default_document_is_valid_and_complete(self):
        document = settings.validate(settings.default_settings())
        self.assertEqual(len(document["models"]), 11)
        self.assertEqual(document["runtime"]["default_model"], "deepseek-v4.1-flash")
        self.assertEqual(document["models"][-1]["id"], "k3.1-pro")

    def test_atomic_save_creates_backup_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "router-settings.json"
            document = settings.default_settings()
            settings.save(path, document)
            document["models"][0]["display_name"] = "Renamed GPT"
            settings.save(path, document)
            self.assertEqual(settings.load(path)["models"][0]["display_name"], "Renamed GPT")
            backups = list(Path(directory).glob("*.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertFalse(list(Path(directory).glob("*.tmp-*")))

    def test_rejects_credentials_and_duplicate_ids(self):
        document = settings.default_settings()
        document["models"][0]["display_name"] = "sk-" + ("a" * 24)
        with self.assertRaisesRegex(ValueError, "credential"):
            settings.validate(document)
        document = settings.default_settings()
        document["models"][1]["id"] = document["models"][0]["id"]
        with self.assertRaisesRegex(ValueError, "unique"):
            settings.validate(document)

    def test_rejects_unsupported_provider_tools_and_bad_default(self):
        document = settings.default_settings()
        document["models"][2]["tools"]["connected_apps"] = True
        with self.assertRaisesRegex(ValueError, "OpenAI-only"):
            settings.validate(document)
        document = settings.default_settings()
        document["models"][2]["reasoning"]["default"] = "max"
        with self.assertRaisesRegex(ValueError, "default"):
            settings.validate(document)

    def test_local_model_requires_loopback_and_records_upstream_id(self):
        document = settings.default_settings()
        local = settings._model("local-llama", "local", "Llama · Local", "medium", ["low", "medium", "high"])
        local["local"] = {"endpoint": "http://127.0.0.1:11434/v1/chat/completions",
                          "protocol": "openai_chat", "credential_env": None}
        local["upstream_id"] = "llama3.2:3b"
        document["models"].append(local)
        clean = settings.validate(document)
        added = clean["models"][-1]
        self.assertEqual(added["upstream_id"], "llama3.2:3b")
        self.assertEqual(added["local"]["endpoint"], "http://127.0.0.1:11434/v1")
        local["local"]["endpoint"] = "http://192.168.1.10:11434/v1"
        with self.assertRaisesRegex(ValueError, "loopback"):
            settings.validate(document)

    def test_version_one_migrates_without_losing_preferences(self):
        document = settings.default_settings()
        document["version"] = 1
        document["models"][0]["display_name"] = "Keep me"
        for model in document["models"]:
            model.pop("upstream_id", None)
        document["providers"].pop("local")
        document["providers"]["anthropic"]["auth_method"] = "opencode_oauth"
        clean = settings.validate(document)
        self.assertEqual(clean["version"], 2)
        self.assertEqual(clean["models"][0]["display_name"], "Keep me")
        self.assertEqual(clean["models"][0]["upstream_id"], clean["models"][0]["id"])
        self.assertEqual(clean["providers"]["anthropic"]["auth_method"], "relay_oauth")
        self.assertTrue(clean["providers"]["local"]["enabled"])

    def test_legacy_default_claude_names_are_normalized_without_renaming_custom_routes(self):
        document = settings.default_settings()
        for model in document["models"]:
            if model["provider"] == "anthropic":
                model["display_name"] = model["display_name"].replace(" — Claude", " — Claude Pro")
        custom = [model for model in document["models"] if model["provider"] == "anthropic"][1]
        custom["display_name"] = "My Custom Claude"
        clean = settings.validate(document)
        names = [model["display_name"] for model in clean["models"] if model["provider"] == "anthropic"]
        self.assertIn("Claude Sonnet 5.5 — Claude", names)
        self.assertIn("My Custom Claude", names)
        self.assertFalse(any(name.endswith("— Claude Pro") for name in names))

    def test_missing_file_preserves_original_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            document = settings.load(Path(directory) / "absent.json")
            self.assertEqual([m["id"] for m in document["models"][:2]], ["gpt-6.1-sol", "gpt-6-luna"])


if __name__ == "__main__":
    unittest.main()
