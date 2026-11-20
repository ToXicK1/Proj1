"""Human supervision of a running stage: escalations that pause it, and questions to the project owner.

Only people move these states. Escalating and resolving are for the professional team (the stage's department,
project managers, administrators). Asking the owner is for whoever may approve the stage; only the owner answers.
An answer goes back to the AI as feedback through the normal rework path, and the professional still decides.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.models import ChangeRequest
from app.artifacts import service as artifacts
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.hooks import service as hooks
from app.portal.lifecycle import BY_PROFILE, BY_STAGE
from app.projects.models import Project
from app.workflows import service as engine
from app.workflows.models import OwnerQuestion, StageEscalation, StageExecution, WorkflowExecution
from app.workflows.state_machine import ActorType, StageStatus

S = StageStatus
SETTLED = {S.APPROVED.value, S.COMPLETED.value, S.SKIPPED.value, S.CANCELLED.value}


def _stage(db: Session, user: User, project_id: uuid.UUID, stage_key: str) -> tuple[Project, Any, WorkflowExecution,
                                                                                    StageExecution]:
    from app.collab.service import scope_for
    from app.portal.service import _execution

    project, scope = scope_for(db, user, project_id)
    execution = _execution(db, project_id)
    step = BY_STAGE.get(stage_key)
    stage = engine.stage_rows(db, execution.id).get(stage_key) if execution and step else None
    if stage is None or (scope.kind == "professional" and step.profile not in scope.profiles):
        raise not_found()
    return project, scope, execution, stage


def _supervises(scope: Any, profile: str) -> bool:
    return scope.kind in ("admin", "manager") or (scope.kind == "professional" and profile in scope.profiles)


def _audit_and_notify(db: Session, project: Project, user: User, event: str, payload: dict[str, Any],
                      people: set[uuid.UUID], kind: str, message: str) -> None:
    from app.portal.service import _audit, _notify_users

    _audit(db, project, event, "human", user.id, payload)
    _notify_users(db, project, people - {user.id}, kind, message)


def _team(db: Session, project: Project, profile: str) -> set[uuid.UUID]:
    from app.collab.service import holders
    from app.organizations.models import Membership

    overseers = set(db.execute(select(Membership.user_id).where(
        Membership.organization_id == project.organization_id, Membership.status == "active",
        Membership.role.in_(("org_admin", "project_manager")))).scalars())
    return holders(db, project, profile) | overseers


def _escalation_out(row: StageEscalation, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {"id": str(row.id), "status": row.status, "reason": row.reason, "raised_by": names.get(row.raised_by, ""),
            "resolution": row.resolution, "resolved_by": names.get(row.resolved_by) if row.resolved_by else None,
            "raised_at": row.created_at.isoformat(), "resolved_at": row.resolved_at.isoformat() if row.resolved_at
            else None}


def _names(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict(db.execute(select(User.id, User.display_name).where(User.id.in_(wanted))).all())


# Escalations --------------------------------------------------------------------------------------------------------

def escalate(db: Session, user: User, project_id: uuid.UUID, stage_key: str, reason: str) -> dict[str, Any]:
    project, scope, execution, stage = _stage(db, user, project_id, stage_key)
    step = BY_STAGE[stage_key]
    if scope.kind == "owner":
        raise AppError(403, "not_permitted", "Owners raise a ticket; the professional team escalates")
    if not _supervises(scope, step.profile):
        raise AppError(403, "not_permitted", "Only this department, a project manager or an administrator can escalate")
    try:
        _, stage = engine.lock_stage(db, execution.id, stage_key)
        if stage.status in SETTLED:
            raise AppError(409, "stage_settled", "This step is already finished")
        if engine.open_escalation(db, stage) is not None:
            raise AppError(409, "already_escalated", "This step is already escalated")
        row = StageEscalation(id=uuid7(), stage_execution_id=stage.id, project_id=project.id, raised_by=user.id,
                              reason=reason.strip())
        db.add(row)
        db.flush()
        hooks.run_hooks(db, engine.hook_scope(db, execution, stage_key), "stage.escalated")
        _audit_and_notify(db, project, user, "stage.escalated", {"stage": stage_key, "escalation": str(row.id)},
                          _team(db, project, step.profile), f"escalation:{row.id}",
                          f"{step.name} on {project.name} was escalated and is paused: {reason.strip()[:140]}")
        db.commit()
        return _escalation_out(row, _names(db, {row.raised_by}))
    except Exception:
        db.rollback()
        raise


def resolve(db: Session, user: User, project_id: uuid.UUID, escalation_id: uuid.UUID,
            resolution: str) -> tuple[dict[str, Any], uuid.UUID]:
    row = db.get(StageEscalation, escalation_id)
    if row is None or row.project_id != project_id:
        raise not_found()
    stage = db.get(StageExecution, row.stage_execution_id)
    project, scope, execution, _ = _stage(db, user, project_id, stage.stage_key)
    step = BY_STAGE[stage.stage_key]
    if not _supervises(scope, step.profile):
        raise AppError(403, "not_permitted", "Only this department, a project manager or an administrator can resolve")
    try:
        row = db.execute(select(StageEscalation).where(StageEscalation.id == escalation_id).with_for_update()
                         .execution_options(populate_existing=True)).scalar_one()
        if row.status != "open":
            raise AppError(409, "already_resolved", "This escalation is already resolved")
        row.status, row.resolution, row.resolved_by = "resolved", resolution.strip(), user.id
        row.resolved_at = datetime.now(UTC)
        hooks.run_hooks(db, engine.hook_scope(db, execution, stage.stage_key), "stage.escalation_resolved")
        _audit_and_notify(db, project, user, "stage.escalation_resolved",
                          {"stage": stage.stage_key, "escalation": str(row.id)}, {row.raised_by},
                          f"escalation_resolved:{row.id}", f"The escalation on {step.name} was resolved.")
        db.commit()
        return _escalation_out(row, _names(db, {row.raised_by, row.resolved_by})), execution.id
    except Exception:
        db.rollback()
        raise


def escalations(db: Session, user: User, project_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.collab.service import scope_for

    _, scope = scope_for(db, user, project_id)
    if not scope.internal:
        raise AppError(403, "not_permitted", "Escalations are for the professional team")
    rows = db.execute(select(StageEscalation, StageExecution.stage_key)
                      .join(StageExecution, StageExecution.id == StageEscalation.stage_execution_id)
                      .where(StageEscalation.project_id == project_id)
                      .order_by(StageEscalation.created_at.desc())).all()
    rows = [(r, key) for r, key in rows if scope.kind != "professional" or BY_STAGE[key].profile in scope.profiles]
    names = _names(db, {r.raised_by for r, _ in rows} | {r.resolved_by for r, _ in rows})
    return [{**_escalation_out(r, names), "stage": key, "stage_name": BY_STAGE[key].name} for r, key in rows]


# Questions to the owner ------------------------------------------------------------------------------------------------

def ask_owner(db: Session, user: User, project_id: uuid.UUID, stage_key: str, question: str) -> dict[str, Any]:
    project, scope, execution, stage = _stage(db, user, project_id, stage_key)
    step = BY_STAGE[stage_key]
    if not (scope.kind == "admin" or (scope.kind == "professional" and step.profile in scope.profiles)):
        raise AppError(403, "not_permitted", f"Only the {BY_PROFILE[step.profile].title} can ask about this work")
    try:
        engine.transition_stage(db, execution_id=execution.id, stage_key=stage_key,
                                to_status=S.AWAITING_USER_INPUT, actor=ActorType.HUMAN, actor_id=str(user.id),
                                reason="asked the project owner a question", commit=False)
        row = OwnerQuestion(id=uuid7(), stage_execution_id=stage.id, project_id=project.id, asked_by=user.id,
                            question=question.strip())
        db.add(row)
        db.flush()
        from app.portal.service import _notify

        _notify(db, project, {"project_owner"}, f"owner_question:{row.id}",
                f"{BY_PROFILE[step.profile].title} has a question about {step.name}.")
        _audit_and_notify(db, project, user, "stage.question_asked", {"stage": stage_key, "question": str(row.id)},
                          set(), "", "")
        db.commit()
        return {"id": str(row.id), "status": row.status}
    except Exception:
        db.rollback()
        raise


def answer(db: Session, user: User, project_id: uuid.UUID, question_id: uuid.UUID,
           text: str) -> uuid.UUID:
    """The owner's answer becomes feedback for the AI's next version. Returns the execution to drive."""
    from app.portal.service import _owner

    project = _owner(db, user, project_id)
    row = db.get(OwnerQuestion, question_id)
    if row is None or row.project_id != project.id:
        raise not_found()
    stage = db.get(StageExecution, row.stage_execution_id)
    try:
        row = db.execute(select(OwnerQuestion).where(OwnerQuestion.id == question_id).with_for_update()
                         .execution_options(populate_existing=True)).scalar_one()
        if row.status != "open":
            raise AppError(409, "question_closed", "This question was already answered or withdrawn")
        current = artifacts.current_version(db, stage.id)
        if current is None:
            raise AppError(409, "no_artifact", "There is no work to change yet")
        engine.transition_stage(db, execution_id=stage.workflow_execution_id, stage_key=stage.stage_key,
                                to_status=S.CHANGES_REQUESTED, actor=ActorType.HUMAN, actor_id=str(user.id),
                                reason="the project owner answered", commit=False)
        db.add(ChangeRequest(id=uuid7(), stage_execution_id=stage.id, artifact_version_id=current[1].id,
                             author_user_id=user.id, status="open",
                             comment=f'The project owner answered the question "{row.question}": {text.strip()}'))
        row.status, row.answer, row.answered_by, row.answered_at = "answered", text.strip(), user.id, datetime.now(UTC)
        step = BY_STAGE[stage.stage_key]
        _audit_and_notify(db, project, user, "stage.question_answered", {"stage": stage.stage_key,
                                                                         "question": str(row.id)},
                          {row.asked_by}, f"owner_answer:{row.id}",
                          f"The project owner answered your question about {step.name}. The AI is updating the work.")
        db.commit()
        return stage.workflow_execution_id
    except Exception:
        db.rollback()
        raise


def withdraw(db: Session, user: User, project_id: uuid.UUID, question_id: uuid.UUID) -> dict[str, Any]:
    row = db.get(OwnerQuestion, question_id)
    if row is None or row.project_id != project_id:
        raise not_found()
    stage = db.get(StageExecution, row.stage_execution_id)
    project, scope, execution, _ = _stage(db, user, project_id, stage.stage_key)
    step = BY_STAGE[stage.stage_key]
    if not (scope.kind == "admin" or (scope.kind == "professional" and step.profile in scope.profiles)):
        raise AppError(403, "not_permitted", "Only the department that asked can withdraw the question")
    try:
        if row.status != "open":
            raise AppError(409, "question_closed", "This question was already answered or withdrawn")
        engine.transition_stage(db, execution_id=execution.id, stage_key=stage.stage_key,
                                to_status=S.AWAITING_HUMAN_REVIEW, actor=ActorType.HUMAN, actor_id=str(user.id),
                                reason="question withdrawn", commit=False)
        row.status = "withdrawn"
        _audit_and_notify(db, project, user, "stage.question_withdrawn", {"stage": stage.stage_key,
                                                                          "question": str(row.id)}, set(), "", "")
        db.commit()
        return {"id": str(row.id), "status": row.status}
    except Exception:
        db.rollback()
        raise


def open_questions(db: Session, project_id: uuid.UUID) -> list[tuple[OwnerQuestion, str]]:
    return list(db.execute(select(OwnerQuestion, StageExecution.stage_key)
                           .join(StageExecution, StageExecution.id == OwnerQuestion.stage_execution_id)
                           .where(OwnerQuestion.project_id == project_id, OwnerQuestion.status == "open")
                           .order_by(OwnerQuestion.created_at)).all())
