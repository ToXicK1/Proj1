"""Queueing execution jobs and reading their results (Phase 1, RD-30).

The API and worker never run code themselves: they queue a job of an allowlisted kind and wait for the executor's
result. A job that does not finish in time, or an executor that is not running, is reported plainly and never counts
as a pass (the same rule as the sandbox).
"""

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.execution.models import ExecutionJob

KINDS = ("checks", "git.init", "git.commit", "git.read", "git.diff", "git.log", "git.merge", "git.index")
DONE = ("succeeded", "failed", "timed_out", "rejected", "error")


def submit(db: Session, *, organization_id: uuid.UUID, project_id: uuid.UUID, kind: str, payload: dict[str, Any],
           user_id: uuid.UUID | None = None, agent_run_id: uuid.UUID | None = None) -> ExecutionJob:
    """Queues one job. The caller commits."""
    if kind not in KINDS:
        raise AppError(422, "unknown_job_kind", "This kind of execution is not available")
    job = ExecutionJob(id=uuid7(), organization_id=organization_id, project_id=project_id, kind=kind,
                       payload=payload, requested_by_user_id=user_id, agent_run_id=agent_run_id, status="queued")
    db.add(job)
    return job


def wait(factory: sessionmaker[Session], job_id: uuid.UUID, timeout_seconds: float, poll: float = 0.5
         ) -> ExecutionJob | None:
    """The finished job, or None if it did not finish in time (the executor may be down)."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        with factory() as db:
            job = db.get(ExecutionJob, job_id)
            if job is not None and job.status in DONE:
                db.expunge(job)
                return job
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


def job_out(job: ExecutionJob) -> dict[str, Any]:
    return {"id": str(job.id), "kind": job.kind, "status": job.status, "image": job.image, "limits": job.limits,
            "exit_code": job.exit_code, "output": job.output, "result": job.result, "failure": job.failure,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None}


def _allowed(db: Session, user: User, project_id: uuid.UUID):
    """The project's engineering professionals run code; administrators (oversight only), clients, the PM and members
    do not."""
    from app.collab.service import scope_for
    from app.portal.lifecycle import ENGINEERING

    project, scope = scope_for(db, user, project_id)
    engineer = scope.kind == "professional" and bool(scope.profiles & set(ENGINEERING))
    if not engineer:
        raise AppError(403, "not_permitted", "Only the project's engineering professionals run code")
    return project


PUBLIC_KINDS = ("checks",)  # git operations go through the repository service, which enforces approvals


def request(db: Session, user: User, project_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> ExecutionJob:
    project = _allowed(db, user, project_id)
    if kind not in PUBLIC_KINDS:
        raise AppError(422, "unknown_job_kind", "This kind of execution is not available here")
    job = submit(db, organization_id=project.organization_id, project_id=project.id, kind=kind, payload=payload,
                 user_id=user.id)
    append_event(db, chain_key=org_chain(project.organization_id), event_type="execution.requested",
                 actor_type="human", actor_id=str(user.id), organization_id=project.organization_id,
                 project_id=project.id, payload={"job": str(job.id), "kind": kind})
    from app.events.service import publish

    publish(db, organization_id=project.organization_id, project_id=project.id, kind="execution.queued",
            subject=str(job.id), actor=f"user:{user.id}", data={"kind": kind})
    db.commit()
    return job


def get(db: Session, user: User, project_id: uuid.UUID, job_id: uuid.UUID) -> ExecutionJob:
    project = _allowed(db, user, project_id)
    job = db.get(ExecutionJob, job_id)
    if job is None or job.project_id != project.id:
        raise not_found()
    return job


def recent(db: Session, user: User, project_id: uuid.UUID) -> list[ExecutionJob]:
    project = _allowed(db, user, project_id)
    return list(db.execute(select(ExecutionJob).where(ExecutionJob.project_id == project.id)
                           .order_by(ExecutionJob.created_at.desc()).limit(50)).scalars())
