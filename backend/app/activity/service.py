"""Records what the AI does, as it happens, and shows it to the people who supervise it.

A stage runs inside one database transaction, so nothing it does is visible until it finishes. This log is
written through its own short sessions instead: each step is committed the moment it happens, so a professional
can watch the work in progress. It records only facts the platform observed (what an agent was given, what it
returned, what the reviewer and the sandbox said). Models here return finished JSON, not a stream of thoughts,
so nothing is invented to look like reasoning. Writing to the log never breaks the work it describes.

Owners never see this log; professionals see their own departments; administrators and project managers see all.
"""

import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.activity.models import AiActivity
from app.auth.models import User
from app.core import correlation
from app.core.db import uuid7
from app.core.errors import AppError
from app.jobs.models import Job

log = logging.getLogger("aidlc.activity")

PREVIEW_CHARS = 400
MAX_FILES = 60


@dataclass(frozen=True)
class _Scope:
    factory: sessionmaker[Session] | None = None
    organization_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    stage_key: str | None = None
    profile_key: str | None = None


_EMPTY = _Scope()
_scope: ContextVar[_Scope | None] = ContextVar("activity_scope", default=None)


@contextmanager
def scope(**changes: Any) -> Iterator[None]:
    """Narrows where the notes made inside this block belong (factory, project, job, stage, department)."""
    token = _scope.set(replace(_scope.get() or _EMPTY, **{k: v for k, v in changes.items() if v is not None}))
    try:
        yield
    finally:
        _scope.reset(token)


def note(kind: str, title: str, detail: dict[str, Any] | None = None, *, stage_key: str | None = None,
         profile_key: str | None = None) -> None:
    """Commits one entry at once, in its own session. Does nothing outside a job (no factory bound)."""
    current = _scope.get() or _EMPTY
    if current.factory is None or current.project_id is None or current.organization_id is None:
        return
    try:
        with current.factory() as db:
            db.add(AiActivity(id=uuid7(), organization_id=current.organization_id, project_id=current.project_id,
                              job_id=current.job_id, stage_key=stage_key or current.stage_key,
                              profile_key=profile_key or current.profile_key, kind=kind, title=title[:300],
                              detail=_bounded(detail or {}), correlation_id=correlation.current()))
            db.commit()
    except Exception:
        log.warning("could not record activity %s", kind, exc_info=True)


def _bounded(detail: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(detail, default=str)
    if len(text) <= 16000:
        return json.loads(text)
    return {"note": "Too large to show here; open the deliverable for the full content."}


def _clip(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS].rstrip() + "…"


def files_of(value: Any) -> list[dict[str, Any]]:
    """Paths and sizes of generated files. The contents stay in the deliverable, behind its own permissions."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:MAX_FILES]:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            content = item.get("content") if isinstance(item.get("content"), str) else ""
            out.append({"path": item["path"][:200], "lines": content.count("\n") + (1 if content else 0),
                        "bytes": len(content.encode())})
    return out


def preview(output: dict[str, Any]) -> dict[str, Any]:
    """A short, readable view of what an agent returned, field by field."""
    fields = []
    for key, value in output.items():
        if key == "source_files":
            files = files_of(value)
            fields.append({"key": key, "files": files, "count": len(value) if isinstance(value, list) else 0})
        elif isinstance(value, list):
            fields.append({"key": key, "count": len(value), "items": [_clip(v) for v in value[:5]]})
        else:
            fields.append({"key": key, "text": _clip(value)})
    return {"fields": fields}


# Live model calls -------------------------------------------------------------------------------------------------

PROMPT_CHARS = 16000
LIVE_CHARS = 30000
FLUSH_SECONDS = 0.8


class LiveCall:
    """One model call shown as it happens: the exact prompt, then the reasoning and the reply as they stream in.

    Like a chat app's "thinking" panel, but only with what the model really sent: reasoning appears only when the
    model reports it; otherwise the reply itself is what streams.
    """

    def __init__(self, row_id: uuid.UUID, factory: sessionmaker[Session]) -> None:
        self.row_id, self.factory = row_id, factory
        self.text: list[str] = []
        self.thinking: list[str] = []
        self.size = {"text": 0, "thinking": 0}
        self.started = time.monotonic()
        self.flushed = 0.0

    @classmethod
    def start(cls, title: str, *, agent: str, role: str, attempt: int, system: str, user: str, max_tokens: int,
              context_tokens: int) -> "LiveCall | None":
        current = _scope.get() or _EMPTY
        if current.factory is None or current.project_id is None or current.organization_id is None:
            return None
        prompt_tokens = (len(system) + len(user)) // 4  # a rough estimate: about four characters per token
        room = max(0, context_tokens - prompt_tokens)
        warning = None
        if prompt_tokens >= context_tokens * 0.85:
            warning = (f"The prompt is about {prompt_tokens} tokens, close to or over the model's {context_tokens}-token "
                       "window. The model may silently drop the start of it, where the instructions are.")
        elif room < min(max_tokens, 1500):
            warning = f"Only about {room} tokens are left for the reply, so a long answer may be cut off."
        detail = {
            "agent": agent, "role": role, "attempt": attempt, "state": "waiting",
            "prompt": {"system": system[:PROMPT_CHARS], "user": user[:PROMPT_CHARS],
                       "cut": len(system) > PROMPT_CHARS or len(user) > PROMPT_CHARS},
            "prompt_tokens_est": prompt_tokens, "context_tokens": context_tokens, "reply_room_est": room,
            "max_reply_tokens": max_tokens, "warning": warning, "text": "", "thinking": "",
            "has_code": _has_code(system) or _has_code(user),
        }
        try:
            with current.factory() as db:
                row = AiActivity(id=uuid7(), organization_id=current.organization_id, project_id=current.project_id,
                                 job_id=current.job_id, stage_key=current.stage_key, profile_key=current.profile_key,
                                 kind="model_call", title=title[:300], detail=detail,
                                 correlation_id=correlation.current())
                db.add(row)
                db.commit()
                return cls(row.id, current.factory)
        except Exception:
            log.warning("could not start a live entry", exc_info=True)
            return None

    def delta(self, kind: str, chunk: str) -> None:
        key = "thinking" if kind == "thinking" else "text"
        if self.size[key] < LIVE_CHARS:
            piece = chunk[:LIVE_CHARS - self.size[key]]
            (self.thinking if key == "thinking" else self.text).append(piece)
            self.size[key] += len(piece)
        if time.monotonic() - self.flushed >= FLUSH_SECONDS:
            self._save({"state": "streaming"})

    def finish(self, *, ok: bool, seconds: float, tokens: dict[str, int] | None, final_text: str | None,
               thinking: str, error: str | None) -> None:
        text = final_text if final_text else "".join(self.text)
        self.text, self.size["text"] = [text[:LIVE_CHARS]], min(len(text), LIVE_CHARS)
        if thinking and not self.thinking:
            self.thinking = [thinking[:LIVE_CHARS]]
        self._save({"state": "done" if ok else "failed", "seconds": seconds, "tokens": tokens, "error": error})

    def _save(self, patch: dict[str, Any]) -> None:
        self.flushed = time.monotonic()
        text = "".join(self.text)
        patch = {**patch, "text": text, "thinking": "".join(self.thinking),
                 "elapsed": round(self.flushed - self.started, 1)}
        if _has_code(text):
            patch["has_code"] = True
        try:
            with self.factory() as db:
                row = db.get(AiActivity, self.row_id)
                if row is not None:
                    row.detail = {**row.detail, **patch}
                    db.commit()
        except Exception:
            log.warning("could not update a live entry", exc_info=True)


def _has_code(text: str) -> bool:
    """Generated source code travels as a source_files list; prompts and replies holding it are marked."""
    return "source_files" in text and '"content"' in text


CODE_HIDDEN = ("This step includes generated source code. Only the development team (developers, QA engineers and "
               "administrators) can see code, so the prompt and reply are not shown here.")


def _redacted(detail: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in detail.items() if k not in ("prompt", "text", "thinking")}
    return {**out, "text": "", "thinking": "", "hidden": CODE_HIDDEN}


def _visible(row: AiActivity, may_see_code: bool) -> dict[str, Any]:
    if may_see_code:
        return row.detail
    if row.detail.get("has_code"):
        return _redacted(row.detail)
    if row.kind == "checks":  # test output can quote source lines; the verdict and summary stay visible
        return {**row.detail, "checks": [{**c, "output": []} for c in row.detail.get("checks", [])]}
    return row.detail


# Reading -----------------------------------------------------------------------------------------------------------

JOB_LABELS = {"portal.drive": "Planning the next steps", "portal.stage": "Running a step", "portal.resume": "Trying a blocked step again",
              "portal.answer": "Answering the project owner", "collab.triage": "Checking a new ticket"}


def _out(row: AiActivity, may_see_code: bool = True) -> dict[str, Any]:
    from app.portal.lifecycle import BY_PROFILE, BY_STAGE

    step = BY_STAGE.get(row.stage_key or "")
    member = BY_PROFILE.get(row.profile_key or "")
    return {"id": str(row.id), "kind": row.kind, "title": row.title, "stage": row.stage_key,
            "stage_name": f"{step.number} {step.name}" if step else None,
            "department": member.title if member else None,
            "profile": row.profile_key, "at": row.created_at.isoformat(),
            "detail": _visible(row, may_see_code)}


def project_activity(db: Session, user: User, project_id: uuid.UUID, *, limit: int = 80) -> dict[str, Any]:
    from app.collab.service import scope_for

    project, who = scope_for(db, user, project_id)
    if not who.internal:  # owners and plain members get the plain-language view, never the AI's working
        raise AppError(403, "not_permitted", "The AI activity log is for the professional team")
    query = select(AiActivity).where(AiActivity.project_id == project.id)
    if who.kind == "professional":  # their own departments, plus job-level notes that name no department
        query = query.where(or_(AiActivity.profile_key.in_(sorted(who.profiles)),
                                (AiActivity.profile_key.is_(None)) & (AiActivity.kind == "job")))
    rows = db.execute(query.order_by(AiActivity.created_at.desc(), AiActivity.id.desc()).limit(limit)).scalars()
    from app.portal.service import _may_see_code

    code = _may_see_code(db, user, project)
    running = db.execute(select(Job).where(Job.project_id == project.id, Job.status.in_(("queued", "running")))
                         .order_by(Job.created_at)).scalars().all()
    return {
        "items": [_out(r, code) for r in rows],
        "jobs": [{"kind": JOB_LABELS.get(j.kind, j.kind), "status": j.status, "attempts": j.attempts,
                  "since": (j.started_at or j.created_at).isoformat()} for j in running],
        "now": datetime.now().astimezone().isoformat(),
    }
