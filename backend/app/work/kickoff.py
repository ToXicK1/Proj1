"""The project kickoff (start flow, after P5).

The PM holds the kickoff once the platform's checklist passes: the project has its PM and client, its kind of work
(chosen when the project was created), and a professional in every department that kind of work needs. The kickoff
is a confirmed PM record (date, attendees, agenda, notes, how everyone keeps in touch). The brief can only be
assembled after it. The PM may change the kind of work (audited) until the client approves the brief or delivery
starts; delivery then starts with it.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core.errors import AppError, not_found
from app.projects.models import Project
from app.work import service as work
from app.work.models import WorkItem, WorkPackage

PM = "project_manager"


def held(db: Session, project_id: uuid.UUID) -> WorkItem | None:
    return db.execute(select(WorkItem).where(WorkItem.project_id == project_id, WorkItem.kind == "kickoff",
                                             WorkItem.status != "archived",
                                             WorkItem.provenance.not_in(work.NEEDS_CONFIRMING))).scalars().first()


def locked(db: Session, project: Project) -> bool:
    """The kind of work is fixed once the client approved a brief or delivery started."""
    from app.workflows.models import WorkflowExecution

    if db.execute(select(WorkflowExecution.id).where(WorkflowExecution.project_id == project.id)).first():
        return True
    return db.execute(select(WorkPackage.id).where(WorkPackage.project_id == project.id,
                                                   WorkPackage.client_status == "approved")).first() is not None


def checklist(db: Session, project: Project) -> list[dict[str, Any]]:
    from app.collab.service import holders
    from app.portal.lifecycle import BY_PROFILE, SCOPE_LABELS, departments_for
    from app.projects.models import ProjectMember

    client = db.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == project.id,
                                                            ProjectMember.project_role == "project_owner")).first()
    items = [
        {"key": "pm", "label": "A Project Manager is assigned", "ok": project.project_manager_id is not None},
        {"key": "client", "label": "The client has an account on the project", "ok": client is not None},
        {"key": "scope", "label": "The kind of work is chosen"
         + (f": {SCOPE_LABELS[project.delivery_scope]}" if project.delivery_scope else ""),
         "ok": project.delivery_scope is not None},
    ]
    for department in departments_for(project.delivery_scope) if project.delivery_scope else ():
        people = holders(db, project, department)
        items.append({"key": f"team:{department}", "label": f"A {BY_PROFILE[department].title} is assigned",
                      "ok": bool(people)})
    return items


def missing(db: Session, project: Project) -> list[str]:
    return [i["label"] for i in checklist(db, project) if not i["ok"]]


def status(db: Session, user: User, project_id: uuid.UUID) -> dict[str, Any]:
    from app.portal.lifecycle import SCOPE_LABELS, SCOPES

    project, scope = work._scope(db, user, project_id)
    if not work.reads_all(scope, PM):
        raise not_found()
    record = held(db, project.id)
    items = checklist(db, project)
    return {"checklist": items, "ready": all(i["ok"] for i in items),
            "kickoff": work.item_out(db, record, full=True) if record else None,
            "scope": project.delivery_scope, "scope_locked": locked(db, project),
            "scopes": [{"key": k, "label": SCOPE_LABELS[k]} for k in SCOPES],
            "can_edit": work.edits(db, user, project, PM)}


def hold(db: Session, user: User, project_id: uuid.UUID, *, held_at: str, attendees: list[str], agenda: list[str],
         notes: str, communication: str) -> dict[str, Any]:
    """The PM records the kickoff; only when the checklist passes, and once per project."""
    project, _ = work._scope(db, user, project_id)
    work._require_editor(db, user, project, PM)
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    if held(db, project.id) is not None:
        raise AppError(409, "kickoff_held", "The kickoff is already recorded; edit that record instead")
    gaps = missing(db, project)
    if gaps:
        raise AppError(409, "kickoff_not_ready", "The project is not ready for its kickoff", problems=gaps)
    body = {k: v for k, v in {"held_at": held_at.strip(), "attendees": attendees, "agenda": agenda,
                              "notes": notes.strip(), "communication": communication.strip()}.items() if v}
    db.commit()  # release the lock; create() takes its own transaction
    return work.create(db, user, project.id, PM, kind="kickoff", title="Project kickoff", body=body,
                       reason="held the kickoff", kickoff=True)


def change_scope(db: Session, user: User, project_id: uuid.UUID, scope: str, reason: str) -> dict[str, Any]:
    """The PM changes the kind of work, with the client's agreement, until it is locked."""
    from app.portal.lifecycle import SCOPES

    project, _ = work._scope(db, user, project_id)
    work._require_editor(db, user, project, PM)
    if scope not in SCOPES:
        raise AppError(422, "unknown_scope", "Choose one of the listed kinds of work")
    if not reason.strip():
        raise AppError(422, "reason_required", "Say why the kind of work changes")
    project = db.execute(select(Project).where(Project.id == project.id).with_for_update()).scalar_one()
    if locked(db, project):
        raise AppError(409, "scope_locked", "The client approved the brief; the kind of work can no longer change")
    previous, project.delivery_scope = project.delivery_scope, scope
    # A brief waiting for the client names the old kind of work: it is withdrawn, to be re-assembled and approved.
    withdrawn = []
    for package in db.execute(select(WorkPackage).where(WorkPackage.project_id == project.id,
                                                        WorkPackage.client_status == "awaiting")).scalars():
        package.client_status, package.client_note = "withdrawn", f"The kind of work changed: {reason}"[:2000]
        withdrawn.append(package.number)
    work._audit(db, project, "project.scope_changed", user, {"from": previous, "to": scope, "reason": reason[:500],
                                                             "withdrawn_packages": withdrawn})
    db.commit()
    return status(db, user, project.id)
