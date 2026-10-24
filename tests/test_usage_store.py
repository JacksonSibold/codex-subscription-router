from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import usage_store


class UsageStoreTests(unittest.TestCase):
    def test_records_and_aggregates_provider_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.sqlite"
            usage_store.record(path, "openai", "Codex account", "gpt-test", 200, {
                "input_tokens": 100, "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 40},
                "output_tokens_details": {"reasoning_tokens": 5},
            })
            usage_store.record(path, "anthropic", "Claude account", "claude-test", 200, {
                "input_tokens": 50, "output_tokens": 10,
            })
            result = usage_store.dashboard(path)
            self.assertTrue(result["available"])
            self.assertEqual(result["totals"]["requests"], 2)
            self.assertEqual(result["totals"]["total_tokens"], 180)
            self.assertEqual(len(result["providers"]), 2)
            self.assertEqual(result["models"][0]["total_tokens"], 120)
            self.assertEqual(len(result["recent"]), 2)

    def test_missing_database_returns_empty_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            result = usage_store.dashboard(Path(directory) / "missing.sqlite")
            self.assertFalse(result["available"])
            self.assertEqual(result["totals"]["requests"], 0)


if __name__ == "__main__":
    unittest.main()
