"""Vendor adapters. Each builds one HTTP request, parses one response, and maps failures to ProviderError.

Official endpoints and headers as documented by each vendor:
- Anthropic Messages API: POST /v1/messages, header x-api-key and anthropic-version
- OpenAI Chat Completions: POST /v1/chat/completions, Bearer token, response_format json_object
- Gemini generateContent: POST /v1beta/models/{model}:generateContent, header x-goog-api-key
- OpenAI-compatible servers (vLLM, Ollama, LM Studio, ...): same shape as OpenAI at a base URL

The mock adapter is deterministic and offline. It is refused outside development and test.
The HTTP client is injectable so tests can use httpx.MockTransport.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.providers.base import CompletionRequest, CompletionResult, ProviderError, Usage

ANTHROPIC_BASE = "https://api.anthropic.com"
OPENAI_BASE = "https://api.openai.com/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _map_status(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if status in (400, 404, 413, 422):
        return "invalid_request"
    if status >= 500:
        return "unavailable"
    return "bad_response"


QUOTA_MARKERS = ("enforced_spend_limit_reached", "insufficient_quota", "billing_error", "credit balance",
                 "exceeded your current quota", "billing_hard_limit_reached")


def http_error(response: httpx.Response) -> ProviderError:
    """Maps a failed response to a normalized error. Out-of-credit and spend-cap answers are told apart from
    ordinary rate limits (some providers send both as 429), because retrying cannot fix them. Vendor text is
    read only to classify; it never reaches callers."""
    status = response.status_code
    try:
        body = response.read().decode("utf-8", "replace").lower()[:4000]
    except Exception:  # noqa: BLE001 - classification only
        body = ""
    retry_after = None
    try:
        retry_after = float(response.headers["retry-after"]) if "retry-after" in response.headers else None
    except ValueError:
        retry_after = None
    if status == 402 or (status in (400, 403, 429) and any(m in body for m in QUOTA_MARKERS)):
        return ProviderError("quota_exhausted", f"HTTP {status}")
    return ProviderError(_map_status(status), f"HTTP {status}", retry_after)


def _send(client: httpx.Client, method: str, url: str, *, headers: dict[str, str], body: dict[str, Any] | None,
          timeout: float) -> dict[str, Any]:
    try:
        response = client.request(method, url, headers=headers, json=body, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError("timeout", type(exc).__name__) from exc
    except httpx.HTTPError as exc:
        raise ProviderError("unavailable", type(exc).__name__) from exc
    if response.status_code >= 400:
        raise http_error(response)
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError("bad_response", "response is not JSON") from exc
    if not isinstance(data, dict):
        raise ProviderError("bad_response", "unexpected response shape")
    return data


def _bad(message: str) -> ProviderError:
    return ProviderError("bad_response", message)


@dataclass
class _Base:
    client: httpx.Client
    api_key: str | None = None
    base_url: str | None = None
    adapter_type: str = field(default="", init=False)


# Claude models that think adaptively and reject sampling parameters (current API, see the claude-api reference)
_CLAUDE_ADAPTIVE = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable-5", "claude-mythos-5")


def _claude_messages(request: CompletionRequest) -> list[dict[str, Any]]:
    """Our conversation (OpenAI-shaped, provider-neutral) in Claude's shape. Tool results go back together in one
    user turn; an assistant turn that used tools is replayed with Claude's own blocks when we have them."""
    if not request.messages:
        return [{"role": "user", "content": request.user}]
    out: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    def flush() -> None:
        if results:
            out.append({"role": "user", "content": list(results)})
            results.clear()

    for m in request.messages:
        role = m.get("role")
        if role == "system":
            continue
        if role == "tool":
            results.append({"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": str(m.get("content", ""))})
            continue
        flush()
        if role == "assistant":
            native = m.get("_native_anthropic")
            if native:
                out.append({"role": "assistant", "content": list(native)})
                continue
            blocks: list[dict[str, Any]] = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for call in m.get("tool_calls") or []:
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except ValueError:
                    args = {}
                blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": args})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        else:
            out.append({"role": "user", "content": str(m.get("content", ""))})
    flush()
    return out


def _claude_body(request: CompletionRequest) -> dict[str, Any]:
    adaptive = request.model.startswith(_CLAUDE_ADAPTIVE)
    body: dict[str, Any] = {
        "model": request.model,
        # Reasoning shares the output budget on these models, so leave room for it; unused tokens cost nothing.
        "max_tokens": max(request.max_tokens, 16000) if adaptive else request.max_tokens,
        # The instructions repeat on every call of an agent: cache them. Top-level caching also covers the
        # growing conversation during tool use. Cached input is billed at about a tenth of the normal price.
        "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
        "cache_control": {"type": "ephemeral"},
        "messages": _claude_messages(request),
    }
    if adaptive:
        body["thinking"] = {"type": "adaptive", "display": "summarized"}  # a readable summary for the activity log
    else:
        body["temperature"] = request.temperature
    if request.tools:
        body["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                          "input_schema": t["function"]["parameters"]} for t in request.tools]
    return body


def _claude_result(blocks: list[dict[str, Any]], usage: dict[str, Any], model: str, stop_reason: str | None,
                   latency: int) -> CompletionResult:
    if stop_reason == "refusal":
        raise ProviderError("content_filtered", "refused")
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    thinking = "".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking")
    calls = tuple({"id": str(b["id"]), "name": str(b["name"]), "arguments": json.dumps(b.get("input") or {})}
                  for b in blocks if b.get("type") == "tool_use")
    return CompletionResult(
        text=text,
        usage=Usage(int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)),
                    int(usage.get("cache_read_input_tokens") or 0), int(usage.get("cache_creation_input_tokens") or 0)),
        model=model, latency_ms=latency, thinking=thinking, tool_calls=calls,
        native_content=tuple(blocks) if calls else (),
    )


@dataclass
class AnthropicAdapter(_Base):
    adapter_type: str = field(default="anthropic", init=False)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        url = f"{(self.base_url or ANTHROPIC_BASE).rstrip('/')}/v1/messages"
        headers = {"x-api-key": self.api_key or "", "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        body = _claude_body(request)
        started = time.perf_counter()
        if request.on_delta is not None:
            return self._stream(url, headers, {**body, "stream": True}, request, started)
        data = _send(self.client, "POST", url, headers=headers, body=body, timeout=request.timeout_seconds)
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise _bad("missing content")
        return _claude_result([b for b in blocks if isinstance(b, dict)], data.get("usage") or {},
                              str(data.get("model", request.model)), data.get("stop_reason"),
                              int((time.perf_counter() - started) * 1000))

    def _stream(self, url: str, headers: dict[str, str], body: dict[str, Any], request: CompletionRequest,
                started: float) -> CompletionResult:
        """Claude's server-sent events: text and reasoning are reported as they arrive; tool arguments are
        collected until each tool block ends."""
        emit = request.on_delta
        assert emit is not None
        blocks: dict[int, dict[str, Any]] = {}
        partial: dict[int, str] = {}
        usage: dict[str, Any] = {}
        stop_reason = None
        model = request.model
        try:
            with self.client.stream("POST", url, headers=headers, json=body,
                                    timeout=request.timeout_seconds) as response:
                if response.status_code >= 400:
                    raise http_error(response)
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    response.read()
                    try:
                        data = response.json()
                    except ValueError as exc:
                        raise ProviderError("bad_response", "response is not JSON") from exc
                    result = _claude_result([b for b in data.get("content") or [] if isinstance(b, dict)],
                                            data.get("usage") or {}, str(data.get("model", model)),
                                            data.get("stop_reason"), int((time.perf_counter() - started) * 1000))
                    if result.thinking:
                        emit("thinking", result.thinking)
                    if result.text:
                        emit("text", result.text)
                    return result
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    kind = event.get("type")
                    if kind == "error":
                        message = json.dumps(event.get("error") or {}).lower()
                        if any(m in message for m in QUOTA_MARKERS):
                            raise ProviderError("quota_exhausted", "stream error")
                        raise ProviderError("rate_limited" if "rate_limit" in message else "unavailable",
                                            "stream error")
                    if kind == "message_start":
                        message = event.get("message") or {}
                        model = str(message.get("model") or model)
                        usage.update(message.get("usage") or {})
                    elif kind == "content_block_start":
                        index = int(event.get("index", len(blocks)))
                        blocks[index] = dict(event.get("content_block") or {})
                        if blocks[index].get("type") == "tool_use":
                            blocks[index]["input"] = {}
                            partial[index] = ""
                    elif kind == "content_block_delta":
                        index = int(event.get("index", 0))
                        delta = event.get("delta") or {}
                        block = blocks.setdefault(index, {"type": "text", "text": ""})
                        if delta.get("type") == "text_delta":
                            block["text"] = block.get("text", "") + delta.get("text", "")
                            emit("text", delta.get("text", ""))
                        elif delta.get("type") == "thinking_delta":
                            block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
                            emit("thinking", delta.get("thinking", ""))
                        elif delta.get("type") == "signature_delta":
                            block["signature"] = block.get("signature", "") + delta.get("signature", "")
                        elif delta.get("type") == "input_json_delta":
                            partial[index] = partial.get(index, "") + delta.get("partial_json", "")
                    elif kind == "content_block_stop":
                        index = int(event.get("index", 0))
                        if index in partial:
                            try:
                                blocks[index]["input"] = json.loads(partial.pop(index) or "{}")
                            except ValueError:
                                blocks[index]["input"] = {}
                    elif kind == "message_delta":
                        stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
                        usage.update({k: v for k, v in (event.get("usage") or {}).items() if v is not None})
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", type(exc).__name__) from exc
        return _claude_result([blocks[i] for i in sorted(blocks)], usage, model, stop_reason,
                              int((time.perf_counter() - started) * 1000))


class ThinkSplitter:
    """Separates <think>...</think> reasoning from the answer in streamed text, even when a tag is split."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.inside = False
        self.pending = ""

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self.pending += chunk
        out: list[tuple[str, str]] = []
        while self.pending:
            tag = self.CLOSE if self.inside else self.OPEN
            at = self.pending.find(tag)
            if at >= 0:
                if at:
                    out.append(("thinking" if self.inside else "text", self.pending[:at]))
                self.pending = self.pending[at + len(tag):]
                self.inside = not self.inside
                continue
            keep = next((n for n in range(len(tag) - 1, 0, -1) if self.pending.endswith(tag[:n])), 0)
            ready = self.pending[:len(self.pending) - keep]
            if ready:
                out.append(("thinking" if self.inside else "text", ready))
            self.pending = self.pending[len(ready):]
            break
        return out

    def flush(self) -> list[tuple[str, str]]:
        rest, self.pending = self.pending, ""
        return [("thinking" if self.inside else "text", rest)] if rest else []


def _stream_chat(client: httpx.Client, url: str, headers: dict[str, str], body: dict[str, Any],
                 request: CompletionRequest) -> CompletionResult:
    """Streams a chat completion (server-sent events), reporting text and reasoning as they arrive."""
    emit = request.on_delta
    assert emit is not None
    body = {**body, "stream": True, "stream_options": {"include_usage": True}}
    started = time.perf_counter()
    text: list[str] = []
    thinking: list[str] = []
    usage: dict[str, Any] = {}
    model = request.model
    splitter = ThinkSplitter()
    calls: dict[int, dict[str, str]] = {}

    def deliver(parts: list[tuple[str, str]]) -> None:
        for kind, piece in parts:
            (thinking if kind == "thinking" else text).append(piece)
            emit(kind, piece)

    try:
        with client.stream("POST", url, headers=headers, json=body, timeout=request.timeout_seconds) as response:
            if response.status_code >= 400:
                raise http_error(response)
            if "text/event-stream" not in response.headers.get("content-type", ""):
                response.read()  # the server answered without streaming: use the whole reply
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ProviderError("bad_response", "response is not JSON") from exc
                result = _parse_chat(data, request, int((time.perf_counter() - started) * 1000))
                deliver([("thinking", result.thinking)] if result.thinking else [])
                deliver(splitter.feed(result.text) + splitter.flush())
                return CompletionResult(text="".join(text), usage=result.usage, model=result.model,
                                        latency_ms=result.latency_ms, thinking="".join(thinking),
                                        tool_calls=result.tool_calls)
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                model = str(chunk.get("model") or model)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    if choice.get("finish_reason") == "content_filter":
                        raise ProviderError("content_filtered", "filtered")
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                    if reasoning:
                        deliver([("thinking", str(reasoning))])
                    if delta.get("content"):
                        deliver(splitter.feed(str(delta["content"])))
                    for part in delta.get("tool_calls") or []:
                        slot = calls.setdefault(int(part.get("index", len(calls))), {"id": "", "name": "", "arguments": ""})
                        fn = part.get("function") or {}
                        slot["id"] = part.get("id") or slot["id"]
                        slot["name"] += fn.get("name") or ""
                        args = fn.get("arguments")
                        slot["arguments"] += args if isinstance(args, str) else json.dumps(args) if args else ""
            deliver(splitter.flush())
    except httpx.TimeoutException as exc:
        raise ProviderError("timeout", type(exc).__name__) from exc
    except httpx.HTTPError as exc:
        raise ProviderError("unavailable", type(exc).__name__) from exc
    return CompletionResult(
        text="".join(text),
        usage=Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))),
        model=model, latency_ms=int((time.perf_counter() - started) * 1000), thinking="".join(thinking),
        tool_calls=tuple({"id": c["id"] or f"call_{i}", "name": c["name"], "arguments": c["arguments"] or "{}"}
                         for i, c in sorted(calls.items())))


def _parse_chat(data: dict[str, Any], request: CompletionRequest, latency: int) -> CompletionResult:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise _bad("missing choices")
    if choices[0].get("finish_reason") == "content_filter":
        raise ProviderError("content_filtered", "filtered")
    message = choices[0].get("message") or {}
    usage = data.get("usage") or {}
    calls = tuple({"id": str(c.get("id") or f"call_{i}"), "name": str((c.get("function") or {}).get("name", "")),
                   "arguments": (c.get("function") or {}).get("arguments") or "{}"}
                  for i, c in enumerate(message.get("tool_calls") or []) if isinstance(c, dict))
    return CompletionResult(
        text=str(message.get("content") or ""),
        usage=Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))),
        model=str(data.get("model", request.model)),
        latency_ms=latency,
        thinking=str(message.get("reasoning") or message.get("reasoning_content") or ""),
        tool_calls=tuple({**c, "arguments": c["arguments"] if isinstance(c["arguments"], str)
                          else json.dumps(c["arguments"])} for c in calls),
    )


def _chat_completions(
    client: httpx.Client, base: str, api_key: str | None, request: CompletionRequest, *, json_mode: bool
) -> CompletionResult:
    url = f"{base.rstrip('/')}/chat/completions"
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    body: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
        "messages": [{k: v for k, v in m.items() if not k.startswith("_")} for m in request.messages] or [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ],
    }
    if request.tools:
        body["tools"] = list(request.tools)
    if json_mode and not request.tools:
        body["response_format"] = {"type": "json_object"}
    if request.on_delta is not None:
        return _stream_chat(client, url, headers, body, request)
    started = time.perf_counter()
    data = _send(client, "POST", url, headers=headers, body=body, timeout=request.timeout_seconds)
    return _parse_chat(data, request, int((time.perf_counter() - started) * 1000))


@dataclass
class OpenAIAdapter(_Base):
    adapter_type: str = field(default="openai", init=False)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return _chat_completions(self.client, self.base_url or OPENAI_BASE, self.api_key, request, json_mode=True)


@dataclass
class OpenAICompatibleAdapter(_Base):
    adapter_type: str = field(default="openai_compatible", init=False)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        if not self.base_url:
            raise ProviderError("invalid_request", "base_url is required")
        return _chat_completions(self.client, self.base_url, self.api_key, request, json_mode=False)


@dataclass
class GeminiAdapter(_Base):
    adapter_type: str = field(default="gemini", init=False)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        base = (self.base_url or GEMINI_BASE).rstrip("/")
        url = f"{base}/models/{request.model}:generateContent"
        headers = {"x-goog-api-key": self.api_key or "", "content-type": "application/json"}
        body = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
                "responseMimeType": "application/json",
            },
        }
        started = time.perf_counter()
        data = _send(self.client, "POST", url, headers=headers, body=body, timeout=request.timeout_seconds)
        latency = int((time.perf_counter() - started) * 1000)
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise _bad("missing candidates")
        if candidates[0].get("finishReason") in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise ProviderError("content_filtered", "filtered")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
        usage = data.get("usageMetadata") or {}
        return CompletionResult(
            text=text,
            usage=Usage(int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0))),
            model=request.model,
            latency_ms=latency,
        )


_MOCK_PROJECT = [
    {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
    {"path": "test_calc.py", "content": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
]


@dataclass
class MockAdapter(_Base):
    """Deterministic, offline. base_url selects the behaviour: 'ok', 'unavailable', 'auth',
    'rate_limited', 'bad_json', 'missing_keys', or 'filtered'. Used by CI and local demos."""

    adapter_type: str = field(default="mock", init=False)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        mode = self.base_url or "ok"
        if mode == "unavailable":
            raise ProviderError("unavailable", "mock outage")
        if mode == "auth":
            raise ProviderError("auth", "mock credentials rejected")
        if mode == "rate_limited":
            raise ProviderError("rate_limited", "mock limit")
        if mode == "filtered":
            raise ProviderError("content_filtered", "mock filter")
        keys = _requested_keys(request.system)
        if mode == "bad_json":
            text = "Sure! Here is the answer, not JSON."
        elif mode == "missing_keys":
            text = json.dumps({"unrelated": True})
        else:
            lists = _mock_lists(request.system)
            if list(keys) == ["verdict", "findings"] and "findings" not in lists:
                text = json.dumps({"verdict": "pass", "findings": []})
            else:
                text = json.dumps({key: _MOCK_PROJECT if key == "source_files" else lists[key] if key in lists
                                   else f"{key} drafted from {len(request.user)} characters of input" for key in keys})
        return CompletionResult(
            text=text,
            usage=Usage(input_tokens=max(1, len(request.user) // 4), output_tokens=max(1, len(text) // 4)),
            model=request.model,
            latency_ms=1,
        )


_LIST_SPEC = re.compile(r"(\w+) must be a JSON list of objects, each with a short title and: (.*?)\.(?= \w+ must be|$)",
                        re.MULTILINE)


_PLAIN_LISTS = re.compile(r"as JSON lists of short texts, \[\] when nothing applies: ([a-z_, ]+)\.")


def _mock_lists(system: str) -> dict[str, list[dict[str, Any]]]:
    """For record steps, one example object per list, built from the field description the step gives (offline)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for key, fields in _LIST_SPEC.findall(system):
        item: dict[str, Any] = {"title": f"Example {key.replace('_', ' ')} (offline mock)"}
        for part in fields.split(", "):
            name = part.split(" ", 1)[0]
            if " one of " in part:
                item[name] = part.split(" one of ", 1)[1].split("/")[0]
            elif "as a list of texts" in part:
                item[name] = [f"{name.replace('_', ' ')} (offline mock)"]
            elif "(required)" in part:
                item[name] = f"{name.replace('_', ' ')} written by the offline mock"
        out[key] = [item]
    plain = _PLAIN_LISTS.search(system)  # "these as JSON lists of short texts, [] when nothing applies: a, b."
    if plain:
        for key in (k.strip() for k in plain.group(1).split(",")):
            if key:
                out.setdefault(key, [f"{key.replace('_', ' ')} noted by the offline mock"])
    return out


def _requested_keys(system: str) -> list[str]:
    marker = "KEYS:"
    if marker not in system:
        return ["summary"]
    tail = system.split(marker, 1)[1].strip().splitlines()[0]
    return [k.strip() for k in tail.split(",") if k.strip()]


def build_adapter(adapter_type: str, *, api_key: str | None, base_url: str | None,
                  transport: httpx.BaseTransport | None = None, app_env: str = "production") -> Any:
    client = httpx.Client(transport=transport) if transport is not None else httpx.Client()
    if adapter_type == "anthropic":
        return AnthropicAdapter(client=client, api_key=api_key, base_url=base_url)
    if adapter_type == "openai":
        return OpenAIAdapter(client=client, api_key=api_key, base_url=base_url)
    if adapter_type == "gemini":
        return GeminiAdapter(client=client, api_key=api_key, base_url=base_url)
    if adapter_type == "openai_compatible":
        return OpenAICompatibleAdapter(client=client, api_key=api_key, base_url=base_url)
    if adapter_type == "mock":
        if app_env not in ("development", "test"):
            raise ProviderError("invalid_request", "mock provider is not available in this environment")
        return MockAdapter(client=client, api_key=api_key, base_url=base_url)
    raise ProviderError("invalid_request", f"unknown adapter '{adapter_type}'")
