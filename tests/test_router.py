from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import anthropic_adapter
import namespace_tools
import router
import settings
import usage_store


class RouterTests(unittest.TestCase):
    def test_usage_account_labels_follow_the_active_anthropic_credential_source(self):
        with patch.object(router.anthropic_oauth, "load_tokens", return_value={"access": "hidden"}):
            self.assertEqual(router.usage_account("anthropic"), router.USAGE_ACCOUNT_LABELS["anthropic"])
        with patch.object(router.anthropic_oauth, "load_tokens", return_value=None):
            self.assertEqual(router.usage_account("anthropic"), router.USAGE_ACCOUNT_LABELS["anthropic_fallback"])

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
                self.assertEqual(gpt["multi_agent_version"], "disabled")
                claude = catalog[0]
                self.assertEqual(claude["multi_agent_version"], "v2")
                self.assertEqual([level["effort"] for level in claude["supported_reasoning_levels"]], ["low", "medium", "high", "xhigh", "max"])
            finally:
                router.CODEX_HOME = original_home

    def test_catalog_synthesizes_any_custom_upstream_id_across_all_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            document = settings.default_settings()
            routes = [
                settings._model("custom-openai", "openai", "Custom OpenAI", "medium", ["low", "medium", "high"]),
                settings._model("custom-opencode", "opencode", "Custom OpenCode", "high", ["low", "high"]),
                settings._model("custom-claude", "anthropic", "Custom Claude", "high", ["low", "medium", "high", "max"]),
                settings._model("custom-kimi", "kimi", "Custom Kimi", "max", ["low", "high", "max"]),
                settings._model("custom-local", "local", "Custom Local", "medium", ["low", "medium", "high"]),
            ]
            for route in routes:
                route["upstream_id"] = "future-provider-model-not-in-cache"
            routes[-1]["local"] = {"endpoint": "http://127.0.0.1:11434/v1", "protocol": "openai_chat",
                                   "credential_env": None}
            document["models"] = routes
            document["runtime"]["default_model"] = routes[0]["id"]
            original_home = router.CODEX_HOME
            try:
                router.CODEX_HOME = str(home)
                output = home / "catalog.json"
                slugs = router.build_catalog(settings.validate(document), str(output))
            finally:
                router.CODEX_HOME = original_home
            self.assertEqual(slugs, [route["id"] for route in routes])
            built = {item["slug"]: item for item in json.loads(output.read_text(encoding="utf-8"))["models"]}
            self.assertEqual(set(built), {route["id"] for route in routes})
            self.assertTrue(all(item["multi_agent_version"] == "v2" for item in built.values()))
            for item in built.values():
                self.assertTrue(item.get("base_instructions") or item.get("model_messages"), item["slug"])
            for slug in ("custom-opencode", "custom-claude", "custom-kimi", "custom-local"):
                self.assertEqual(built[slug]["use_responses_lite"], False)
                self.assertEqual(built[slug]["tool_mode"], "direct")
            self.assertEqual(built["custom-local"]["shell_type"], "shell_command")

    def test_catalog_excludes_hidden_and_disabled_routes_but_disables_ineligible_parents(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            document = settings.default_settings()
            document["models"][0]["subagents"] = False
            document["models"][1]["visible"] = False
            document["providers"]["kimi"]["enabled"] = False
            original_home = router.CODEX_HOME
            try:
                router.CODEX_HOME = str(home)
                output = home / "catalog.json"
                slugs = router.build_catalog(document, str(output))
            finally:
                router.CODEX_HOME = original_home
            self.assertIn("gpt-6.1-sol", slugs)
            self.assertNotIn("gpt-6-luna", slugs)
            self.assertNotIn("k3.1-pro", slugs)
            built = {item["slug"]: item for item in json.loads(output.read_text(encoding="utf-8"))["models"]}
            self.assertEqual(built["gpt-6.1-sol"]["multi_agent_version"], "disabled")
            self.assertTrue(all(item["multi_agent_version"] == "v2" for slug, item in built.items()
                                if slug != "gpt-6.1-sol"))

    def test_claude_client_headers_follow_linux_and_apple_silicon(self):
        with patch.object(anthropic_adapter.platform, "system", return_value="Linux"), \
             patch.object(anthropic_adapter.platform, "machine", return_value="x86_64"):
            headers = anthropic_adapter._headers("hidden", "session")
        self.assertEqual(headers["x-stainless-os"], "Linux")
        self.assertEqual(headers["x-stainless-arch"], "x64")
        with patch.object(anthropic_adapter.platform, "system", return_value="Darwin"), \
             patch.object(anthropic_adapter.platform, "machine", return_value="arm64"):
            headers = anthropic_adapter._headers("hidden", "session")
        self.assertEqual(headers["x-stainless-os"], "MacOS")
        self.assertEqual(headers["x-stainless-arch"], "arm64")
        self.assertNotIn("Windows", headers.values())


class _FakeResponses:
    status = 200

    def __init__(self, usage=None):
        self.usage = usage or {"input_tokens": 13, "output_tokens": 8, "total_tokens": 21}
        payload = {
            "type": "response.completed",
            "response": {"status": "completed", "output": [], "usage": self.usage},
        }
        self.chunks = [
            b"event: response.completed\ndata: " + json.dumps(payload).encode() + b"\n\n",
            b"",
        ]

    def getheaders(self):
        return [("Content-Type", "text/event-stream")]

    def read1(self, size):
        return self.chunks.pop(0) if self.chunks else b""


class _FakeHttpsConnection:
    calls = []
    debuglevel = 0

    def __init__(self, host, timeout=None, context=None):
        self.host = host
        self.closed = False
        self.response = _FakeResponses()

    def request(self, method, path, body=None, headers=None):
        self.calls.append({"host": self.host, "path": path, "body": json.loads(body), "headers": dict(headers or {})})

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class _LocalChat(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length))
        type(self).calls.append({"body": body, "authorization": self.headers.get("Authorization")})
        events = [
            {"choices": [{"delta": {"content": "Local reply"}}]},
            {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}},
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.close_connection = True


class RouterIntegrationTests(unittest.TestCase):
    def _router_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), router.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_claude_parent_can_target_kimi_child_with_kimi_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            document = settings.default_settings()
            next(model for model in document["models"] if model["id"] == "k3.1-pro")["upstream_id"] = "kimi-upstream-provider-id"
            original_settings, original_usage = router.ACTIVE_SETTINGS, router.USAGE_PATH
            _FakeHttpsConnection.calls.clear()
            try:
                router.ACTIVE_SETTINGS = document
                router.USAGE_PATH = str(Path(directory) / "usage.sqlite")
                server, thread = self._router_server()
                try:
                    body = json.dumps({"model": "k3.1-pro", "stream": True,
                                       "input": [{"type": "message", "role": "user", "content": "child task"}]}).encode()
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/responses", data=body, method="POST",
                        headers={"Content-Type": "application/json", "Authorization": "Bearer parent-chatgpt-credential"},
                    )
                    with patch.object(router, "HTTPS_CONNECTION", _FakeHttpsConnection), \
                         patch.object(router.credentials, "get_secret", side_effect=lambda name:
                                      "kimi-secret" if name == "KIMI_API_KEY" else "opencode-secret"):
                        with urllib.request.urlopen(request, timeout=10) as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn(b"response.completed", response.read())
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                call = _FakeHttpsConnection.calls[0]
                self.assertEqual(call["host"], "api.kimi.ai")
                self.assertEqual(call["headers"]["Authorization"], "Bearer kimi-secret")
                self.assertEqual(call["body"]["model"], "kimi-upstream-provider-id")
                dashboard = usage_store.dashboard(Path(router.USAGE_PATH), 30)
                self.assertEqual(dashboard["providers"][0]["provider"], "kimi")
                self.assertEqual(dashboard["totals"]["total_tokens"], 21)
            finally:
                router.ACTIVE_SETTINGS, router.USAGE_PATH = original_settings, original_usage

    def test_openai_parent_can_target_local_child_without_forwarding_chatgpt_token(self):
        with tempfile.TemporaryDirectory() as directory:
            local_server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalChat)
            local_thread = threading.Thread(target=local_server.serve_forever, daemon=True)
            local_thread.start()
            document = settings.default_settings()
            local = settings._model("local-llama", "local", "Llama · Local", "medium", ["low", "medium", "high"])
            local["upstream_id"] = "llama3.2:3b"
            local["local"] = {"endpoint": f"http://127.0.0.1:{local_server.server_port}/v1",
                              "protocol": "openai_chat", "credential_env": "TEST_LOCAL_KEY"}
            document["models"].append(local)
            document = settings.validate(document)
            original_settings, original_usage = router.ACTIVE_SETTINGS, router.USAGE_PATH
            _LocalChat.calls.clear()
            try:
                router.ACTIVE_SETTINGS = document
                router.USAGE_PATH = str(Path(directory) / "usage.sqlite")
                server, thread = self._router_server()
                try:
                    body = json.dumps({"model": "local-llama", "stream": True,
                                       "input": [{"type": "message", "role": "user", "content": "local child"}]}).encode()
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/responses", data=body, method="POST",
                        headers={"Content-Type": "application/json", "Authorization": "Bearer parent-chatgpt-credential"},
                    )
                    with patch.dict(os.environ, {"TEST_LOCAL_KEY": "local-test-secret"}):
                        with urllib.request.urlopen(request, timeout=10) as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn(b"Local reply", response.read())
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                call = _LocalChat.calls[0]
                self.assertEqual(call["body"]["model"], "llama3.2:3b")
                self.assertEqual(call["authorization"], "Bearer local-test-secret")
                self.assertNotIn("parent-chatgpt-credential", json.dumps(call))
                # Every enabled local route is also eligible as a v2 child target.
                output = Path(directory) / "catalog.json"
                router.build_catalog(document, str(output))
                built = json.loads(output.read_text(encoding="utf-8"))["models"]
                self.assertTrue(next(item for item in built if item["slug"] == "local-llama")["multi_agent_version"] == "v2")
                dashboard = usage_store.dashboard(Path(router.USAGE_PATH), 30)
                self.assertEqual(dashboard["providers"][0]["provider"], "local")
                self.assertEqual(dashboard["totals"]["total_tokens"], 13)
            finally:
                router.ACTIVE_SETTINGS, router.USAGE_PATH = original_settings, original_usage
                local_server.shutdown()
                local_server.server_close()
                local_thread.join()

    def test_openai_child_uses_edited_upstream_id_and_stays_on_codex_lane(self):
        with tempfile.TemporaryDirectory() as directory:
            document = settings.default_settings()
            route = next(model for model in document["models"] if model["provider"] == "openai")
            route["upstream_id"] = "future-openai-child-id"
            original_settings, original_usage = router.ACTIVE_SETTINGS, router.USAGE_PATH
            _FakeHttpsConnection.calls.clear()
            _FakeHttpsConnection.host = None
            try:
                router.ACTIVE_SETTINGS = document
                router.USAGE_PATH = str(Path(directory) / "usage.sqlite")
                server, thread = self._router_server()
                try:
                    body = json.dumps({"model": route["id"], "stream": True,
                                       "input": [{"type": "message", "role": "user", "content": "child task"}]}).encode()
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/responses", data=body, method="POST",
                        headers={"Content-Type": "application/json", "Authorization": "Bearer codex-account-token"},
                    )
                    with patch.object(router, "HTTPS_CONNECTION", _FakeHttpsConnection):
                        with urllib.request.urlopen(request, timeout=10) as response:
                            self.assertEqual(response.status, 200)
                            response.read()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                call = _FakeHttpsConnection.calls[0]
                self.assertEqual(call["host"], "chatgpt.com")
                self.assertEqual(call["headers"]["Authorization"], "Bearer codex-account-token")
                self.assertEqual(call["body"]["model"], "future-openai-child-id")
            finally:
                router.ACTIVE_SETTINGS, router.USAGE_PATH = original_settings, original_usage

    def test_opencode_child_uses_only_opencode_credential_and_edited_upstream_id(self):
        with tempfile.TemporaryDirectory() as directory:
            document = settings.default_settings()
            route = next(model for model in document["models"] if model["provider"] == "opencode")
            route["upstream_id"] = "future-opencode-child-id"
            original_settings, original_usage = router.ACTIVE_SETTINGS, router.USAGE_PATH
            _FakeHttpsConnection.calls.clear()
            try:
                router.ACTIVE_SETTINGS = document
                router.USAGE_PATH = str(Path(directory) / "usage.sqlite")
                server, thread = self._router_server()
                try:
                    body = json.dumps({"model": route["id"], "stream": True,
                                       "input": [{"type": "message", "role": "user", "content": "child task"}]}).encode()
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/responses", data=body, method="POST",
                        headers={"Content-Type": "application/json", "Authorization": "Bearer parent-codex-token"},
                    )
                    with patch.object(router, "HTTPS_CONNECTION", _FakeHttpsConnection), \
                         patch.object(router.credentials, "get_secret", return_value="opencode-child-secret"):
                        with urllib.request.urlopen(request, timeout=10) as response:
                            self.assertEqual(response.status, 200)
                            response.read()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                call = _FakeHttpsConnection.calls[0]
                self.assertEqual(call["host"], "opencode.ai")
                self.assertEqual(call["headers"]["Authorization"], "Bearer opencode-child-secret")
                self.assertEqual(call["body"]["model"], "future-opencode-child-id")
                self.assertNotIn("parent-codex-token", json.dumps(call))
            finally:
                router.ACTIVE_SETTINGS, router.USAGE_PATH = original_settings, original_usage

    def test_anthropic_child_uses_relay_adapter_and_edited_upstream_id(self):
        with tempfile.TemporaryDirectory() as directory:
            document = settings.default_settings()
            route = next(model for model in document["models"] if model["provider"] == "anthropic")
            route["upstream_id"] = "future-claude-child-id"
            observed: list[dict] = []
            original_settings, original_usage = router.ACTIVE_SETTINGS, router.USAGE_PATH

            def fake_anthropic(body, start, emit, write_raw, log):
                observed.append(body)
                start(200, [("Content-Type", "text/event-stream")])
                emit("response.completed", {"type": "response.completed", "response": {
                    "status": "completed", "output": [], "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
                }})
                return 200, 1, {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}

            try:
                router.ACTIVE_SETTINGS = document
                router.USAGE_PATH = str(Path(directory) / "usage.sqlite")
                server, thread = self._router_server()
                try:
                    body = json.dumps({"model": route["id"], "stream": True,
                                       "input": [{"type": "message", "role": "user", "content": "child task"}]}).encode()
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/responses", data=body, method="POST",
                        headers={"Content-Type": "application/json", "Authorization": "Bearer parent-codex-token"},
                    )
                    with patch.object(router.anthropic_adapter, "run", side_effect=fake_anthropic):
                        with urllib.request.urlopen(request, timeout=10) as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn(b"response.completed", response.read())
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                self.assertEqual(observed[0]["model"], "future-claude-child-id")
                dashboard = usage_store.dashboard(Path(router.USAGE_PATH), 30)
                self.assertEqual(dashboard["providers"][0]["provider"], "anthropic")
            finally:
                router.ACTIVE_SETTINGS, router.USAGE_PATH = original_settings, original_usage

    def test_catalog_keeps_route_slug_when_upstream_id_is_edited(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "models_cache.json").write_text(json.dumps({"models": [
                {"slug": "provider-model-v2", "display_name": "Provider Model"},
            ]}), encoding="utf-8")
            (home / "opencode-go-models.json").write_text('{"models":[]}', encoding="utf-8")
            document = settings.default_settings()
            document["models"] = [settings._model("my-route", "openai", "My route", "medium", ["low", "medium", "high"])]
            document["models"][0]["upstream_id"] = "provider-model-v2"
            document["runtime"]["default_model"] = "my-route"
            original_home = router.CODEX_HOME
            try:
                router.CODEX_HOME = str(home)
                output = home / "mixed.json"
                slugs = router.build_catalog(document, str(output))
                self.assertEqual(slugs, ["my-route"])
                item = json.loads(output.read_text(encoding="utf-8"))["models"][0]
                self.assertEqual(item["slug"], "my-route")
                self.assertEqual(item["multi_agent_version"], "v2")
            finally:
                router.CODEX_HOME = original_home


if __name__ == "__main__":
    unittest.main()
