"""Human approval engine (APPROVAL_GOVERNANCE.md).

Rules enforced here, inside one locked transaction per decision:
- only a project member with a role named by the policy can decide; non-members get not_found
- a decision binds to one artifact version; a newer version makes older approvals stop counting
- one person fills at most one approval slot per version; sequential steps open in order
- an author cannot approve their own artifact version
- a repeated request with the same idempotency key returns the original result
- reject and request-changes need a comment
- APPROVED, and workflow completion, happen in the same transaction as the approval row
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.models import DECISIONS, ApprovalDecision, ChangeRequest
from app.approvals.policy import (
    DEFAULT_POLICY,
    Slot,
    is_complete,
    open_slot_for,
    parse_policy,
    satisfied_slots,
    slots_for,
)
from app.artifacts import service as artifacts
from app.artifacts.models import ArtifactVersion
from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.workflows.models import StageExecution, WorkflowExecution, WorkflowVersion
from app.workflows.service import (
    lock_stage,
    project_role,
    stage_rows,
    stage_spec,
    transition_stage,
)
from app.workflows.state_machine import ActorType, StageStatus

MAX_COMMENT = 2000


def _slots(db: Session, execution: WorkflowExecution, stage_key: str) -> list[Slot]:
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    raw = stage_spec(version, stage_key).get("approval_policy") or DEFAULT_POLICY
    return slots_for(parse_policy(raw))


def _approvals_by_slot(db: Session, artifact_version_id: uuid.UUID, epoch: int) -> dict[str, set[uuid.UUID]]:
    """Approvals for this version that still count (same approval epoch as the stage)."""
    rows = db.execute(
        select(ApprovalDecision.policy_slot, ApprovalDecision.approver_user_id).where(
            ApprovalDecision.artifact_version_id == artifact_version_id,
            ApprovalDecision.approval_epoch == epoch,
            ApprovalDecision.decision == "APPROVE",
        )
    ).all()
    grouped: dict[str, set[uuid.UUID]] = {}
    for slot, approver in rows:
        grouped.setdefault(slot, set()).add(approver)
    return grouped


def _current(db: Session, stage: StageExecution) -> tuple[Any, ArtifactVersion] | None:
    return artifacts.current_version(db, stage.id)


def _dependents(db: Session, execution: WorkflowExecution, stage_key: str) -> list[str]:
    """Every stage downstream of stage_key, nearest first, without duplicates."""
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    children: dict[str, list[str]] = {s["id"]: [] for s in version.spec_json["stages"]}
    for s in version.spec_json["stages"]:
        for dep in s["depends_on"]:
            children[dep].append(s["id"])
    seen: list[str] = []
    frontier = list(children[stage_key])
    while frontier:
        node = frontier.pop(0)
        if node not in seen:
            seen.append(node)
            frontier.extend(children[node])
    return seen


def _complete_if_done(db: Session, execution: WorkflowExecution) -> None:
    stages = stage_rows(db, execution.id).values()
    if execution.status == "RUNNING" and all(
        s.status in {StageStatus.APPROVED.value, StageStatus.SKIPPED.value} for s in stages
    ):
        execution.status = "COMPLETED"
        append_event(
            db,
            chain_key=org_chain(execution.organization_id),
            event_type="workflow.completed",
            actor_type=ActorType.SYSTEM.value,
            organization_id=execution.organization_id,
            project_id=execution.project_id,
            payload={"workflow_execution": execution.id.hex},
        )


def _display_name(db: Session, user_id: uuid.UUID) -> str:
    user = db.get(User, user_id)
    return user.display_name if user else "Unknown"


def submit_decision(
    db: Session,
    user: User,
    *,
    execution_id: uuid.UUID,
    stage_key: str,
    artifact_version_id: uuid.UUID,
    decision: str,
    comment: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise AppError(422, "invalid_decision", "Decision must be APPROVE, REJECT or REQUEST_CHANGES")
    comment = comment.strip()
    if len(comment) > MAX_COMMENT:
        raise AppError(422, "comment_too_long", f"Comment must be at most {MAX_COMMENT} characters")
    try:
        execution, stage = lock_stage(db, execution_id, stage_key)
        role = project_role(db, user, execution.project_id)
        if role is None:
            raise not_found()

        existing = db.execute(
            select(ApprovalDecision).where(
                ApprovalDecision.approver_user_id == user.id,
                ApprovalDecision.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.artifact_version_id != artifact_version_id or existing.decision != decision:
                raise AppError(409, "idempotency_conflict", "This key was already used for a different decision")
            db.rollback()
            return review_view(db, user, execution_id, stage_key)

        if stage.status != StageStatus.AWAITING_HUMAN_REVIEW.value:
            raise AppError(409, "not_awaiting_review", "This stage is not waiting for a decision")
        current = _current(db, stage)
        if current is None or current[1].id != artifact_version_id:
            raise AppError(409, "stale_version", "A newer version exists; review the current version")
        _, version = current
        if version.author_user_id == user.id:
            raise AppError(403, "separation_of_duties", "You cannot approve an artifact you authored")
        if decision != "APPROVE" and not comment:
            raise AppError(422, "comment_required", "A comment is required to reject or request changes")

        slots = _slots(db, execution, stage_key)
        approvals = _approvals_by_slot(db, version.id, stage.approval_epoch)

        if decision == "APPROVE":
            if any(user.id in people for people in approvals.values()):
                raise AppError(409, "already_approved", "You already approved this version")
            slot = open_slot_for(slots, role, approvals, user.id)
            if slot is None:
                raise AppError(403, "approval_not_permitted", "No open approval slot matches your role")
            approvals.setdefault(slot.id, set()).add(user.id)
            db.add(_record(execution, stage, version, user, decision, slot.id, comment, idempotency_key, slots, approvals))
            append_event(
                db,
                chain_key=org_chain(execution.organization_id),
                event_type="approval.recorded",
                actor_type=ActorType.HUMAN.value,
                actor_id=str(user.id),
                organization_id=execution.organization_id,
                project_id=execution.project_id,
                payload={"stage": stage_key, "slot": slot.id, "version": version.version_number},
            )
            db.flush()
            if is_complete(slots, approvals):
                transition_stage(db, execution_id=execution.id, stage_key=stage_key, to_status=StageStatus.APPROVED,
                                 actor=ActorType.HUMAN, actor_id=str(user.id), reason="policy satisfied",
                                 approval_satisfied=True, commit=False)
                _complete_if_done(db, execution)
        else:
            db.add(_record(execution, stage, version, user, decision, None, comment, idempotency_key, slots, approvals))
            if decision == "REJECT":
                transition_stage(db, execution_id=execution.id, stage_key=stage_key, to_status=StageStatus.REJECTED,
                                 actor=ActorType.HUMAN, actor_id=str(user.id), reason=comment[:300], commit=False)
            else:
                db.add(
                    ChangeRequest(
                        id=uuid7(),
                        stage_execution_id=stage.id,
                        artifact_version_id=version.id,
                        author_user_id=user.id,
                        comment=comment,
                        status="open",
                    )
                )
                transition_stage(db, execution_id=execution.id, stage_key=stage_key,
                                 to_status=StageStatus.CHANGES_REQUESTED, actor=ActorType.HUMAN,
                                 actor_id=str(user.id), reason=comment[:300], commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return review_view(db, user, execution_id, stage_key)


def _record(
    execution: WorkflowExecution,
    stage: StageExecution,
    version: ArtifactVersion,
    user: User,
    decision: str,
    slot_id: str | None,
    comment: str,
    idempotency_key: str,
    slots: list[Slot],
    approvals: dict[str, set[uuid.UUID]],
) -> ApprovalDecision:
    return ApprovalDecision(
        id=uuid7(),
        organization_id=execution.organization_id,
        project_id=execution.project_id,
        stage_execution_id=stage.id,
        artifact_version_id=version.id,
        approval_epoch=stage.approval_epoch,
        approver_user_id=user.id,
        approver_type="human",
        decision=decision,
        policy_slot=slot_id,
        comment=comment,
        idempotency_key=idempotency_key,
        content_sha256=version.content_sha256,
        validation_snapshot={
            "version_number": version.version_number,
            "satisfied_slots": sorted(satisfied_slots(slots, approvals)),
            "mandatory_sensors": [],
        },
    )


def record_upstream_change(
    db: Session,
    *,
    execution_id: uuid.UUID,
    stage_key: str,
    content: dict[str, Any],
    author_user_id: uuid.UUID | None = None,
) -> None:
    """A new version of an APPROVED stage's artifact invalidates that approval and any approved
    downstream stage. The approvals of the old version stop counting, because the stage now
    judges a newer version."""
    try:
        execution, stage = lock_stage(db, execution_id, stage_key)
        if stage.status != StageStatus.APPROVED.value:
            raise AppError(409, "not_approved", "Only an approved stage can be changed upstream")
        artifacts.create_version(
            db,
            project_id=execution.project_id,
            stage_execution_id=stage.id,
            kind=stage_key,
            content=content,
            author_user_id=author_user_id,
        )
        transition_stage(db, execution_id=execution_id, stage_key=stage_key, to_status=StageStatus.AWAITING_HUMAN_REVIEW,
                         actor=ActorType.SYSTEM, reason="upstream artifact changed", commit=False)
        stage.approval_epoch += 1  # approvals of the previous epoch stop counting
        stages = stage_rows(db, execution.id)
        for key in _dependents(db, execution, stage_key):
            if stages[key].status == StageStatus.APPROVED.value:
                transition_stage(db, execution_id=execution_id, stage_key=key,
                                 to_status=StageStatus.AWAITING_HUMAN_REVIEW, actor=ActorType.SYSTEM,
                                 reason=f"upstream stage '{stage_key}' changed", commit=False)
                stages[key].approval_epoch += 1
        if execution.status == "COMPLETED":
            execution.status = "RUNNING"
            append_event(db, chain_key=org_chain(execution.organization_id), event_type="workflow.reopened",
                         actor_type=ActorType.SYSTEM.value, organization_id=execution.organization_id,
                         project_id=execution.project_id, payload={"workflow_execution": execution.id.hex})
        db.commit()
    except Exception:
        db.rollback()
        raise


def review_view(db: Session, user: User, execution_id: uuid.UUID, stage_key: str) -> dict[str, Any]:
    execution = db.get(WorkflowExecution, execution_id)
    role = project_role(db, user, execution.project_id) if execution else None
    if execution is None or role is None:
        raise not_found()
    stage = stage_rows(db, execution_id).get(stage_key)
    if stage is None:
        raise not_found()
    spec = stage_spec(db.get(WorkflowVersion, execution.workflow_version_id), stage_key)
    slots = _slots(db, execution, stage_key)

    current = _current(db, stage)
    artifact_block = None
    approvals: dict[str, set[uuid.UUID]] = {}
    decisions: list[dict[str, Any]] = []
    change_requests: list[dict[str, Any]] = []
    if current is not None:
        artifact, version = current
        approvals = _approvals_by_slot(db, version.id, stage.approval_epoch)
        artifact_block = {
            "kind": artifact.kind,
            "version_id": str(version.id),
            "version_number": version.version_number,
            "content": version.content_json,
            "content_sha256": version.content_sha256,
        }
        rows = db.execute(
            select(ApprovalDecision).where(
                ApprovalDecision.artifact_version_id == version.id,
                ApprovalDecision.approval_epoch == stage.approval_epoch,
            )
            .order_by(ApprovalDecision.decided_at)
        ).scalars()
        decisions = [
            {"decision": d.decision, "approver": _display_name(db, d.approver_user_id), "comment": d.comment,
             "decided_at": d.decided_at.isoformat(), "policy_slot": d.policy_slot}
            for d in rows
        ]
        crs = db.execute(
            select(ChangeRequest).where(ChangeRequest.stage_execution_id == stage.id)
            .order_by(ChangeRequest.created_at)
        ).scalars()
        change_requests = [
            {"comment": c.comment, "status": c.status, "author": _display_name(db, c.author_user_id)}
            for c in crs
        ]

    reviews: list[dict[str, Any]] = []
    if current is not None:
        from app.agents.models import ReviewRecord

        for rec in db.execute(select(ReviewRecord).where(
                ReviewRecord.stage_execution_id == stage.id,
                ReviewRecord.artifact_version_id == current[1].id)).scalars():
            reviews.append({"verdict": rec.verdict, "findings": rec.findings,
                            "reviewed_at": rec.created_at.isoformat()})
    done = satisfied_slots(slots, approvals)
    can_decide = False
    if current is not None and stage.status == StageStatus.AWAITING_HUMAN_REVIEW.value:
        can_decide = open_slot_for(slots, role, approvals, user.id) is not None and (
            current[1].author_user_id != user.id
        )

    return {
        "stage": {
            "key": stage_key,
            "name": spec["name"],
            "status": stage.status,
            "version": stage.version,
            "rework_count": stage.rework_count,
        },
        "artifact": artifact_block,
        "policy": {
            "slots": [
                {
                    "id": s.id,
                    "roles": sorted(s.roles),
                    "required": s.required,
                    "satisfied": s.id in done,
                    "approvals": len(approvals.get(s.id, set())),
                }
                for s in slots
            ]
        },
        "decisions": decisions,
        "reviews": reviews,
        "change_requests": change_requests,
        "can_decide": can_decide,
        "your_role": role,
    }

