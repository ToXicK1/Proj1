"""Where lifecycle steps and work records meet (step 7.1a, RD-17, RD-19).

- A step whose spec has a `records` map (output key -> record kind) turns each entry of that output list into a
  proposed record (`ai_suggestion`, authored by the step's agent, sourced to the step's artifact version).
- On rework, the step's AI suggestions nobody confirmed are archived and replaced; records a person confirmed or
  edited are kept.
- The step is approved through a package: submitting it assembles a system-authored artifact version from the exact
  record versions, runs the step's sensors on it, and the decision goes through the normal approval gate.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import service as activity
from app.artifacts.models import ArtifactVersion
from app.core.errors import AppError
from app.projects.models import Project
from app.work import service as work
from app.work.kinds import KINDS, InvalidBody, validate
from app.work.models import WorkItem, WorkItemVersion, WorkPackage

MAX_PER_STEP = 60


def _normal(field: Any, value: Any) -> Any:
    if field.type == "enum" and isinstance(value, str):
        candidate = value.strip().lower().replace("-", "_").replace(" ", "_")
        return candidate if candidate in field.choices else value
    if field.type == "list" and isinstance(value, str):
        return [line.strip("-• ").strip() for line in value.splitlines() if line.strip()]
    return value


def _title(entry: dict[str, Any]) -> str:
    for key in ("title", "name", "summary", "role", "question", "description"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    return ""


def propose_from_output(db: Session, *, project: Project, stage_execution_id: uuid.UUID, stage_key: str,
                        spec: dict[str, Any], output: dict[str, Any], artifact_version_id: uuid.UUID) -> int:
    """Turns the step's AI output into proposed records. Does not commit. Returns how many were proposed."""
    mapping: dict[str, str] = spec.get("records") or {}
    if not mapping:
        return 0
    department = spec.get("profile") or ""
    stale = db.execute(select(WorkItem).where(WorkItem.stage_execution_id == stage_execution_id,
                                              WorkItem.provenance == "ai_suggestion",
                                              WorkItem.status != "archived")).scalars().all()
    for item in stale:  # replaced by this run; confirmed and edited records stay
        item.status = "archived"
    made, skipped = 0, 0
    agent = spec.get("agent") or f"{stage_key}-lead"
    for output_key, kind_key in mapping.items():
        kind = KINDS.get(kind_key)
        entries = output.get(output_key)
        if kind is None or kind.department != department or not isinstance(entries, list):
            continue
        for entry in entries[:MAX_PER_STEP]:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            title = _title(entry)
            known = {f.name: f for f in kind.fields}
            body = {k: _normal(known[k], v) for k, v in entry.items() if k in known and v not in (None, "", [])}
            try:
                validate(kind, body)
            except InvalidBody:
                skipped += 1
                continue
            if not title:
                skipped += 1
                continue
            item = work.propose(db, project, department, agent=agent, kind=kind_key, title=title, body=body,
                                sources=[{"stage": stage_key, "artifact_version": str(artifact_version_id),
                                          "output_key": output_key}])
            item.stage_execution_id = stage_execution_id
            made += 1
    if made or skipped:
        activity.note("output", f"Proposed {made} record(s) for the professional to confirm"
                      + (f"; {skipped} entr{'y' if skipped == 1 else 'ies'} could not be used" if skipped else ""),
                      {"stage": stage_key, "proposed": made, "skipped": skipped})
    return made


def step_records(db: Session, stage_execution_id: uuid.UUID) -> list[WorkItem]:
    return list(db.execute(select(WorkItem).where(WorkItem.stage_execution_id == stage_execution_id,
                                                  WorkItem.status != "archived")).scalars())


def bind_package(db: Session, *, project: Project, stage_key: str, department: str,
                 items: list[WorkItem]) -> tuple[uuid.UUID, uuid.UUID]:
    """Checks the step can take this package, then writes the step's new artifact version. Does not commit.
    Returns (stage execution id, artifact version id)."""
    from app.artifacts import service as artifacts
    from app.sensors import service as sensors
    from app.workflows import service as engine
    from app.workflows.models import WorkflowExecution, WorkflowVersion
    from app.workflows.state_machine import StageStatus

    execution = db.execute(select(WorkflowExecution).where(WorkflowExecution.project_id == project.id)
                           .order_by(WorkflowExecution.created_at.desc())).scalars().first()
    if execution is None:
        raise AppError(409, "not_started", "The project's lifecycle has not started")
    stage = engine.stage_rows(db, execution.id).get(stage_key)
    spec = engine.stage_spec(db.get(WorkflowVersion, execution.workflow_version_id), stage_key) if stage else None
    if stage is None or spec is None or spec.get("profile") != department or not spec.get("records"):
        raise AppError(422, "not_a_record_step", "This step is not one of this department's record steps")
    if spec.get("sandbox"):
        raise AppError(422, "not_a_record_step", "Steps that build code are approved on their build evidence")
    if stage.status != StageStatus.AWAITING_HUMAN_REVIEW.value:
        raise AppError(409, "not_awaiting_review", "This step is not waiting for a decision")
    chosen = {i.id for i in items}
    missing = [i.key for i in step_records(db, stage.id) if i.id not in chosen]
    if missing:
        raise AppError(422, "package_incomplete", "Every record of this step must be in its package, or archived",
                       problems=[f"{k} is not included" for k in missing])
    current = artifacts.current_version(db, stage.id)
    content: dict[str, Any] = dict(current[1].content_json) if current else {}
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(items, key=lambda i: i.key):
        v = db.get(WorkItemVersion, item.current_version_id)
        by_kind.setdefault(item.kind, []).append({"key": item.key, "title": v.title, "version": v.number,
                                                  "provenance": v.provenance, **v.body})
    for output_key, kind_key in spec["records"].items():
        content[output_key] = by_kind.get(kind_key, [])
    content["_package"] = "assembled from the professional's confirmed records"
    version = artifacts.create_version(db, project_id=project.id, stage_execution_id=stage.id,
                                       kind=spec.get("artifact_kind", stage_key), content=content)
    sensors.run_stage_sensors(db, execution, stage, spec, version)
    return stage.id, version.id


def send_back(db: Session, user: Any, *, project: Project, review_key: str, target_key: str, note: str) -> uuid.UUID:
    """From the department's review (or after the owner's input), send one approved step back for rework with the
    professional's note. The review waits until that step and everything after it are approved again, then is
    gathered afresh. Returns the execution to drive."""
    from app.approvals.models import ChangeRequest
    from app.artifacts import service as artifacts
    from app.core.db import uuid7
    from app.workflows import service as engine
    from app.workflows.models import WorkflowExecution, WorkflowVersion
    from app.workflows.state_machine import ActorType, StageStatus

    if not note.strip():
        raise AppError(422, "note_required", "Say what needs to change")
    execution = db.execute(select(WorkflowExecution).where(WorkflowExecution.project_id == project.id)
                           .order_by(WorkflowExecution.created_at.desc())).scalars().first()
    if execution is None:
        raise AppError(409, "not_started", "The project's lifecycle has not started")
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    specs = {s["id"]: s for s in version.spec_json["stages"]}
    review, target = specs.get(review_key), specs.get(target_key)
    if review is None or review.get("work") not in ("department_review", "owner_review"):
        raise AppError(422, "not_a_review", "Only the department's review steps can send work back")
    if not work.edits(db, user, project, review.get("profile") or ""):
        raise AppError(403, "not_permitted", "Only the department's assigned professionals can do this")
    if target is None or target.get("profile") != review.get("profile") or target_key not in (review.get("reads") or []):
        raise AppError(422, "not_upstream", "Choose one of this department's earlier steps")
    if target.get("work") != "ai:stage_work":
        raise AppError(422, "not_upstream", "Only AI steps can be reworked")
    rows = engine.stage_rows(db, execution.id)
    if rows[review_key].status != StageStatus.AWAITING_HUMAN_REVIEW.value:
        raise AppError(409, "not_awaiting_review", "The review is not waiting for a decision")
    if rows[target_key].status != StageStatus.APPROVED.value:
        raise AppError(409, "not_approved", "That step is not approved, so there is nothing to send back")
    current = artifacts.current_version(db, rows[target_key].id)
    engine.transition_stage(db, execution_id=execution.id, stage_key=target_key,
                            to_status=StageStatus.CHANGES_REQUESTED, actor=ActorType.HUMAN, actor_id=str(user.id),
                            reason=f"sent back from {review['name']}"[:300], commit=False)
    db.add(ChangeRequest(id=uuid7(), stage_execution_id=rows[target_key].id, artifact_version_id=current[1].id,
                         author_user_id=user.id, status="open", comment=note.strip()))
    order = [s["id"] for s in version.spec_json["stages"]]
    for key in order[order.index(target_key) + 1:]:  # later steps, up to and including the review, wait
        stage = rows[key]
        if stage.status == StageStatus.APPROVED.value:
            engine.transition_stage(db, execution_id=execution.id, stage_key=key,
                                    to_status=StageStatus.AWAITING_HUMAN_REVIEW, actor=ActorType.SYSTEM,
                                    reason=f"'{target['name']}' was sent back", commit=False)
            stage.approval_epoch += 1
        if key == review_key:
            break
    engine.transition_stage(db, execution_id=execution.id, stage_key=review_key,
                            to_status=StageStatus.CHANGES_REQUESTED, actor=ActorType.HUMAN, actor_id=str(user.id),
                            reason=f"sent '{target['name']}' back: {note.strip()}"[:300], commit=False)
    work._audit(db, project, "work.step_sent_back", user, {"from": review_key, "step": target_key})
    db.commit()
    return execution.id


def is_package_version(db: Session, version: ArtifactVersion) -> bool:
    return db.execute(select(WorkPackage.id).where(WorkPackage.artifact_version_id == version.id)).first() is not None


def decide_step(db: Session, user: Any, package: WorkPackage, decision: str, note: str) -> None:
    """The package decision, through the step's gate. Commits (the approval service does)."""
    from app.approvals import service as approvals
    from app.workflows.models import StageExecution

    stage = db.get(StageExecution, package.stage_execution_id)
    approvals.submit_decision(db, user, execution_id=stage.workflow_execution_id, stage_key=stage.stage_key,
                              artifact_version_id=package.artifact_version_id,
                              decision="APPROVE" if decision == "approve" else "REQUEST_CHANGES",
                              comment=note, idempotency_key=f"package:{package.id}:{decision}")
