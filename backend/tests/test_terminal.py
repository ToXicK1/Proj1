"""Phase 2d: the IDE terminal. Only the project's engineers open one, on a project with a repository; the session is
audited; the executor accepts its one-time nonce once, within two minutes; the browser relay refuses other origins,
people who are not signed in and anyone but the session's owner; every input line is recorded and the container is
always removed. Docker is simulated here (the real container path is demonstrated on the test stack)."""

import asyncio
import json
import queue
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.core.db import make_session_factory
from app.execution import terminal_server
from app.terminal.models import TerminalSession
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)
from tests.test_repositories import _team, git  # noqa: F401  (fixture)


def _with_repository(managed, engine):  # noqa: F811
    url, dev, reviewer, client = _team(managed, engine)
    assert dev[0].post(url, headers=dev[1]).status_code == 201
    return url.replace("/repository", "/terminal"), dev, reviewer, client


def test_only_engineers_open_a_terminal_and_it_is_audited(managed, engine, git):  # noqa: F811
    url, dev, reviewer, (client, ch) = _team(managed, engine)
    terminal = url.replace("/repository", "/terminal")
    early = dev[0].post(terminal, headers=dev[1], json={"branch": "main"})
    assert early.status_code == 404 and early.json()["code"] == "no_repository"
    assert dev[0].post(url, headers=dev[1]).status_code == 201
    assert client.post(terminal, headers=ch, json={"branch": "main"}).status_code in (403, 404)
    assert dev[0].post(terminal, headers=dev[1], json={"branch": "../etc"}).status_code == 422
    assert dev[0].post(terminal, json={"branch": "main"}).status_code == 403  # no CSRF token
    opened = dev[0].post(terminal, headers=dev[1], json={"branch": "main"})
    assert opened.status_code == 201, opened.text
    body = opened.json()
    assert body["status"] == "requested" and "nonce" not in body  # the nonce never reaches the browser
    with engine.connect() as conn:
        audited = conn.execute(text("select count(*) from audit_events where event_type = 'terminal.opened' "
                                    "and payload->>'session' = :s"), {"s": body["id"]}).scalar_one()
        live = conn.execute(text("select count(*) from workspace_events where kind = 'terminal.opened' "
                                 "and subject = :s"), {"s": body["id"]}).scalar_one()
    assert audited == 1 and live == 1
    assert [s["id"] for s in dev[0].get(terminal).json()["items"]] == [body["id"]]
    assert reviewer[0].get(terminal).json()["items"] == []  # another engineer sees only their own sessions
    assert reviewer[0].get(f"{terminal}/{body['id']}").status_code == 404
    record = dev[0].get(f"{terminal}/{body['id']}").json()
    assert record["inputs"] == [] and record["transcript"] == ""


def test_the_executor_accepts_the_nonce_once_and_only_while_fresh(managed, engine, git):  # noqa: F811
    terminal, dev, _, _ = _with_repository(managed, engine)
    factory = make_session_factory(engine)
    first = uuid.UUID(dev[0].post(terminal, headers=dev[1], json={"branch": "main"}).json()["id"])
    with factory() as db:
        nonce = db.get(TerminalSession, first).nonce
    assert len(nonce) >= 40
    assert terminal_server.claim(factory, first, "guess") is None
    assert terminal_server.claim(factory, first, "") is None
    claimed = terminal_server.claim(factory, first, nonce)
    assert claimed is not None and claimed.status == "running" and claimed.limits["network"] == "none"
    assert terminal_server.claim(factory, first, nonce) is None  # used once
    with factory() as db:
        assert db.get(TerminalSession, first).nonce == ""
    stale = uuid.UUID(dev[0].post(terminal, headers=dev[1], json={"branch": "main"}).json()["id"])
    with factory() as db:
        row = db.get(TerminalSession, stale)
        row.created_at, nonce = datetime.now(UTC) - timedelta(minutes=3), row.nonce
        db.commit()
    assert terminal_server.claim(factory, stale, nonce) is None


def test_the_relay_refuses_other_origins_strangers_and_other_people(managed, engine, git):  # noqa: F811
    terminal, dev, reviewer, (client, _) = _with_repository(managed, engine)
    sid = dev[0].post(terminal, headers=dev[1], json={"branch": "main"}).json()["id"]
    evil = {"origin": "https://evil.example"}
    for person, headers in ((dev[0], evil), (reviewer[0], {}), (client, {})):
        with pytest.raises(WebSocketDisconnect), person.websocket_connect(f"{terminal}/{sid}/ws", headers=headers) as s:
            s.receive_text()
    stranger = type(dev[0])(dev[0].app)
    with pytest.raises(WebSocketDisconnect), stranger.websocket_connect(f"{terminal}/{sid}/ws") as s:
        s.receive_text()
    factory = make_session_factory(engine)
    with factory() as db:
        assert db.get(TerminalSession, uuid.UUID(sid)).status == "requested"  # nothing reached the executor


class ConnectionClosedOK(Exception):  # the name the server treats as a normal close
    pass


class FakeShell:
    """The exec socket: echoes what is typed, like a tty."""

    def __init__(self):
        self.out, self.sent = queue.Queue(), []

    def sendall(self, data):
        self.sent.append(data)
        self.out.put(data)

    def recv(self, size):
        return self.out.get(timeout=5)

    def close(self):
        self.out.put(b"")


class FakeContainer:
    id, status = "c1", "running"

    def __init__(self):
        self.removed = False

    def put_archive(self, path, data):
        assert path == "/repo"

    def start(self):
        pass

    def exec_run(self, command, user):
        assert user == "2000:2000"
        return 0, b""

    def reload(self):
        pass

    def remove(self, force, v):
        self.removed = force and v


class FakeDocker:
    def __init__(self):
        self.created, self.shell, self.container, self.api = [], FakeShell(), FakeContainer(), self
        self.containers, self.execs = self, []

    def create(self, image, command, **options):
        self.created.append({"image": image, "command": command, **options})
        return self.container

    def exec_create(self, container, command, **options):
        self.execs.append({"command": command, **options})
        return {"Id": "e1"}

    def exec_start(self, exec_id, socket, tty):
        return self.shell

    def exec_resize(self, exec_id, height, width):
        self.resized = (height, width)

    def close(self):
        self.shell.close()


class FakeConnection:
    def __init__(self, sid, nonce, messages):
        self.request = type("R", (), {"path": f"/terminal/{sid}", "headers": {"x-terminal-nonce": nonce}})()
        self.incoming, self.sent, self.closed = list(messages), [], None

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        await asyncio.sleep(0.05)
        if not self.incoming:
            raise ConnectionClosedOK()
        return json.dumps(self.incoming.pop(0))

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


def test_a_session_runs_locked_down_records_input_and_always_cleans_up(managed, engine, git, monkeypatch):  # noqa: F811
    import docker

    terminal, dev, _, _ = _with_repository(managed, engine)
    factory = make_session_factory(engine)
    sid = uuid.UUID(dev[0].post(terminal, headers=dev[1], json={"branch": "main"}).json()["id"])
    with factory() as db:
        nonce = db.get(TerminalSession, sid).nonce
    fake = FakeDocker()
    monkeypatch.setattr(docker, "from_env", lambda timeout: fake)
    monkeypatch.setattr(terminal_server, "_repo_archive", lambda path: b"")
    connection = FakeConnection(sid, nonce, [{"type": "resize", "cols": 1000, "rows": 1},
                                             {"type": "input", "data": "ls -la\r"},
                                             {"type": "input", "data": "pytest -q\r"},
                                             {"type": "input", "data": "half typed"}])
    asyncio.run(terminal_server.handle(connection, factory))

    made = fake.created[0]
    assert made["network_mode"] == "none" and made["network_disabled"] and made["read_only"]
    assert made["cap_drop"] == ["ALL"] and "NET_RAW" not in made["cap_add"] and made["pids_limit"] == 256
    assert made["mem_limit"] == "768m" and made["environment"] == {}  # no secrets reach the container
    assert made["command"][-2:] == ["main", str(terminal_server.MAX_SECONDS)]
    assert fake.execs[0]["user"] == "2000:2000" and fake.execs[0]["tty"]
    assert fake.resized == (5, 400)  # clamped
    assert fake.container.removed
    assert {"type": "status", "text": "ready"} in connection.sent
    with factory() as db:
        row = db.get(TerminalSession, sid)
        assert row.status == "ended" and row.nonce == "" and row.ended_at is not None
        assert [i["line"] for i in row.inputs] == ["ls -la", "pytest -q", "half typed"]
        assert row.inputs[-1].get("unsubmitted") and row.input_count == 3
        assert "pytest -q" in row.transcript  # the echoed output
    with engine.connect() as conn:
        closed = conn.execute(text("select data from workspace_events where kind = 'terminal.closed' and subject = :s"),
                              {"s": str(sid)}).scalar_one()
    assert closed["inputs"] == 3 and closed["status"] == "ended"


def test_a_refused_connection_starts_no_container(managed, engine, git, monkeypatch):  # noqa: F811
    import docker

    terminal, dev, _, _ = _with_repository(managed, engine)
    factory = make_session_factory(engine)
    sid = uuid.UUID(dev[0].post(terminal, headers=dev[1], json={"branch": "main"}).json()["id"])
    fake = FakeDocker()
    monkeypatch.setattr(docker, "from_env", lambda timeout: fake)
    connection = FakeConnection(sid, "wrong", [])
    asyncio.run(terminal_server.handle(connection, factory))
    assert connection.closed[0] == 1008 and fake.created == []
