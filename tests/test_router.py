from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import anthropic_adapter
import namespace_tools
import router
import settings


class RouterTests(unittest.TestCase):
    def test_namespace_bridge_self_test(self):
        namespace_tools.self_test()

    def test_claude_computer_use_and_thinking_survive_translation(self):
        body = {
            "model": "claude-opus-5-5",
            "reasoning": {"effort": "xhigh"},
            "tools": [{"type": "namespace", "name": "mcp__cua_repl", "tools": [
                {"type": "function", "name": "js", "parameters": {"type": "object"}}
            ]}],
            "input": [{"type": "message", "role": "user", "content": [{"type": "text", "text": "Hello"}]}],
        }
        payload, kinds = anthropic_adapter.build_payload(body)
        self.assertEqual(payload["output_config"]["effort"], "xhigh")
        self.assertEqual(payload["tools"][0]["name"], "mcp__cua_repl__js")
        self.assertEqual(kinds["mcp__cua_repl__js"], "function")

    def test_tool_policy_is_enforced_before_forwarding(self):
        preference = settings.default_settings()["models"][0]
        preference["tools"].update({"shell": False, "computer_use": False, "connected_apps": True, "web_search": False})
        body = {"tools": [
            {"type": "function", "name": "exec_command"},
            {"type": "namespace", "name": "mcp__node_repl", "tools": []},
            {"type": "namespace", "name": "mcp__gmail", "tools": []},
            {"type": "web_search"},
        ], "tool_choice": "auto"}
        self.assertTrue(router.apply_tool_policy(body, preference))
        self.assertEqual([tool["name"] for tool in body["tools"]], ["mcp__gmail"])
        self.assertEqual(body["tool_choice"], "auto")

    def test_catalog_honors_visibility_order_names_reasoning_and_subagents(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "models_cache.json").write_text(json.dumps({"models": [
                {"slug": "gpt-6.1-sol", "display_name": "original"},
                {"slug": "gpt-6-luna", "display_name": "original"},
            ]}), encoding="utf-8")
            (home / "opencode-go-models.json").write_text((ROOT / "catalog" / "opencode-go-models.json").read_text(encoding="utf-8"), encoding="utf-8")
            original_home = router.CODEX_HOME
            try:
                router.CODEX_HOME = str(home)
                document = settings.default_settings()
                document["models"][0]["display_name"] = "My GPT"
                document["models"][0]["subagents"] = False
                document["models"][1]["visible"] = False
                document["models"].insert(0, document["models"].pop(8))
                output = home / "catalog.json"
                slugs = router.build_catalog(document, str(output))
                catalog = json.loads(output.read_text(encoding="utf-8"))["models"]
                self.assertEqual(slugs[0], "claude-sonnet-5-5")
                self.assertNotIn("gpt-6-luna", slugs)
                gpt = next(model for model in catalog if model["slug"] == "gpt-6.1-sol")
                self.assertEqual(gpt["display_name"], "My GPT")
                self.assertIsNone(gpt["multi_agent_version"])
                claude = catalog[0]
                self.assertEqual([level["effort"] for level in claude["supported_reasoning_levels"]], ["low", "medium", "high", "xhigh", "max"])
            finally:
                router.CODEX_HOME = original_home


if __name__ == "__main__":
    unittest.main()
