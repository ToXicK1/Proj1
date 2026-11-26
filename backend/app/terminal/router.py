"""Terminal sessions over HTTP and a WebSocket relay to the executor (Phase 2d).

The browser connects to the API with its session cookie; the API checks the person, the project and the session, then
connects to the executor's internal terminal server with the session's one-time nonce and relays messages both ways.
The API never runs a command itself.
"""

import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.auth import service as auth
from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.auth.models import User
from app.terminal import service

log = logging.getLogger("aidlc.terminal")
router = APIRouter(prefix="/api/v1/projects/{project_id}/terminal", tags=["terminal"])
EXECUTOR_URL = os.environ.get("AIDLC_EXECUTOR_TERMINAL_URL", "ws://executor:8090")


class OpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str = Field(min_length=1, max_length=100)


@router.post("", status_code=201)
def open_terminal(project_id: uuid.UUID, body: OpenIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.session_out(service.open_session(db, caller.user, project_id, body.branch))


@router.get("")
def list_sessions(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": [service.session_out(r) for r in service.recent(db, caller.user, project_id)]}


@router.get("/{session_id}")
def session_record(project_id: uuid.UUID, session_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.session_out(service.get(db, caller.user, project_id, session_id), full=True)


def _nonce_for(websocket: WebSocket, project_id: uuid.UUID, session_id: uuid.UUID) -> str | None:
    state = websocket.app.state
    raw = websocket.cookies.get(state.settings.session_cookie_name)
    if not raw:
        return None
    with state.session_factory() as db:
        found = auth.find_session(db, raw)
        user = db.get(User, found.user_id) if found else None
        if user is None or user.status != "active" or user.must_change_password:
            return None
        return service.connectable(db, user, project_id, session_id)


@router.websocket("/{session_id}/ws")
async def relay(websocket: WebSocket, project_id: uuid.UUID, session_id: uuid.UUID) -> None:
    from websockets.asyncio.client import connect

    settings = websocket.app.state.settings
    origin = websocket.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in set(settings.cors_origins) | {settings.public_base_url.rstrip("/")}:
        await websocket.close(code=1008)
        return
    nonce = await run_in_threadpool(_nonce_for, websocket, project_id, session_id)
    if not nonce:
        await websocket.close(code=1008)  # not signed in, not this person's session, or already used
        return
    await websocket.accept()
    try:
        async with connect(f"{EXECUTOR_URL}/terminal/{session_id}", additional_headers={"x-terminal-nonce": nonce},
                           max_size=1024 * 1024, open_timeout=20) as upstream:

            async def down() -> None:  # executor -> browser
                async for message in upstream:
                    await websocket.send_text(message if isinstance(message, str) else message.decode("utf-8", "replace"))

            async def up() -> None:  # browser -> executor
                while True:
                    await upstream.send(await websocket.receive_text())

            tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                task.cancel()
    except (TimeoutError, WebSocketDisconnect, OSError, RuntimeError):
        pass
    except Exception as exc:  # noqa: BLE001 - the executor closed or refused: logged, and the browser is closed below
        log.warning("terminal relay %s ended: %s", session_id, type(exc).__name__)
    try:
        await websocket.close()
    except RuntimeError:
        pass
