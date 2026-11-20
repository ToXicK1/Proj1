"""Correlation IDs: one ID follows a request into the jobs it starts, their logs and the audit events they write.

A caller may send `X-Request-ID`; it is used only if it is a short, plain token. Otherwise a new one is made.
"""

import logging
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "X-Request-ID"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_current: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_id() -> str:
    return uuid.uuid4().hex


def clean(value: str | None) -> str | None:
    """A caller-supplied ID is kept only when it cannot inject anything into logs or headers."""
    return value if value and _SAFE.fullmatch(value) else None


def current() -> str | None:
    return _current.get()


def bind(value: str | None) -> object:
    """Sets the ID for the current context and returns a token for `reset`."""
    return _current.set(value)


def reset(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]


class CorrelationMiddleware:
    """Pure ASGI middleware, so the ID is set before any route or dependency runs and survives streaming."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == b"x-request-id"),
                        None)
        cid = clean(supplied) or new_id()
        token = bind(cid)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"].append((HEADER.lower().encode(), cid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            reset(token)


class CorrelationFilter(logging.Filter):
    """Adds `correlation_id` to every log record so a formatter can print it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = current() or "-"
        return True


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(isinstance(f, CorrelationFilter) for h in root.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
