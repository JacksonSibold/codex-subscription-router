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
import subscription_usage


class SubscriptionUsageTests(unittest.TestCase):
    def test_parses_codex_claude_and_kimi_allowance_shapes(self):
        plan, codex = subscription_usage._parse_openai({
            "plan_type": "plus",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 23.4,
                    "limit_window_seconds": 18_000,
                    "reset_at": 2_000_000_000,
                },
                "secondary_window": {
                    "used_percent": 8,
                    "limit_window_seconds": 604_800,
                    "reset_after_seconds": 3600,
                },
            },
        })
        self.assertEqual(plan, "plus")
        self.assertEqual([row["label"] for row in codex], ["5-hour limit", "Weekly limit"])
        self.assertEqual(codex[0]["used_percent"], 23.4)
        self.assertEqual(codex[0]["remaining_percent"], 76.6)

        claude = subscription_usage._parse_anthropic({
            "five_hour": {"utilization": 42.5, "resets_at": "2030-01-01T00:00:00Z"},
            "seven_day": {"utilization": 12, "resets_at": "2030-01-02T00:00:00Z"},
        })
        self.assertEqual([row["used_percent"] for row in claude], [42.5, 12.0])

        kimi = subscription_usage._parse_kimi({
            "usages": {
                "limit_5h": {"used_ratio": 0.3, "reset_time": "2030-01-01T00:00:00Z"},
                "limit_7d": {"used_ratio": "0.2", "reset_time": "2030-01-02T00:00:00Z"},
            }
        })
        self.assertEqual([row["used_percent"] for row in kimi], [30.0, 20.0])
        self.assertEqual(kimi[0]["remaining_percent"], 70.0)

    def test_collect_reports_all_five_lanes_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(subscription_usage.anthropic_oauth, "access_token", side_effect=RuntimeError("missing")), \
             patch.object(subscription_usage.credentials, "get_secret", return_value=None), \
             patch.object(subscription_usage, "_get_json") as request:
            result = subscription_usage.collect(directory)
        request.assert_not_called()
        self.assertEqual(len(result["providers"]), 5)
        self.assertEqual({row["provider"] for row in result["providers"]},
                         {"openai", "anthropic", "kimi", "opencode", "local"})
        self.assertEqual(next(row for row in result["providers"] if row["provider"] == "openai")["status"],
                         "not_connected")

    def test_collect_keeps_credentials_out_of_response_and_headers_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text(json.dumps({
                "tokens": {"access_token": "codex-test-token", "account_id": "account-test"}
            }), encoding="utf-8")
            calls: dict[str, dict[str, str]] = {}

            def fake_json(url: str, headers: dict[str, str]):
                calls[url] = headers
                if "chatgpt.com" in url:
                    return {"plan_type": "plus", "rate_limit": {"primary_window": {
                        "used_percent": 10, "limit_window_seconds": 18_000
                    }}}
                if "anthropic.com" in url:
                    return {"five_hour": {"utilization": 20}}
                return {"usages": {"limit_5h": {"used_ratio": 0.3}}}

            with patch.dict(os.environ, {"CODEX_ROUTER_CREDENTIALS": str(home / "credentials.json")}), \
                 patch.object(subscription_usage.anthropic_oauth, "access_token", return_value="claude-test-token"), \
                 patch.object(subscription_usage.credentials, "get_secret",
                              side_effect=lambda name: "kimi-test-token" if name == "KIMI_API_KEY" else None), \
                 patch.object(subscription_usage, "_get_json", side_effect=fake_json):
                result = subscription_usage.collect(home)

            statuses = {row["provider"]: row["status"] for row in result["providers"]}
            self.assertEqual(statuses["openai"], "available")
            self.assertEqual(statuses["anthropic"], "available")
            self.assertEqual(statuses["kimi"], "available")
            self.assertNotIn("codex-test-token", json.dumps(result))
            self.assertNotIn("claude-test-token", json.dumps(result))
            self.assertNotIn("kimi-test-token", json.dumps(result))
            anthropic_call = next(headers for url, headers in calls.items() if "anthropic.com" in url)
            kimi_call = next(headers for url, headers in calls.items() if "kimi.ai" in url)
            self.assertEqual(anthropic_call["Authorization"], "Bearer claude-test-token")
            self.assertEqual(kimi_call["Authorization"], "Bearer kimi-test-token")
            self.assertNotIn("codex-test-token", json.dumps(anthropic_call))
            self.assertNotIn("codex-test-token", json.dumps(kimi_call))


if __name__ == "__main__":
    unittest.main()