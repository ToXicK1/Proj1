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


def _send(client: httpx.Client, method: str, url: str, *, headers: dict[str, str], body: dict[str, Any] | None,
          timeout: float) -> dict[str, Any]:
    try:
        response = client.request(method, url, headers=headers, json=body, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError("timeout", type(exc).__name__) from exc
    except httpx.HTTPError as exc:
        raise ProviderError("unavailable", type(exc).__name__) from exc
    if response.status_code >= 400:
        raise ProviderError(_map_status(response.status_code), f"HTTP {response.status_code}")
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


@dataclass
class AnthropicAdapter(_Base):
    adapter_type: str = field(default="anthropic", init=False)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        url = f"{(self.base_url or ANTHROPIC_BASE).rstrip('/')}/v1/messages"
        headers = {"x-api-key": self.api_key or "", "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        body = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
        }
        started = time.perf_counter()
        data = _send(self.client, "POST", url, headers=headers, body=body, timeout=request.timeout_seconds)
        latency = int((time.perf_counter() - started) * 1000)
        if data.get("stop_reason") == "refusal":
            raise ProviderError("content_filtered", "refused")
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise _bad("missing content")
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        usage = data.get("usage") or {}
        return CompletionResult(
            text=text,
            usage=Usage(int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))),
            model=str(data.get("model", request.model)),
            latency_ms=latency,
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
        "messages": [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    started = time.perf_counter()
    data = _send(client, "POST", url, headers=headers, body=body, timeout=request.timeout_seconds)
    latency = int((time.perf_counter() - started) * 1000)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise _bad("missing choices")
    if choices[0].get("finish_reason") == "content_filter":
        raise ProviderError("content_filtered", "filtered")
    message = choices[0].get("message") or {}
    usage = data.get("usage") or {}
    return CompletionResult(
        text=str(message.get("content") or ""),
        usage=Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))),
        model=str(data.get("model", request.model)),
        latency_ms=latency,
    )


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
            text = json.dumps({key: f"{key} drafted from {len(request.user)} characters of input" for key in keys})
        return CompletionResult(
            text=text,
            usage=Usage(input_tokens=max(1, len(request.user) // 4), output_tokens=max(1, len(text) // 4)),
            model=request.model,
            latency_ms=1,
        )


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
