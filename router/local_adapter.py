"""Bridge Codex Responses requests to loopback OpenAI-compatible model servers.

Only endpoints accepted by settings.normalize_local_endpoint() are used. Relays
never forwards the caller's ChatGPT credential to a local server.
"""
from __future__ import annotations

import http.client
import json
import ssl
from typing import Any, Callable
from urllib.parse import urlsplit
import uuid

import credentials
import namespace_tools
import settings

SSL_CONTEXT = ssl.create_default_context()
FORWARD_HEADERS = {"content-type", "accept", "openai-beta", "originator", "session-id", "thread-id"}
SKIP_RESPONSE_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
                         "trailer", "transfer-encoding", "upgrade", "content-length", "content-encoding"}


def _connection(endpoint: str, suffix: str) -> tuple[http.client.HTTPConnection, str, str]:
    normalized = settings.normalize_local_endpoint(endpoint)
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = (parsed.path.rstrip("/") + suffix) or suffix
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=600, context=SSL_CONTEXT), path, normalized
    return http.client.HTTPConnection(host, port, timeout=600), path, normalized


def _auth_headers(local: dict[str, Any]) -> dict[str, str]:
    name = local.get("credential_env")
    if not name:
        return {}
    secret = credentials.get_secret(str(name))
    if not secret:
        raise credentials.CredentialError(f"{name} is not configured")
    return {"Authorization": "Bearer " + secret}


def discover(endpoint: str) -> list[dict[str, str]]:
    """List models exposed by a loopback OpenAI-compatible server."""
    connection, path, _ = _connection(endpoint, "/models")
    try:
        connection.request("GET", path, headers={"Accept": "application/json", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        payload = response.read(5_000_001)
        if response.status != 200:
            raise RuntimeError(f"Local model discovery returned HTTP {response.status}")
        if len(payload) > 5_000_000:
            raise RuntimeError("Local model discovery response is too large")
        document = json.loads(payload)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Could not reach the local model server: {type(exc).__name__}") from None
    finally:
        connection.close()
    items = document.get("data") if isinstance(document, dict) else None
    if not isinstance(items, list):
        items = document.get("models") if isinstance(document, dict) else document
    if not isinstance(items, list):
        raise RuntimeError("Local server returned an unsupported model list")
    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            model_id, name = item, item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
            name = item.get("display_name") or item.get("name") or model_id
        else:
            continue
        if not isinstance(model_id, str) or not model_id or len(model_id) > 200 or model_id in seen:
            continue
        seen.add(model_id)
        models.append({"id": model_id, "name": str(name or model_id)[:200]})
    return sorted(models, key=lambda item: item["name"].casefold())


def _content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[dict[str, Any]] = []
    for part in content:
        if isinstance(part, str):
            parts.append({"type": "text", "text": part})
            continue
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind in ("input_text", "output_text", "text"):
            text = part.get("text")
            if isinstance(text, str):
                parts.append({"type": "text", "text": text})
        elif kind in ("input_image", "image_url"):
            image = part.get("image_url")
            if isinstance(image, dict):
                image = image.get("url")
            if isinstance(image, str) and image:
                parts.append({"type": "image_url", "image_url": {"url": image}})
        elif kind == "refusal" and isinstance(part.get("refusal"), str):
            parts.append({"type": "text", "text": part["refusal"]})
    if not parts:
        return ""
    if all(part.get("type") == "text" for part in parts):
        return "\n".join(part["text"] for part in parts)
    return parts


def _tool_output(item: dict[str, Any]) -> str:
    output = item.get("output")
    if isinstance(output, str):
        return output
    if output is None:
        return ""
    return json.dumps(output, ensure_ascii=False)


def chat_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate Responses input items into Chat Completions messages."""
    messages: list[dict[str, Any]] = []
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages.append({"role": "system", "content": instructions})
    source = body.get("input")
    if isinstance(source, str):
        messages.append({"role": "user", "content": source})
        return messages
    if not isinstance(source, list):
        return messages

    last_assistant_tools: dict[str, Any] | None = None

    def add_tool_call(item: dict[str, Any]) -> None:
        nonlocal last_assistant_tools
        call_id = item.get("call_id") or item.get("id") or ("call_" + uuid.uuid4().hex)
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return
        if item.get("type") == "custom_tool_call":
            arguments = json.dumps({"input": item.get("input")}, ensure_ascii=False)
        else:
            arguments = item.get("arguments")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)
        call = {"id": str(call_id), "type": "function", "function": {"name": name, "arguments": arguments}}
        if last_assistant_tools is None:
            last_assistant_tools = {"role": "assistant", "content": None, "tool_calls": []}
            messages.append(last_assistant_tools)
        last_assistant_tools["tool_calls"].append(call)

    for item in source:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind in ("function_call", "custom_tool_call"):
            add_tool_call(item)
            continue
        if kind in ("function_call_output", "custom_tool_call_output", "tool_output"):
            call_id = item.get("call_id")
            if isinstance(call_id, str) and call_id:
                messages.append({"role": "tool", "tool_call_id": call_id, "content": _tool_output(item)})
            last_assistant_tools = None
            continue
        if kind == "reasoning":
            continue
        role = item.get("role")
        if role is None and kind == "message":
            role = "user"
        if role not in ("user", "assistant", "system", "developer"):
            continue
        messages.append({"role": "system" if role == "developer" else role,
                         "content": _content(item.get("content"))})
        last_assistant_tools = None
    return messages


def chat_tools(body: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict) or tool.get("type") not in ("function", "custom"):
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        definition: dict[str, Any] = {"name": name}
        description = tool.get("description")
        if isinstance(description, str) and description:
            definition["description"] = description
        parameters = tool.get("parameters")
        if isinstance(parameters, dict):
            definition["parameters"] = parameters
        elif tool.get("type") == "custom":
            definition["parameters"] = {
                "type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"],
            }
        else:
            definition["parameters"] = {"type": "object", "properties": {}}
        output.append({"type": "function", "function": definition})
    return output


def chat_payload(body: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": body.get("model"),
        "messages": chat_messages(body),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    tools = chat_tools(body)
    if tools:
        payload["tools"] = tools
        choice = body.get("tool_choice")
        if isinstance(choice, str) and choice in ("auto", "none", "required"):
            payload["tool_choice"] = choice
        elif isinstance(choice, dict) and isinstance(choice.get("name"), str):
            payload["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
    for source, target in (("max_output_tokens", "max_tokens"), ("temperature", "temperature"),
                           ("top_p", "top_p"), ("parallel_tool_calls", "parallel_tool_calls")):
        value = body.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            payload[target] = value
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and isinstance(reasoning.get("effort"), str):
        payload["reasoning_effort"] = reasoning["effort"]
    return payload


class ChatTranslator:
    """Translate streamed Chat Completions chunks into Responses API events."""

    def __init__(self, emit: Callable[[str, dict[str, Any]], None], mapping: dict[str, tuple[str, str]],
                 custom_names: set[str] | None = None):
        self.emit_raw = emit
        self.mapping = mapping
        self.custom_names = custom_names or set()
        self.response_id = "resp_" + uuid.uuid4().hex
        self.created_at = int(__import__("time").time())
        self.seq = 0
        self.next_index = 0
        self.output: list[dict[str, Any]] = []
        self.done: dict[int, dict[str, Any]] = {}
        self.text: dict[str, Any] | None = None
        self.tools: dict[int, dict[str, Any]] = {}
        self.usage: dict[str, Any] = {}
        self.finished = False

    def emit(self, event: str, data: dict[str, Any]) -> None:
        self.emit_raw(event, {"type": event, "sequence_number": self.seq, **data})
        self.seq += 1

    def response(self, model: str | None, status: str, output: list[dict[str, Any]] | None = None,
                 usage: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"id": self.response_id, "object": "response", "created_at": self.created_at,
                "status": status, "model": model, "output": output or [], "usage": usage,
                "error": None, "incomplete_details": None}

    def start(self, model: str) -> None:
        response = self.response(model, "in_progress")
        self.emit("response.created", {"response": response})
        self.emit("response.in_progress", {"response": response})

    def text_delta(self, text: str) -> None:
        if not text:
            return
        if self.text is None:
            output_index = self.next_index
            self.next_index += 1
            item_id = "msg_" + uuid.uuid4().hex
            item = {"type": "message", "id": item_id, "role": "assistant", "status": "in_progress", "content": []}
            self.text = {"output_index": output_index, "item_id": item_id, "text": "", "item": item}
            self.emit("response.output_item.added", {"output_index": output_index, "item": item})
            self.emit("response.content_part.added", {
                "item_id": item_id, "output_index": output_index, "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": [], "logprobs": []},
            })
        self.text["text"] += text
        self.emit("response.output_text.delta", {
            "item_id": self.text["item_id"], "output_index": self.text["output_index"],
            "content_index": 0, "delta": text, "logprobs": [],
        })

    def tool_delta(self, index: int, delta: dict[str, Any]) -> None:
        state = self.tools.get(index)
        if state is None:
            name = str(delta.get("name") or "tool_call")
            namespace, simple = self.mapping.get(name, (None, name))
            call_id = str(delta.get("id") or ("call_" + uuid.uuid4().hex))
            kind = "custom" if name in self.custom_names and not namespace else "function"
            item_id = ("ctc_" if kind == "custom" else "fc_") + uuid.uuid4().hex
            if kind == "custom":
                item: dict[str, Any] = {"type": "custom_tool_call", "id": item_id, "call_id": call_id,
                                        "name": name, "input": "", "status": "in_progress"}
            else:
                item = {"type": "function_call", "id": item_id, "call_id": call_id,
                        "name": simple, "arguments": "", "status": "in_progress"}
                if namespace:
                    item["namespace"] = namespace
            output_index = self.next_index
            self.next_index += 1
            state = {"output_index": output_index, "item_id": item_id, "kind": kind,
                     "name": name, "raw": "", "item": item}
            self.tools[index] = state
            self.emit("response.output_item.added", {"output_index": state["output_index"], "item": item})
        arguments = delta.get("arguments")
        if isinstance(arguments, str) and arguments:
            state["raw"] += arguments
            if state["kind"] == "function":
                self.emit("response.function_call_arguments.delta", {
                    "item_id": state["item_id"], "output_index": state["output_index"], "delta": arguments,
                })

    def consume(self, data: dict[str, Any]) -> None:
        usage = data.get("usage")
        if isinstance(usage, dict):
            self.usage = usage
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            delta = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = delta.get("content")
        if isinstance(content, str):
            self.text_delta(content)
        elif isinstance(content, list):
            self.text_delta("".join(str(part.get("text") or "") for part in content if isinstance(part, dict)))
        calls = delta.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if isinstance(call, dict):
                    self.tool_delta(int(call.get("index") or 0), call)

    def finish(self, model: str) -> None:
        if self.finished:
            return
        self.finished = True
        if self.text is not None:
            text = self.text["text"]
            item = self.text["item"]
            part = {"type": "output_text", "text": text, "annotations": [], "logprobs": []}
            self.emit("response.output_text.done", {
                "item_id": self.text["item_id"], "output_index": self.text["output_index"],
                "content_index": 0, "text": text, "logprobs": [],
            })
            self.emit("response.content_part.done", {
                "item_id": self.text["item_id"], "output_index": self.text["output_index"],
                "content_index": 0, "part": part,
            })
            item.update({"status": "completed", "content": [part]})
            self.emit("response.output_item.done", {"output_index": self.text["output_index"], "item": item})
            self.done[self.text["output_index"]] = item
        for index in sorted(self.tools):
            state = self.tools[index]
            arguments = state["raw"] or "{}"
            item = state["item"]
            if state["kind"] == "custom":
                try:
                    parsed = json.loads(arguments) if arguments.strip() else {}
                except ValueError:
                    parsed = {"input": arguments}
                value = parsed.get("input") if isinstance(parsed, dict) else arguments
                if not isinstance(value, str):
                    value = json.dumps(value, ensure_ascii=False)
                self.emit("response.custom_tool_call_input.delta", {
                    "item_id": state["item_id"], "output_index": state["output_index"], "delta": value,
                })
                self.emit("response.custom_tool_call_input.done", {
                    "item_id": state["item_id"], "output_index": state["output_index"], "input": value,
                })
                item.update({"status": "completed", "input": value})
            else:
                self.emit("response.function_call_arguments.done", {
                    "item_id": state["item_id"], "output_index": state["output_index"], "arguments": arguments,
                })
                item.update({"status": "completed", "arguments": arguments})
            self.emit("response.output_item.done", {"output_index": state["output_index"], "item": item})
            self.done[state["output_index"]] = item
        self.output = [self.done[index] for index in sorted(self.done)]
        usage = None
        if self.usage:
            input_tokens = int(self.usage.get("prompt_tokens") or self.usage.get("input_tokens") or 0)
            output_tokens = int(self.usage.get("completion_tokens") or self.usage.get("output_tokens") or 0)
            usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                     "total_tokens": int(self.usage.get("total_tokens") or input_tokens + output_tokens)}
            prompt_details = self.usage.get("prompt_tokens_details")
            if isinstance(prompt_details, dict):
                usage["input_tokens_details"] = prompt_details
            completion_details = self.usage.get("completion_tokens_details")
            if isinstance(completion_details, dict):
                usage["output_tokens_details"] = completion_details
        self.emit("response.completed", {"response": self.response(model, "completed", self.output, usage)})

    def fail(self, model: str, message: str) -> None:
        if self.finished:
            return
        self.finished = True
        response = self.response(model, "failed", self.output, None)
        response["error"] = {"code": "local_upstream_error", "message": message}
        self.emit("response.failed", {"response": response})


def run_chat(body: dict[str, Any], local: dict[str, Any],
             start: Callable[[int, list[tuple[str, str]]], None],
             emit: Callable[[str, dict[str, Any]], None], write_raw: Callable[[bytes], None],
             log: Callable[[str], None], endpoint: str,
             mapping: dict[str, tuple[str, str]]) -> tuple[int, int, dict[str, Any]]:
    connection, path, _ = _connection(endpoint, "/chat/completions")
    payload = chat_payload(body)
    raw = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json",
               "Accept-Encoding": "identity"}
    custom_names = {str(tool.get("name")) for tool in body.get("tools") or []
                    if isinstance(tool, dict) and tool.get("type") == "custom" and tool.get("name")}
    translator = ChatTranslator(emit, mapping, custom_names)
    sent = 0
    response_started = False
    model = str(body.get("model") or "")
    try:
        headers.update(_auth_headers(local))
        connection.request("POST", path, body=raw, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            error = response.read(2_000_001)
            if len(error) > 2_000_000:
                error = json.dumps({"error": {"message": "Local server error response is too large"}}).encode()
            start(response.status, [("Content-Type", "application/json"), ("Content-Length", str(len(error)))])
            write_raw(error)
            return response.status, len(error), {}
        content_type = (response.getheader("Content-Type") or "").lower()
        if "application/json" in content_type and "text/event-stream" not in content_type:
            document = json.loads(response.read(10_000_001))
            sent = len(json.dumps(document, ensure_ascii=False).encode())
            start(200, [("Content-Type", "text/event-stream; charset=utf-8")])
            translator.start(model)
            translator.consume(document)
            translator.finish(model)
            return 200, sent, dict(translator.usage)
        start(200, [("Content-Type", "text/event-stream; charset=utf-8")])
        response_started = True
        translator.start(model)
        buffer = b""
        done = False
        while not done:
            chunk = response.read1(65536)
            if not chunk:
                break
            sent += len(chunk)
            buffer = (buffer + chunk).replace(b"\r\n", b"\n")
            while b"\n\n" in buffer:
                block, buffer = buffer.split(b"\n\n", 1)
                data_lines = []
                for line in block.replace(b"\r\n", b"\n").split(b"\n"):
                    if line.startswith(b"data:"):
                        data_lines.append(line[5:].lstrip())
                if not data_lines:
                    continue
                data_text = b"\n".join(data_lines).decode("utf-8", "replace").strip()
                if data_text == "[DONE]":
                    done = True
                    break
                try:
                    document = json.loads(data_text)
                except ValueError:
                    continue
                if not isinstance(document, dict):
                    continue
                if isinstance(document.get("error"), dict):
                    translator.fail(model, str(document["error"].get("message") or "Local server returned an error"))
                    done = True
                    break
                translator.consume(document)
        if not translator.finished:
            translator.finish(model)
        return 200, sent, dict(translator.usage)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        log(f"ERROR local chat: {exc!r}")
        try:
            if response_started:
                translator.fail(model, f"Local model bridge failed: {type(exc).__name__}")
            else:
                error = json.dumps({"error": {"message": f"Local model bridge failed: {type(exc).__name__}"}}).encode()
                start(502, [("Content-Type", "application/json"), ("Content-Length", str(len(error)))])
                write_raw(error)
        except Exception:
            pass
        return 502, sent, dict(translator.usage)
    finally:
        connection.close()

class ResponsesUsageScanner:
    def __init__(self) -> None:
        self.buffer = b""
        self.usage: dict[str, Any] = {}

    def _consume_document(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        response = data.get("response") if isinstance(data.get("response"), dict) else data
        usage = response.get("usage") if isinstance(response, dict) else None
        if isinstance(usage, dict):
            self.usage = usage

    def feed(self, chunk: bytes) -> None:
        self.buffer = (self.buffer + chunk).replace(b"\r\n", b"\n")
        while b"\n\n" in self.buffer:
            block, self.buffer = self.buffer.split(b"\n\n", 1)
            for line in block.replace(b"\r\n", b"\n").split(b"\n"):
                if line.startswith(b"data:"):
                    try:
                        self._consume_document(json.loads(line[5:].lstrip()))
                    except ValueError:
                        pass

    def flush(self) -> None:
        if self.buffer:
            for line in self.buffer.replace(b"\r\n", b"\n").split(b"\n"):
                if line.startswith(b"data:"):
                    try:
                        self._consume_document(json.loads(line[5:].lstrip()))
                    except ValueError:
                        pass
            self.buffer = b""


def run_responses(body: dict[str, Any], local: dict[str, Any],
                  start: Callable[[int, list[tuple[str, str]]], None],
                  write_raw: Callable[[bytes], None], log: Callable[[str], None],
                  endpoint: str, mapping: dict[str, tuple[str, str]]) -> tuple[int, int, dict[str, Any]]:
    """Proxy a loopback standard Responses stream and collect terminal usage."""
    connection, path, _ = _connection(endpoint, "/responses")
    raw = json.dumps(body, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json",
               "Accept-Encoding": "identity"}
    scanner = ResponsesUsageScanner()
    rewriter = namespace_tools.SseRewriter(mapping)
    sent = 0
    response_started = False
    try:
        headers.update(_auth_headers(local))
        connection.request("POST", path, body=raw, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            error = response.read(2_000_001)
            if len(error) > 2_000_000:
                error = json.dumps({"error": {"message": "Local server error response is too large"}}).encode()
            start(response.status, [("Content-Type", "application/json"), ("Content-Length", str(len(error)))])
            write_raw(error)
            return response.status, len(error), {}
        content_type = response.getheader("Content-Type") or "text/event-stream"
        safe_headers = [(key, value) for key, value in response.getheaders() if key.lower() not in SKIP_RESPONSE_HEADERS]
        if "application/json" in content_type.lower() and "text/event-stream" not in content_type.lower():
            payload = response.read(10_000_001)
            sent = len(payload)
            try:
                scanner._consume_document(json.loads(payload))
            except ValueError:
                pass
            safe_headers.append(("Content-Length", str(len(payload))))
            start(response.status, safe_headers)
            response_started = True
            write_raw(payload)
            return response.status, sent, dict(scanner.usage)
        start(response.status, safe_headers)
        response_started = True
        while True:
            chunk = response.read1(65536)
            if not chunk:
                break
            sent += len(chunk)
            scanner.feed(chunk)
            rewritten = rewriter.feed(chunk)
            if rewritten:
                write_raw(rewritten)
        tail = rewriter.flush()
        if tail:
            write_raw(tail)
        scanner.flush()
        return response.status, sent, dict(scanner.usage)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        log(f"ERROR local responses: {exc!r}")
        try:
            if not response_started:
                error = json.dumps({"error": {"message": f"Local model bridge failed: {type(exc).__name__}"}}).encode()
                start(502, [("Content-Type", "application/json"), ("Content-Length", str(len(error)))])
                write_raw(error)
        except Exception:
            pass
        return 502, sent, dict(scanner.usage)
    finally:
        connection.close()
