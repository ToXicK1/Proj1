"""Provider contract (AGENT_ARCHITECTURE.md section 7). Adapters are the only code that knows vendor formats.

Every adapter returns a CompletionResult or raises ProviderError with a normalized kind. Callers
never see vendor status codes or payloads, and they never see a credential.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

ErrorKind = Literal[
    "auth", "rate_limited", "timeout", "unavailable", "invalid_request", "content_filtered", "bad_response"
]
RETRYABLE: frozenset[str] = frozenset({"rate_limited", "timeout", "unavailable"})
ADAPTER_TYPES: frozenset[str] = frozenset({"anthropic", "openai", "gemini", "openai_compatible", "mock"})


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    user: str
    model: str
    max_tokens: int = 1024
    temperature: float = 0.0
    timeout_seconds: float = 30.0
    # Called with ("text" | "thinking", chunk) as a streamed reply arrives. Adapters that cannot stream ignore it.
    on_delta: Callable[[str, str], None] | None = None
    # A conversation, for tool use: when given, it replaces system and user. Each entry is a chat message dict.
    messages: tuple[dict, ...] = ()
    tools: tuple[dict, ...] = ()  # OpenAI-style function definitions the model may call


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class CompletionResult:
    text: str
    usage: Usage
    model: str
    latency_ms: int
    thinking: str = ""  # reasoning the model reported separately from its answer, when it does
    tool_calls: tuple[dict, ...] = ()  # {"id", "name", "arguments"} the model asked for instead of answering


class ProviderError(Exception):
    def __init__(self, kind: ErrorKind, message: str = "") -> None:
        super().__init__(kind)
        self.kind = kind
        self.retryable = kind in RETRYABLE
        # Messages are short and never contain request bodies or credentials.
        self.message = message[:200]


class ProviderAdapter(Protocol):
    adapter_type: str

    def complete(self, request: CompletionRequest) -> CompletionResult: ...
