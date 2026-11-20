"""How request handlers hand work to the worker."""

import uuid
from typing import Any

from fastapi import BackgroundTasks, Request
from sqlalchemy.orm import Session

from app.jobs import service as jobs
from app.projects.models import Project


def queue(request: Request, tasks: BackgroundTasks, db: Session, kind: str, payload: dict[str, Any], *,
          dedupe_key: str | None = None, project_id: uuid.UUID | None = None) -> None:
    """Records the job durably, then returns. The worker picks it up; in tests the API runs it after responding."""
    project = db.get(Project, project_id) if project_id else None
    jobs.enqueue(db, kind, payload, dedupe_key=dedupe_key, project_id=project_id,
                 organization_id=project.organization_id if project else None)
    db.commit()
    state = request.app.state
    if state.settings.jobs_inline:
        tasks.add_task(jobs.run_pending, state.session_factory, state.settings, state.provider_transport)
