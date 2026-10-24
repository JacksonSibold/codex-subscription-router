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

    def test_missing_file_preserves_original_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            document = settings.load(Path(directory) / "absent.json")
            self.assertEqual([m["id"] for m in document["models"][:2]], ["gpt-6.1-sol", "gpt-6-luna"])


if __name__ == "__main__":
    unittest.main()
