from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "router"))
import local_adapter
import namespace_tools
import settings


class _FakeLocal(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        payload = json.dumps({"data": [
            {"id": "llama3.2:3b", "name": "Llama 3.2 3B"},
            {"id": "qwen3:8b"},
        ]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length))
        type(self).requests.append({"path": self.path, "body": body, "authorization": self.headers.get("Authorization")})
        if self.path == "/v1/chat/completions":
            events = [
                {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hel"}}]},
                {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {"content": "lo"}}]},
                {"choices": [{"delta": {}}], "usage": {
                    "prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16,
                    "prompt_tokens_details": {"cached_tokens": 3},
                }},
            ]
        elif self.path == "/v1/responses":
            events = [
                {"type": "response.created", "response": {"status": "in_progress", "output": []}},
                {"type": "response.completed", "response": {"status": "completed", "output": [],
                    "usage": {"input_tokens": 7, "output_tokens": 4, "total_tokens": 11}}},
            ]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            payload = ("data: " + json.dumps(event) + "\r\n\r\n").encode()
            self.wfile.write(payload)
            self.wfile.flush()
            time.sleep(0.005)
        self.wfile.write(b"data: [DONE]\r\n\r\n")
        self.wfile.flush()
        self.close_connection = True


class LocalAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLocal)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        _FakeLocal.requests.clear()

    def test_discovers_loopback_models_and_rejects_remote_endpoint(self):
        models = local_adapter.discover(self.endpoint)
        self.assertEqual([model["id"] for model in models], ["llama3.2:3b", "qwen3:8b"])
        with self.assertRaisesRegex(ValueError, "loopback"):
            local_adapter.discover("http://example.com/v1")

    def test_chat_translation_preserves_tools_and_tool_results(self):
        body = {
            "model": "llama3.2:3b", "instructions": "Be concise.",
            "tools": [
                {"type": "function", "name": "exec_command", "description": "Run", "parameters": {"type": "object"}},
                {"type": "namespace", "name": "mcp__node_repl__", "tools": [
                    {"type": "function", "name": "js", "parameters": {"type": "object"}}
                ]},
            ],
            "input": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Inspect"}]},
                {"type": "function_call", "call_id": "call-1", "name": "exec_command", "arguments": "{\"cmd\":\"pwd\"}"},
                {"type": "function_call_output", "call_id": "call-1", "output": "/tmp"},
            ],
            "max_output_tokens": 100,
            "reasoning": {"effort": "medium"},
        }
        mapping, changed = namespace_tools.flatten_request(body)
        self.assertTrue(changed)
        payload = local_adapter.chat_payload(body)
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "Be concise."})
        self.assertEqual(payload["messages"][1]["content"], "Inspect")
        self.assertEqual(payload["messages"][2]["tool_calls"][0]["function"]["name"], "exec_command")
        self.assertEqual(payload["messages"][3], {"role": "tool", "tool_call_id": "call-1", "content": "/tmp"})
        self.assertEqual({tool["function"]["name"] for tool in payload["tools"]}, {"exec_command", "mcp__node_repl__js"})
        self.assertEqual(payload["max_tokens"], 100)
        self.assertEqual(payload["reasoning_effort"], "medium")
        self.assertEqual(mapping["mcp__node_repl__js"], ("mcp__node_repl__", "js"))

    def test_custom_tool_calls_are_returned_in_codex_freeform_shape(self):
        events = []
        translator = local_adapter.ChatTranslator(
            lambda event, data: events.append((event, data)), {}, {"apply_patch"})
        translator.start("local-model")
        translator.tool_delta(0, {"id": "call-custom", "name": "apply_patch", "arguments": "{\"input\":\"*** Begin Patch"})
        translator.tool_delta(0, {"arguments": "\n*** End Patch\"}"})
        translator.finish("local-model")
        self.assertIn("response.custom_tool_call_input.done", [event for event, _ in events])
        completed = next(data for event, data in events if event == "response.completed")
        item = completed["response"]["output"][0]
        self.assertEqual(item["type"], "custom_tool_call")
        self.assertEqual(item["name"], "apply_patch")
        self.assertIn("*** Begin Patch", item["input"])

    def test_streamed_chat_response_becomes_responses_events_with_usage(self):
        events, raw = [], []
        starts = []
        body = {"model": "llama3.2:3b", "input": [{"type": "message", "role": "user", "content": "Hello"}]}
        status, sent, usage = local_adapter.run_chat(
            body, {"endpoint": self.endpoint, "protocol": "openai_chat"},
            lambda code, headers: starts.append((code, headers)),
            lambda event, data: events.append((event, data)),
            raw.append, lambda message: None, self.endpoint, {},
        )
        self.assertEqual(status, 200)
        self.assertGreater(sent, 0)
        self.assertEqual(starts[0][0], 200)
        self.assertIn("response.output_text.delta", [event for event, _ in events])
        completed = next(data for event, data in events if event == "response.completed")
        self.assertEqual(completed["response"]["usage"]["input_tokens"], 11)
        self.assertEqual(completed["response"]["usage"]["output_tokens"], 5)
        self.assertEqual(completed["response"]["usage"]["total_tokens"], 16)
        self.assertEqual(usage["total_tokens"], 16)
        self.assertEqual(_FakeLocal.requests[0]["body"]["messages"][0]["content"], "Hello")

    def test_loopback_responses_stream_captures_terminal_usage(self):
        starts, raw = [], []
        body = {"model": "llama3.2:3b", "input": "Hello", "stream": True}
        status, sent, usage = local_adapter.run_responses(
            body, {"endpoint": self.endpoint, "protocol": "openai_responses"},
            lambda code, headers: starts.append((code, headers)), raw.append,
            lambda message: None, self.endpoint, {},
        )
        self.assertEqual(status, 200)
        self.assertGreater(sent, 0)
        self.assertEqual(usage["total_tokens"], 11)
        self.assertIn(b"response.completed", b"".join(raw))
        self.assertEqual(_FakeLocal.requests[0]["path"], "/v1/responses")


if __name__ == "__main__":
    unittest.main()