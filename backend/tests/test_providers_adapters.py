"""Adapters against mocked HTTP: request shape, response parsing and error normalization.

These tests prove the adapters build the documented requests and map the documented failures.
They do not prove that a live vendor accepts them; that needs real keys (see live tests, skipped).
"""

import json

import httpx
import pytest

from app.providers.adapters import build_adapter
from app.providers.base import CompletionRequest, ProviderError

REQ = CompletionRequest(system="Reply with JSON. KEYS: summary", user="hello", model="model-x", max_tokens=64)


def _transport(status: int, body, *, capture: list | None = None, raise_exc: Exception | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        if raise_exc is not None:
            raise raise_exc
        payload = body if isinstance(body, (dict, list)) else {"raw": body}
        return httpx.Response(status, json=payload if not isinstance(body, str) else None,
                              content=body.encode() if isinstance(body, str) else None)

    return httpx.MockTransport(handler)


def _adapter(adapter_type: str, transport, api_key="sk-test-1234567890", base_url=None):
    return build_adapter(adapter_type, api_key=api_key, base_url=base_url, transport=transport, app_env="test")


ANTHROPIC_OK = {"type": "message", "model": "model-x", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"summary": "ok"}'}],
                "usage": {"input_tokens": 11, "output_tokens": 7}}
OPENAI_OK = {"model": "model-x", "choices": [{"finish_reason": "stop",
                                              "message": {"role": "assistant", "content": '{"summary": "ok"}'}}],
             "usage": {"prompt_tokens": 12, "completion_tokens": 8}}
GEMINI_OK = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"summary": "ok"}'}]}}],
             "usageMetadata": {"promptTokenCount": 13, "candidatesTokenCount": 9}}


def test_anthropic_sends_documented_headers_and_parses_usage():
    seen: list = []
    result = _adapter("anthropic", _transport(200, ANTHROPIC_OK, capture=seen)).complete(REQ)
    request = seen[0]
    assert request.url == httpx.URL("https://api.anthropic.com/v1/messages")
    assert request.headers["x-api-key"] == "sk-test-1234567890"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["model"] == "model-x" and body["system"] == REQ.system
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert result.text == '{"summary": "ok"}'
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 7)


def test_openai_uses_bearer_auth_and_json_mode():
    seen: list = []
    result = _adapter("openai", _transport(200, OPENAI_OK, capture=seen)).complete(REQ)
    request = seen[0]
    assert request.url == httpx.URL("https://api.openai.com/v1/chat/completions")
    assert request.headers["authorization"] == "Bearer sk-test-1234567890"
    body = json.loads(request.content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": REQ.system}
    assert (result.usage.input_tokens, result.usage.output_tokens) == (12, 8)


def test_gemini_keeps_the_key_out_of_the_url():
    seen: list = []
    result = _adapter("gemini", _transport(200, GEMINI_OK, capture=seen)).complete(REQ)
    request = seen[0]
    assert request.url == httpx.URL("https://generativelanguage.googleapis.com/v1beta/models/model-x:generateContent")
    assert "key=" not in str(request.url)
    assert request.headers["x-goog-api-key"] == "sk-test-1234567890"
    assert json.loads(request.content)["generationConfig"]["responseMimeType"] == "application/json"
    assert result.text == '{"summary": "ok"}'


def test_openai_compatible_needs_a_base_url_and_works_without_a_key():
    seen: list = []
    adapter = _adapter("openai_compatible", _transport(200, OPENAI_OK, capture=seen), api_key=None,
                       base_url="http://localhost:11434/v1")
    adapter.complete(REQ)
    assert seen[0].url == httpx.URL("http://localhost:11434/v1/chat/completions")
    assert "authorization" not in seen[0].headers
    with pytest.raises(ProviderError) as exc:
        _adapter("openai_compatible", _transport(200, OPENAI_OK), api_key=None, base_url=None).complete(REQ)
    assert exc.value.kind == "invalid_request"


@pytest.mark.parametrize(
    ("status", "kind", "retryable"),
    [(401, "auth", False), (403, "auth", False), (429, "rate_limited", True), (400, "invalid_request", False),
     (500, "unavailable", True), (503, "unavailable", True), (418, "bad_response", False)],
)
@pytest.mark.parametrize("adapter_type", ["anthropic", "openai", "gemini"])
def test_http_failures_are_normalized(adapter_type, status, kind, retryable):
    with pytest.raises(ProviderError) as exc:
        _adapter(adapter_type, _transport(status, {"error": "vendor text with a secret-looking sk-abc"})).complete(REQ)
    assert exc.value.kind == kind
    assert exc.value.retryable is retryable
    assert "sk-abc" not in exc.value.message  # vendor bodies never reach callers


def test_timeouts_and_connection_failures_are_normalized():
    with pytest.raises(ProviderError) as exc:
        _adapter("openai", _transport(200, {}, raise_exc=httpx.ReadTimeout("slow"))).complete(REQ)
    assert exc.value.kind == "timeout" and exc.value.retryable
    with pytest.raises(ProviderError) as exc:
        _adapter("anthropic", _transport(200, {}, raise_exc=httpx.ConnectError("refused"))).complete(REQ)
    assert exc.value.kind == "unavailable"


def test_refusals_and_safety_blocks_are_content_filtered():
    refusal = {**ANTHROPIC_OK, "stop_reason": "refusal"}
    with pytest.raises(ProviderError) as exc:
        _adapter("anthropic", _transport(200, refusal)).complete(REQ)
    assert exc.value.kind == "content_filtered"
    filtered = {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}
    with pytest.raises(ProviderError) as exc:
        _adapter("openai", _transport(200, filtered)).complete(REQ)
    assert exc.value.kind == "content_filtered"
    blocked = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
    with pytest.raises(ProviderError) as exc:
        _adapter("gemini", _transport(200, blocked)).complete(REQ)
    assert exc.value.kind == "content_filtered"


def test_non_json_and_unexpected_shapes_are_bad_responses():
    with pytest.raises(ProviderError) as exc:
        _adapter("openai", _transport(200, "<html>gateway</html>")).complete(REQ)
    assert exc.value.kind == "bad_response"
    with pytest.raises(ProviderError) as exc:
        _adapter("anthropic", _transport(200, {"content": "not a list"})).complete(REQ)
    assert exc.value.kind == "bad_response"


def test_mock_adapter_is_refused_outside_development():
    with pytest.raises(ProviderError) as exc:
        build_adapter("mock", api_key=None, base_url=None, app_env="production")
    assert exc.value.kind == "invalid_request"


def test_mock_modes_are_deterministic():
    adapter = build_adapter("mock", api_key=None, base_url=None, app_env="test")
    first = adapter.complete(REQ)
    assert first.text == adapter.complete(REQ).text
    assert json.loads(first.text) == {"summary": "summary drafted from 5 characters of input"}
    with pytest.raises(ProviderError) as exc:
        build_adapter("mock", api_key=None, base_url="unavailable", app_env="test").complete(REQ)
    assert exc.value.kind == "unavailable"
