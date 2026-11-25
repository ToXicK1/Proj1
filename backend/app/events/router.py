"""Live workspace events over a WebSocket, and the same events over REST for catching up (Phase 1d).

The WebSocket authenticates with the session cookie exactly as other requests do, refuses other origins, and
re-checks the session on every poll, so a sign-out or a password reset ends the stream. It sends events newer than
the client's last one (`?after=`), then follows new ones about once a second.
"""

import asyncio
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.auth import service as auth
from app.auth.deps import CurrentCaller, DbSession
from app.auth.models import User
from app.core.errors import AppError
from app.events import service as events

router = APIRouter(prefix="/api/v1/projects/{project_id}/events", tags=["events"])
POLL_SECONDS = 1.0


@router.get("")
def list_events(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession,
                after: int = Query(0, ge=0)) -> dict:
    events.allowed(db, caller.user, project_id)
    rows = events.after(db, project_id, after)
    return {"items": [events.event_out(e) for e in rows], "last": rows[-1].id if rows else after}


def _authorise(websocket: WebSocket, project_id: uuid.UUID) -> bool:
    """True if the socket's session still belongs to an active member of the project's team."""
    state = websocket.app.state
    raw = websocket.cookies.get(state.settings.session_cookie_name)
    if not raw:
        return False
    with state.session_factory() as db:
        session_row = auth.find_session(db, raw)
        user = db.get(User, session_row.user_id) if session_row else None
        if user is None or user.status != "active" or user.must_change_password:
            return False
        try:
            events.allowed(db, user, project_id)
        except AppError:
            return False
    return True


def _poll(websocket: WebSocket, project_id: uuid.UUID, last: int) -> list[dict]:
    with websocket.app.state.session_factory() as db:
        return [events.event_out(e) for e in events.after(db, project_id, last)]


@router.websocket("/ws")
async def follow(websocket: WebSocket, project_id: uuid.UUID, after: int = 0) -> None:
    origin = websocket.headers.get("origin")
    allowed_origins = set(websocket.app.state.settings.cors_origins) | {
        websocket.app.state.settings.public_base_url.rstrip("/")}
    if origin is not None and origin.rstrip("/") not in allowed_origins:
        await websocket.close(code=1008)  # policy violation: another site may not follow our events
        return
    if not await run_in_threadpool(_authorise, websocket, project_id):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    last = max(0, after)
    try:
        while True:
            batch = await run_in_threadpool(_poll, websocket, project_id, last)
            if batch:
                last = batch[-1]["id"]
                await websocket.send_json({"type": "events", "items": batch, "last": last})
            await asyncio.sleep(POLL_SECONDS)
            if not await run_in_threadpool(_authorise, websocket, project_id):
                await websocket.close(code=1008)  # signed out, reset, or removed from the project
                return
    except (WebSocketDisconnect, RuntimeError):
        return
