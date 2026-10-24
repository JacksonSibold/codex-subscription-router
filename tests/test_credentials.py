from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import credentials


class CredentialTests(unittest.TestCase):
    def test_file_store_round_trip_is_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "relay" / "credentials.json"
            credentials.set_secret("TEST_API_KEY", "example-secret", file=path)
            credentials.set_secret("OTHER_API_KEY", "second-secret", file=path)
            self.assertEqual(credentials.get_secret("TEST_API_KEY", file=path), "example-secret")
            self.assertEqual(credentials.get_secret("OTHER_API_KEY", file=path), "second-secret")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["TEST_API_KEY"], "example-secret")
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_environment_value_takes_precedence_without_writing(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TEST_API_KEY": "from-environment"}):
            path = Path(directory) / "credentials.json"
            self.assertEqual(credentials.get_secret("TEST_API_KEY", file=path), "from-environment")
            self.assertFalse(path.exists())

    def test_credentials_path_override_keeps_tests_out_of_the_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated" / "credentials.json"
            with patch.dict(os.environ, {"CODEX_ROUTER_CREDENTIALS": str(path), "TEST_API_KEY": "ambient-live-secret"}):
                credentials.set_secret("TEST_API_KEY", "file-secret")
                self.assertEqual(credentials.get_secret("TEST_API_KEY"), "file-secret")
            self.assertTrue(path.is_file())
            self.assertNotIn("TEST_API_KEY", credentials._read_file(path.with_name("missing.json")))

    def test_rejects_bad_names_and_empty_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            with self.assertRaises(credentials.CredentialError):
                credentials.set_secret("../bad", "value", file=path)
            with self.assertRaises(credentials.CredentialError):
                credentials.set_secret("TEST_API_KEY", "   ", file=path)


if __name__ == "__main__":
    unittest.main()
