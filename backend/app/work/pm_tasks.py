"""The PM's Tasks page: what waits on the PM now, and every department's lifecycle work in one view.

Read-only. Everything is computed from the records, packages, handoffs, client input and workflow state that
already exist; nothing here changes anything. Assigned tasks (owners, priorities, due dates) arrive with P6.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core.errors import not_found
from app.work import service as work
from app.work.models import Handoff, WorkItem, WorkItemVersion, WorkPackage

PM = "project_manager"


def _todo(kind: str, text: str, module: str, urgent: bool = False) -> dict[str, Any]:
    return {"kind": kind, "text": text, "module": module, "urgent": urgent}


def _discovery(db: Session, project_id: uuid.UUID, started: bool) -> list[dict[str, Any]]:
    """Intake, brief and handoff: the PM's path to starting delivery (P2 to P4)."""
    if started:
        return []

    def current(kind: str) -> tuple[WorkItem | None, WorkItemVersion | None]:
        item = db.execute(select(WorkItem).where(WorkItem.project_id == project_id, WorkItem.kind == kind,
                                                 WorkItem.status != "archived")).scalars().first()
        return item, db.get(WorkItemVersion, item.current_version_id) if item else None

    intake, intake_v = current("project_intake")
    if intake is None:
        return [_todo("intake", "Create the project intake from your client meetings", "intake")]
    if intake_v.body.get("validation") != "validated" or intake_v.provenance in work.NEEDS_CONFIRMING:
        return [_todo("intake", f"Confirm and validate the project intake ({intake.key})", "intake")]
    brief, brief_v = current("project_brief")
    if brief is None:
        return [_todo("brief", "Assemble the project brief from the validated intake", "brief")]
    if brief_v.provenance in work.NEEDS_CONFIRMING:
        return [_todo("brief", f"Confirm or edit the assembled brief ({brief.key})", "brief")]
    if brief.status == "approved":
        return [_todo("handoff", f"Hand the approved brief ({brief.key}) to the Business Analyst to start delivery",
                      "ba_handoff", urgent=True)]
    if brief.status != "in_review":
        return [_todo("brief", f"Submit the brief ({brief.key}) for approval", "brief")]
    return []


def todos(db: Session, project, user: User) -> list[dict[str, Any]]:
    from app.portal.models import OwnerFeedback
    from app.workflows.models import WorkflowExecution

    started = db.execute(select(WorkflowExecution.id).where(
        WorkflowExecution.project_id == project.id)).first() is not None
    out = _discovery(db, project.id, started)
    for p in db.execute(select(WorkPackage).where(WorkPackage.project_id == project.id, WorkPackage.department == PM,
                                                  WorkPackage.status == "submitted")).scalars():
        own = work._second_person_needed(p.snapshot, user.id)
        out.append(_todo("approval", f"Decide on package {p.number}: {p.title}"
                         + (" (it has your own edits: another Project Manager must approve it)" if own else ""),
                         "brief", urgent=not own))
    to_confirm = db.execute(select(func.count()).select_from(WorkItem).where(
        WorkItem.project_id == project.id, WorkItem.department == PM, WorkItem.status != "archived",
        WorkItem.provenance.in_(("ai_suggestion", "open_question")))).scalar_one()
    if to_confirm:
        out.append(_todo("confirm", f"Confirm or edit {to_confirm} AI suggestion{'s' if to_confirm != 1 else ''} "
                         "(meeting analyses and proposals)", "analysis"))
    for h in db.execute(select(Handoff).where(Handoff.project_id == project.id, Handoff.from_department == PM,
                                              Handoff.status == "clarification_requested")).scalars():
        out.append(_todo("clarification", f"The {h.to_department.replace('_', ' ')} asked for clarification: "
                         f"{h.reply[:200]}", "ba_handoff", urgent=True))
    incoming = db.execute(select(func.count()).select_from(Handoff).where(
        Handoff.project_id == project.id, Handoff.to_department == PM, Handoff.status == "sent")).scalar_one()
    if incoming:
        out.append(_todo("handoff", f"Acknowledge {incoming} handoff{'s' if incoming != 1 else ''} sent to you",
                         "handoffs"))
    for f in db.execute(select(OwnerFeedback).where(OwnerFeedback.project_id == project.id,
                                                    OwnerFeedback.profile_key == PM,
                                                    OwnerFeedback.status.in_(("open", "triaged")))).scalars():
        out.append(_todo("client", f"Client {f.kind.replace('_', ' ')}: {f.summary[:200]}", "conversations"))
    return out


def department_work(db: Session, project) -> dict[str, Any]:
    """Every lifecycle step of the current execution: department, status, who can approve it, and any problem."""
    from app.collab.service import explain, holders
    from app.portal.lifecycle import BY_PROFILE, DEPARTMENT_STAGES, STAGES
    from app.portal.service import DISPLAY
    from app.workflows import service as engine
    from app.workflows.models import WorkflowExecution, WorkflowVersion
    from app.workflows.state_machine import StageStatus as S

    execution = db.execute(select(WorkflowExecution).where(WorkflowExecution.project_id == project.id)
                           .order_by(WorkflowExecution.created_at.desc())).scalars().first()
    if execution is None:
        return {"started": False, "steps": [], "attention": []}
    known = {s.id: s for s in (*STAGES, *(st for group in DEPARTMENT_STAGES.values() for st in group))}
    rows = engine.stage_rows(db, execution.id)
    people: dict[str, list[str]] = {}
    steps, attention = [], []
    for spec in db.get(WorkflowVersion, execution.workflow_version_id).spec_json["stages"]:
        step, stage = known.get(spec["id"]), rows.get(spec["id"])
        if step is None or stage is None:
            continue
        if step.profile not in people:
            people[step.profile] = sorted(work._names(db, holders(db, project, step.profile)).values())
        status = S(stage.status)
        note = None
        if status in (S.FAILED, S.BLOCKED, S.REJECTED):
            note = explain(stage.failure_reason, True)
            attention.append(f"{BY_PROFILE[step.profile].title}: {step.name} stopped: {note}")
        elif status == S.AWAITING_HUMAN_REVIEW and not people[step.profile]:
            note = "Nobody is assigned to approve this"
            attention.append(f"{BY_PROFILE[step.profile].title}: {step.name} cannot be approved: nobody is assigned")
        steps.append({"stage": step.id, "number": step.number, "name": step.name, "department": step.profile,
                      "department_title": BY_PROFILE[step.profile].title, "status": DISPLAY[status],
                      "raw_status": stage.status, "people": people[step.profile], "note": note})
    return {"started": True, "steps": steps, "attention": attention}


def overview(db: Session, user: User, project_id: uuid.UUID) -> dict[str, Any]:
    project, scope = work._scope(db, user, project_id)
    if not work.reads_all(scope, PM):
        raise not_found()
    return {"todos": todos(db, project, user), "departments": department_work(db, project),
            "assigned": {"available": False, "arrives_in": "P6"}}
