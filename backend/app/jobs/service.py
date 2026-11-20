"""Enqueue, claim, heartbeat, finish and recover jobs.

Delivery is at least once. A worker holds a job under a lease that a heartbeat keeps extending; if the worker
dies, the lease runs out and another worker takes the job again. Every handler is written so that running it
twice is safe: it checks the current state before acting, and handlers that write a single result mark their job
done in the same transaction as that result.
"""

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.activity import service as activity
from app.core import correlation
from app.core.config import Settings
from app.core.db import uuid7
from app.jobs.models import Job

log = logging.getLogger("aidlc.jobs")

ACTIVE = ("queued", "running")


def enqueue(db: Session, kind: str, payload: dict[str, Any], *, dedupe_key: str | None = None,
            organization_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None,
            max_attempts: int = 3, delay_seconds: float = 0) -> uuid.UUID | None:
    """Adds a job inside the caller's transaction; the caller commits. Returns None when an identical job waits."""
    job_id = uuid7()
    statement = insert(Job).values(
        id=job_id, kind=kind, payload=payload, status="queued", attempts=0, max_attempts=max_attempts,
        run_after=datetime.now(UTC) + timedelta(seconds=delay_seconds), dedupe_key=dedupe_key,
        correlation_id=correlation.current(), organization_id=organization_id, project_id=project_id)
    if dedupe_key is not None:
        statement = statement.on_conflict_do_nothing(
            index_elements=["dedupe_key"], index_where=text("status = 'queued' and dedupe_key is not null"))
    inserted = db.execute(statement.returning(Job.id)).scalar_one_or_none()
    if inserted is not None:
        log.info("queued %s %s", kind, inserted)
    return inserted


def claim(db: Session, worker_id: str, lease_seconds: float) -> Job | None:
    """Takes the oldest due job, or one whose worker stopped renewing its lease. Commits the claim."""
    while True:
        now = datetime.now(UTC)
        candidate = (
            select(Job.id)
            .where(or_(and_(Job.status == "queued", Job.run_after <= now),
                       and_(Job.status == "running", Job.locked_until < now)))
            .order_by(Job.run_after, Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        job = db.execute(
            update(Job).where(Job.id == candidate)
            .values(status="running", attempts=Job.attempts + 1, locked_by=worker_id,
                    locked_until=now + timedelta(seconds=lease_seconds), started_at=now)
            .returning(Job)
        ).scalar_one_or_none()
        if job is None:
            db.commit()
            return None
        if job.attempts > job.max_attempts:  # it was taken back after its last allowed attempt died
            job.status, job.locked_by, job.locked_until = "failed", None, None
            job.finished_at = now
            job.last_error = (job.last_error or "") + "\nThe worker stopped during the last allowed attempt."
            db.commit()
            log.error("job %s %s failed: no attempts left", job.kind, job.id)
            continue
        db.commit()
        return job


def heartbeat(factory: sessionmaker[Session], job_id: uuid.UUID, worker_id: str, lease_seconds: float) -> bool:
    with factory() as db:
        renewed = db.execute(
            update(Job).where(Job.id == job_id, Job.locked_by == worker_id, Job.status == "running")
            .values(locked_until=datetime.now(UTC) + timedelta(seconds=lease_seconds))
        ).rowcount
        db.commit()
        return bool(renewed)


def mark_done(db: Session, job_id: uuid.UUID, worker_id: str) -> bool:
    """Marks the job done in the caller's transaction. False if another worker owns it now."""
    return bool(db.execute(
        update(Job).where(Job.id == job_id, Job.locked_by == worker_id, Job.status == "running")
        .values(status="done", locked_by=None, locked_until=None, finished_at=datetime.now(UTC), last_error=None)
    ).rowcount)


def backoff_seconds(attempts: int) -> float:
    return min(600.0, 10.0 * 2 ** max(0, attempts - 1))


def record_failure(factory: sessionmaker[Session], job_id: uuid.UUID, worker_id: str, error: str) -> str:
    """Queues another attempt after a pause, or gives up once the attempts are used."""
    with factory() as db:
        job = db.execute(select(Job).where(Job.id == job_id, Job.locked_by == worker_id, Job.status == "running")
                         .with_for_update()).scalar_one_or_none()
        if job is None:
            db.commit()
            return "lost"
        job.last_error = error[-4000:]
        job.locked_by, job.locked_until = None, None
        if job.attempts < job.max_attempts:
            job.status = "queued"
            job.run_after = datetime.now(UTC) + timedelta(seconds=backoff_seconds(job.attempts))
        else:
            job.status, job.finished_at = "failed", datetime.now(UTC)
        status = job.status
        db.commit()
        return status


@dataclass
class JobContext:
    factory: sessionmaker[Session]
    settings: Settings
    transport: Any
    job_id: uuid.UUID
    worker_id: str
    payload: dict[str, Any]
    finished: bool = field(default=False)

    def finish_in(self, db: Session) -> None:
        """For handlers whose result is one transaction: the job is marked done together with that result."""
        mark_done(db, self.job_id, self.worker_id)
        self.finished = True


Handler = Callable[[JobContext], None]


class _Heartbeat(threading.Thread):
    def __init__(self, factory: sessionmaker[Session], job_id: uuid.UUID, worker_id: str, lease: float) -> None:
        super().__init__(daemon=True, name=f"heartbeat-{job_id}")
        self.factory, self.job_id, self.worker_id, self.lease = factory, job_id, worker_id, lease
        self.stopped = threading.Event()

    def run(self) -> None:
        while not self.stopped.wait(max(1.0, self.lease / 3)):
            try:
                if not heartbeat(self.factory, self.job_id, self.worker_id, self.lease):
                    log.warning("lost the lease on job %s", self.job_id)
                    return
            except Exception:
                log.warning("heartbeat failed for job %s", self.job_id, exc_info=True)


def run_one(factory: sessionmaker[Session], settings: Settings, transport: Any, worker_id: str,
            handlers: dict[str, Handler] | None = None) -> bool:
    """Claims and runs one job. Returns False when nothing was due."""
    if handlers is None:
        from app.jobs.handlers import HANDLERS as handlers
    lease = settings.job_lease_seconds
    with factory() as db:
        job = claim(db, worker_id, lease)
        if job is None:
            return False
        job_id, kind, payload, cid = job.id, job.kind, dict(job.payload), job.correlation_id
        attempt, org_id, project_id = job.attempts, job.organization_id, job.project_id
    token = correlation.bind(cid or correlation.new_id())
    beat = _Heartbeat(factory, job_id, worker_id, lease)
    beat.start()
    label = activity.JOB_LABELS.get(kind, kind)
    with activity.scope(factory=factory, organization_id=org_id, project_id=project_id, job_id=job_id):
        try:
            handler = handlers.get(kind)
            if handler is None:
                raise LookupError(f"no handler for job kind {kind!r}")
            context = JobContext(factory, settings, transport, job_id, worker_id, payload)
            log.info("running %s %s", kind, job_id)
            activity.note("job", f"{label}: started" + (f" (attempt {attempt})" if attempt > 1 else ""))
            handler(context)
            if not context.finished:
                with factory() as db:
                    mark_done(db, job_id, worker_id)
                    db.commit()
            log.info("finished %s %s", kind, job_id)
            activity.note("job", f"{label}: finished")
        except Exception as exc:  # every failure is recorded on the job and retried or reported
            status = record_failure(factory, job_id, worker_id, traceback.format_exc())
            log.exception("job %s %s did not finish; now %s", kind, job_id, status)
            activity.note("job", f"{label}: stopped by an error; " +
                          ("it will be tried again shortly" if status == "queued" else "no attempts left"),
                          {"error": type(exc).__name__})
        finally:
            beat.stopped.set()
            correlation.reset(token)
    return True


def run_pending(factory: sessionmaker[Session], settings: Settings, transport: Any, limit: int = 100) -> int:
    """Runs due jobs in this process until none are left. Used by tests (`jobs_inline`), never in production."""
    done = 0
    while done < limit and run_one(factory, settings, transport, "inline"):
        done += 1
    return done


# Recovery -------------------------------------------------------------------------------------------------------

def _no_job_for(key: str, failed_within: timedelta) -> Any:
    """True when nothing is waiting or running for this subject and nothing failed for it recently."""
    since = datetime.now(UTC) - failed_within
    return ~exists().where(Job.dedupe_key == key).where(
        or_(Job.status.in_(ACTIVE), and_(Job.status == "failed", Job.finished_at > since)))


def sweep(db: Session, settings: Settings) -> list[str]:
    """Queues work that should be running but has no job: the safety net for a lost enqueue. Commits."""
    from app.collab.models import Ticket
    from app.workflows.models import (
        StageExecution,
        WorkflowDefinition,
        WorkflowExecution,
        WorkflowVersion,
    )
    from app.workflows.state_machine import StageStatus as S

    grace = datetime.now(UTC) - timedelta(seconds=settings.job_sweep_grace_seconds)
    recent_failure = timedelta(minutes=30)
    queued: list[str] = []

    waiting = db.execute(
        select(WorkflowExecution.id, WorkflowExecution.organization_id, WorkflowExecution.project_id).distinct()
        .join(StageExecution, StageExecution.workflow_execution_id == WorkflowExecution.id)
        .join(WorkflowVersion, WorkflowVersion.id == WorkflowExecution.workflow_version_id)
        .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowVersion.definition_id)
        .where(WorkflowDefinition.organization_id.is_(None), WorkflowDefinition.key.like("aidlc-%"),
               StageExecution.status.in_([S.READY.value, S.CHANGES_REQUESTED.value]),
               StageExecution.updated_at < grace)
    ).all()
    for execution_id, org_id, project_id in waiting:
        key = f"drive:{execution_id}"
        if db.execute(select(_no_job_for(key, recent_failure))).scalar():
            enqueue(db, "portal.drive", {"execution_id": str(execution_id)}, dedupe_key=key,
                    organization_id=org_id, project_id=project_id)
            queued.append(key)

    open_tickets = db.execute(select(Ticket.id, Ticket.organization_id, Ticket.project_id)
                              .where(Ticket.status == "open", Ticket.updated_at < grace)).all()
    for ticket_id, org_id, project_id in open_tickets:
        key = f"triage:{ticket_id}"
        if db.execute(select(_no_job_for(key, recent_failure))).scalar():
            enqueue(db, "collab.triage", {"ticket_id": str(ticket_id)}, dedupe_key=key,
                    organization_id=org_id, project_id=project_id)
            queued.append(key)
    db.commit()
    if queued:
        log.warning("recovered %d stalled item(s): %s", len(queued), ", ".join(queued))
    return queued
