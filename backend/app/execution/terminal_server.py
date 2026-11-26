"""The executor's terminal server (Phase 2d). Internal only: it listens on the compose network and publishes no port.

A connection must name a terminal session the API created and carry its one-time nonce (checked against the database,
then cleared). The executor then starts a fresh container for that session (no network, read-only root, dropped
capabilities, CPU/memory/process limits, the project's repository copied in) and attaches an interactive bash as the
unprivileged user. Keystrokes and output are relayed; every input line and the output (last 200 KB) are recorded.
The session ends after 10 idle minutes or 30 minutes in all, or when either side closes; the container and its
volumes are always removed.
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.execution.executor import REPOS, RUNNER_IMAGE, _repo_archive
from app.terminal.models import TerminalSession

log = logging.getLogger("aidlc.terminal")
PORT = 8090
IDLE_SECONDS, MAX_SECONDS = 600, 1800
TRANSCRIPT_LIMIT = 200_000
NONCE_TTL = timedelta(minutes=2)
LIMITS = {"network": "none", "memory": "768m", "cpus": 1.0, "pids": 256, "idle_seconds": IDLE_SECONDS,
          "max_seconds": MAX_SECONDS, "read_only_root": True, "user": 2000}


def claim(factory: sessionmaker[Session], session_id: uuid.UUID, nonce: str) -> TerminalSession | None:
    """Accepts the nonce once, for a session requested in the last two minutes."""
    with factory() as db:
        row = db.execute(select(TerminalSession).where(TerminalSession.id == session_id).with_for_update()
                         ).scalar_one_or_none()
        if row is None or row.status != "requested" or not row.nonce or row.nonce != nonce \
                or datetime.now(UTC) - row.created_at > NONCE_TTL:
            return None
        row.status, row.nonce, row.started_at, row.limits = "running", "", datetime.now(UTC), dict(LIMITS)
        db.commit()
        db.expunge(row)
        return row


def finish(factory: sessionmaker[Session], session_id: uuid.UUID, *, status: str, reason: str, transcript: str,
           inputs: list[dict]) -> None:
    from app.events.service import publish

    with factory() as db:
        row = db.get(TerminalSession, session_id)
        row.status, row.end_reason, row.ended_at = status, reason[:200], datetime.now(UTC)
        row.transcript, row.inputs, row.input_count = transcript[-TRANSCRIPT_LIMIT:], inputs[-2000:], len(inputs)
        publish(db, organization_id=row.organization_id, project_id=row.project_id, kind="terminal.closed",
                subject=str(row.id), actor=f"user:{row.user_id}",
                data={"branch": row.branch, "status": status, "summary": reason[:200], "inputs": len(inputs)})
        db.commit()


def start_container(client: Any, row: TerminalSession) -> Any:
    from docker.types import Mount

    container = client.containers.create(
        RUNNER_IMAGE, ["python", "/opt/runner/terminal_init.py", row.branch, str(MAX_SECONDS)], detach=True,
        network_disabled=True, network_mode="none", read_only=True, mem_limit="768m", memswap_limit="768m",
        nano_cpus=int(1e9), pids_limit=256, cap_drop=["ALL"], cap_add=["CHOWN", "SETUID", "SETGID"],
        security_opt=["no-new-privileges:true"], init=True, environment={},
        mounts=[Mount(target="/repo", source=None, type="volume")],
        tmpfs={"/work": "size=256m,mode=0711,nosuid,nodev", "/tmp": "size=64m,mode=1777,nosuid,nodev,noexec"},
        labels={"aidlc.terminal-session": str(row.id)})
    container.put_archive("/repo", _repo_archive(REPOS / str(row.project_id)))
    container.start()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:  # wait for the working copy
        code, _ = container.exec_run(["test", "-f", "/work/.ready"], user="2000:2000")
        if code == 0:
            return container
        container.reload()
        if container.status != "running":
            raise RuntimeError("the terminal container stopped while preparing: "
                               + container.logs().decode("utf-8", "replace")[-300:])
        time.sleep(0.3)
    raise RuntimeError("the working copy was not ready in time")


async def handle(connection: Any, factory: sessionmaker[Session]) -> None:
    import docker

    path = connection.request.path
    try:
        session_id = uuid.UUID(path.rstrip("/").split("/")[-1])
    except ValueError:
        await connection.close(1008, "unknown session")
        return
    row = await asyncio.to_thread(claim, factory, session_id, connection.request.headers.get("x-terminal-nonce", ""))
    if row is None:
        await connection.close(1008, "not allowed")
        return
    client = docker.from_env(timeout=120)  # one client per session: the SDK's HTTP session is not thread-safe
    transcript: list[str] = []
    inputs: list[dict] = []
    pending = ""
    container = None
    status, reason = "ended", "closed"
    loop = asyncio.get_running_loop()
    last_input = time.monotonic()
    started = time.monotonic()
    try:
        await connection.send(json.dumps({"type": "status", "text": f"Preparing a working copy of {row.branch}…"}))
        container = await asyncio.to_thread(start_container, client, row)
        exec_id = client.api.exec_create(container.id, ["bash", "-l"], stdin=True, tty=True, user="2000:2000",
                                         workdir="/work/project",
                                         environment={"HOME": "/work", "TERM": "xterm-256color",
                                                      "PS1": f"\\[\\e[32m\\]{row.branch}\\[\\e[0m\\] \\W$ "})["Id"]
        sock = client.api.exec_start(exec_id, socket=True, tty=True)
        raw = sock._sock if hasattr(sock, "_sock") else sock
        await connection.send(json.dumps({"type": "status", "text": "ready"}))

        def pump() -> None:  # container output -> browser
            while True:
                try:
                    data = raw.recv(4096)
                except OSError:
                    break
                if not data:
                    break
                text = data.decode("utf-8", "replace")
                transcript.append(text)
                asyncio.run_coroutine_threadsafe(connection.send(json.dumps({"type": "output", "data": text})), loop)
            asyncio.run_coroutine_threadsafe(connection.close(1000, "the shell exited"), loop)

        threading.Thread(target=pump, daemon=True).start()
        while True:
            remaining = min(IDLE_SECONDS - (time.monotonic() - last_input), MAX_SECONDS - (time.monotonic() - started))
            if remaining <= 0:
                reason = "idle for 10 minutes" if time.monotonic() - last_input >= IDLE_SECONDS else "30 minutes reached"
                await connection.close(1000, reason)
                break
            try:
                message = await asyncio.wait_for(connection.recv(), timeout=remaining)
            except TimeoutError:
                continue
            body = json.loads(message) if isinstance(message, str) else {}
            if body.get("type") == "input" and isinstance(body.get("data"), str):
                data = body["data"][:4096]
                last_input = time.monotonic()
                await asyncio.to_thread(raw.sendall, data.encode())
                pending += data
                while "\r" in pending or "\n" in pending:  # record each submitted line
                    cut = min(i for i in (pending.find("\r"), pending.find("\n")) if i >= 0)
                    inputs.append({"at": datetime.now(UTC).isoformat(), "line": pending[:cut][:1000]})
                    pending = pending[cut + 1:]
            elif body.get("type") == "resize":
                cols, rows = int(body.get("cols", 80)), int(body.get("rows", 24))
                await asyncio.to_thread(client.api.exec_resize, exec_id, height=max(5, min(rows, 200)),
                                        width=max(20, min(cols, 400)))
    except Exception as exc:  # noqa: BLE001 - connection closed, container failed: recorded, never silent
        if type(exc).__name__ not in ("ConnectionClosedOK", "ConnectionClosedError", "ConnectionClosed"):
            status, reason = "failed", f"{type(exc).__name__}: {str(exc)[:150]}"
            log.warning("terminal %s failed: %s", session_id, reason)
    finally:
        if container is not None:
            try:
                await asyncio.to_thread(container.remove, force=True, v=True)
            except Exception:  # noqa: BLE001
                log.warning("could not remove terminal container %s", session_id)
        if pending.strip():
            inputs.append({"at": datetime.now(UTC).isoformat(), "line": pending[:1000], "unsubmitted": True})
        await asyncio.to_thread(finish, factory, session_id, status=status, reason=reason,
                                transcript="".join(transcript), inputs=inputs)
        client.close()


def serve_forever(factory: sessionmaker[Session]) -> None:  # pragma: no cover - started by the executor
    from websockets.asyncio.server import serve

    async def run() -> None:
        async with serve(lambda c: handle(c, factory), "0.0.0.0", PORT, max_size=64 * 1024):
            log.info("terminal server on port %s (internal network only)", PORT)
            await asyncio.Future()

    asyncio.run(run())


def start_in_background(factory: sessionmaker[Session]) -> None:  # pragma: no cover
    threading.Thread(target=serve_forever, args=(factory,), daemon=True, name="terminal-server").start()
