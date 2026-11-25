"""Phase 1d: live workspace events. Producers append events with their own transaction; the project team follows them
over a WebSocket (or REST to catch up); clients, other origins and anyone not signed in are refused."""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.db import make_session_factory
from app.execution import executor
from tests.test_executor import FakeDocker
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _setup, _signed_in

JOB = {"kind": "checks", "payload": {"files": [{"path": "a.py", "content": "x = 1\n"}]}}


def _ready(managed, engine):  # noqa: F811
    _, _, _, project, people = _setup(managed, engine)
    analyst, ah = _signed_in(managed, people["analyst"])
    return f"/api/v1/projects/{project}", analyst, ah, people


def test_the_team_follows_an_execution_live_over_a_websocket(managed, engine):  # noqa: F811
    base, analyst, ah, _ = _ready(managed, engine)
    with analyst.websocket_connect(f"{base}/events/ws") as socket:
        job = analyst.post(f"{base}/executions", headers=ah, json=JOB).json()
        queued = socket.receive_json()
        assert queued["type"] == "events" and [e["kind"] for e in queued["items"]] == ["execution.queued"]
        assert queued["items"][0]["subject"] == job["id"] and queued["items"][0]["actor"].startswith("user:")
        factory = make_session_factory(engine)
        assert executor.claim(factory, "test-executor") is not None
        executor.process(factory, FakeDocker(), executor.uuid.UUID(job["id"]))
        followed: list[dict] = []
        while not followed or followed[-1]["kind"] != "execution.finished":  # one batch or two, as they commit
            followed += socket.receive_json()["items"]
        assert [e["kind"] for e in followed] == ["execution.started", "execution.finished"]
        finished = followed[-1]
        assert finished["data"]["status"] == "succeeded" and finished["data"]["summary"] == "Tests: 1 passed"
    caught_up = analyst.get(f"{base}/events", params={"after": queued["last"]}).json()
    assert [e["kind"] for e in caught_up["items"]] == ["execution.started", "execution.finished"]


def test_clients_other_origins_and_strangers_cannot_follow(managed, engine):  # noqa: F811
    base, analyst, _, people = _ready(managed, engine)
    client, _ = _signed_in(managed, people["client"])
    assert client.get(f"{base}/events").status_code == 403
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"{base}/events/ws") as socket:
        socket.receive_json()
    evil = {"origin": "https://evil.example"}
    with pytest.raises(WebSocketDisconnect), analyst.websocket_connect(f"{base}/events/ws", headers=evil) as socket:
        socket.receive_json()
    from starlette.testclient import TestClient

    stranger = TestClient(managed)
    with pytest.raises(WebSocketDisconnect), stranger.websocket_connect(f"{base}/events/ws") as socket:
        socket.receive_json()
