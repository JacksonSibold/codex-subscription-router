from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import anthropic_oauth
import subscription_usage
import version


class VersionTests(unittest.TestCase):
    def test_version_has_one_source_and_matches_runtime_and_ui_metadata(self):
        declared = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(declared, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(version.__version__, declared)
        package = json.loads((ROOT / "app" / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "app" / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], declared)
        self.assertEqual(lock["version"], declared)
        self.assertEqual(lock["packages"][""]["version"], declared)
        self.assertTrue(anthropic_oauth.USER_AGENT.startswith(f"Relay/{declared} "))
        self.assertTrue(subscription_usage.USER_AGENT.startswith(f"Relay/{declared} "))

    def test_release_metadata_has_no_stale_operational_version(self):
        for source in (ROOT / "router").glob("*.py"):
            text = source.read_text(encoding="utf-8")
            self.assertNotIn("Relay/0.3", text, source.name)
        app = (ROOT / "app" / "src" / "App.jsx").read_text(encoding="utf-8")
        self.assertNotRegex(app, re.compile(r"RELAY\s+0\.3\.0"))


if __name__ == "__main__":
    unittest.main()
