from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import error_explainer


class ErrorExplainerTests(unittest.TestCase):
    def test_auth_error_names_provider_and_reconnect_action(self):
        result = error_explainer.explain(
            "anthropic", 401, b'{"error":{"message":"invalid x-api-key"}}'
        )
        self.assertEqual(result["code"], "authentication")
        self.assertIn("Claude", result["message"])
        self.assertIn("Reconnect", result["action"])
        self.assertIn("invalid x-api-key", result["message"])

    def test_missing_model_preserves_provider_model_hint(self):
        result = error_explainer.explain(
            "openai", 404, b'{"error":{"message":"Model model gpt-old is not available"}}'
        )
        self.assertEqual(result["code"], "model_unavailable")
        self.assertIn("gpt-old", result["action"])

    def test_quota_error_points_to_usage_and_alternate_route(self):
        result = error_explainer.explain(
            "kimi", 429, b'{"error":"usage limit exceeded for this billing period"}'
        )
        self.assertEqual(result["code"], "rate_or_usage_limit")
        self.assertIn("Usage", result["action"])

    def test_tool_and_context_errors_are_actionable(self):
        tool = error_explainer.explain("opencode", 400, "unsupported tool: web_search")
        context = error_explainer.explain("local", 400, "maximum context length exceeded")
        self.assertEqual(tool["code"], "tool_incompatible")
        self.assertEqual(context["code"], "context_limit")

    def test_secrets_are_redacted_and_provider_detail_is_bounded(self):
        body = json.dumps({
            "error": {
                "message": "Authorization: Bearer super-secret-token api_key=another-secret " + "x" * 2000
            }
        }).encode()
        result = error_explainer.explain("openai", 401, body)
        serialized = json.dumps(result)
        self.assertNotIn("super-secret-token", serialized)
        self.assertNotIn("another-secret", serialized)
        self.assertIn("[hidden]", serialized)
        self.assertLessEqual(len(result["detail"]), 600)

    def test_non_json_body_is_still_readable(self):
        result = error_explainer.explain("opencode", 502, b"upstream connect error or disconnect/reset")
        self.assertEqual(result["code"], "provider_unavailable")
        self.assertIn("upstream connect error", result["message"])


if __name__ == "__main__":
    unittest.main()
