"""Approval engine against a real database: version binding, policies, rework, invalidation, atomicity."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.approvals import service as approvals
from app.approvals.models import ApprovalDecision, ChangeRequest
from app.artifacts import service as artifacts
from app.artifacts.models import Artifact
from app.audit.service import org_chain, verify_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError
from app.projects.models import ProjectMember
from app.workflows import service as wf
from app.workflows.models import StageExecution, StageTransition, WorkflowExecution, WorkflowVersion
from app.workflows.seed import seed_templates
from tests.helpers import signup_verify_login

PW = "correct-horse-battery-staple"
JOINT = {
    "key": "joint-review",
    "name": "Joint review",
    "stages": [
        {
            "id": "review",
            "name": "Joint review",
            "depends_on": [],
            "work": "intake_summary",
            "output_required_keys": ["word_count"],
            "approval_policy": {"type": "all_of", "roles": ["project_owner", "internal_reviewer"]},
        }
    ],
}
ORDERED = {
    "key": "ordered-review",
    "name": "Ordered review",
    "stages": [
        {
            "id": "review",
            "name": "Ordered review",
            "depends_on": [],
            "work": "intake_summary",
            "output_required_keys": ["word_count"],
            "approval_policy": {
                "type": "sequential",
                "steps": [{"role": "internal_reviewer"}, {"role": "project_owner"}],
            },
        }
    ],
}


@dataclass
class Ctx:
    engine: object
    app: object
    owner_id: uuid.UUID
    owner_csrf: str
    project_id: uuid.UUID
    execution_id: uuid.UUID
    version_id: uuid.UUID


def _user_id(engine, email: str) -> uuid.UUID:
    with Session(engine) as s:
        return s.execute(select(User.id).where(User.email == email)).scalar_one()


def _add_member(engine, project_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    with Session(engine) as s:
        s.add(ProjectMember(id=uuid7(), project_id=project_id, user_id=user_id, project_role=role))
        s.commit()


def _publish(engine, raw: dict) -> uuid.UUID:
    with Session(engine) as s:
        return wf.publish_version(s, raw).id


def _seeded_version(engine) -> uuid.UUID:
    with Session(engine) as s:
        seed_templates(s)
        from app.workflows.models import WorkflowDefinition

        definition = s.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.key == "discovery-foundation")
        ).scalar_one()
        return s.execute(
            select(WorkflowVersion.id).where(WorkflowVersion.definition_id == definition.id)
        ).scalar_one()


def _project(client, engine, email: str):
    csrf = signup_verify_login(client, engine, email)
    org_id = client.get("/api/v1/orgs").json()["items"][0]["id"]
    project = client.post(
        f"/api/v1/orgs/{org_id}/projects",
        json={"name": "Hiring hub", "description": "Job descriptions and candidate matching", "project_type": "SaaS Platform"},
        headers={"X-CSRF-Token": csrf},
    ).json()
    return csrf, project


def _start(client, engine, email: str, version_id: uuid.UUID) -> Ctx:
    csrf, project = _project(client, engine, email)
    execution_id = client.post(
        f"/api/v1/projects/{project['id']}/workflow-executions",
        json={"workflow_version_id": str(version_id)},
        headers={"X-CSRF-Token": csrf},
    ).json()["id"]
    return Ctx(
        engine=engine,
        app=client.app,
        owner_id=_user_id(engine, email),
        owner_csrf=csrf,
        project_id=uuid.UUID(project["id"]),
        execution_id=uuid.UUID(execution_id),
        version_id=version_id,
    )


@pytest.fixture
def ctx(client, engine) -> Ctx:
    return _start(client, engine, "approver-owner@example.com", _seeded_version(engine))


def _stage(engine, execution_id, key) -> StageExecution:
    with Session(engine) as s:
        row = s.execute(
            select(StageExecution).where(
                StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == key
            )
        ).scalar_one()
        s.expunge(row)
        return row


def _status(engine, execution_id, key) -> str:
    return _stage(engine, execution_id, key).status


def _current_version(engine, execution_id, key) -> uuid.UUID:
    stage = _stage(engine, execution_id, key)
    with Session(engine) as s:
        return s.execute(select(Artifact.current_version_id).where(Artifact.stage_execution_id == stage.id)).scalar_one()


def _run(engine, execution_id, key):
    with Session(engine) as s:
        return wf.run_deterministic_stage(s, execution_id=execution_id, stage_key=key)


def _decide(engine, execution_id, user_id, key, version_id, decision, comment="", idem=None):
    idem = idem or f"k-{uuid.uuid4().hex}"
    with Session(engine) as s:
        user = s.get(User, user_id)
        return approvals.submit_decision(
            s, user, execution_id=execution_id, stage_key=key, artifact_version_id=version_id,
            decision=decision, comment=comment, idempotency_key=idem,
        )


def _decision_rows(engine, version_id) -> list[str]:
    with Session(engine) as s:
        return [r.decision for r in s.execute(
            select(ApprovalDecision).where(ApprovalDecision.artifact_version_id == version_id)).scalars()]


# --- single policy, default for stages without one -----------------------------------------------

def test_owner_approval_completes_the_chain_and_the_workflow(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    view = _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "APPROVE")
    assert view["stage"]["status"] == "APPROVED"
    assert _status(engine, ctx.execution_id, "outline") == "READY"

    _run(engine, ctx.execution_id, "outline")
    v2 = _current_version(engine, ctx.execution_id, "outline")
    _decide(engine, ctx.execution_id, ctx.owner_id, "outline", v2, "APPROVE")
    with Session(engine) as s:
        execution = s.get(WorkflowExecution, ctx.execution_id)
        assert execution.status == "COMPLETED"
        assert verify_chain(s, org_chain(s.get(WorkflowExecution, ctx.execution_id).organization_id)) == []
    with engine.connect() as conn:
        events = {r[0] for r in conn.execute(text("select event_type from audit_events where project_id = :p"),
                                             {"p": str(ctx.project_id)})}
    assert {"approval.recorded", "stage.approved", "workflow.completed"} <= events


def test_approval_of_version_one_does_not_satisfy_version_two(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v1 = _current_version(engine, ctx.execution_id, "intake")
    _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v1, "REQUEST_CHANGES", comment="Add the target users")
    assert _status(engine, ctx.execution_id, "intake") == "CHANGES_REQUESTED"

    with Session(engine) as s:
        wf.run_rework(s, execution_id=ctx.execution_id, stage_key="intake")
    v2 = _current_version(engine, ctx.execution_id, "intake")
    assert v2 != v1
    assert _status(engine, ctx.execution_id, "intake") == "AWAITING_HUMAN_REVIEW"

    with pytest.raises(AppError) as exc:
        _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v1, "APPROVE")
    assert exc.value.code == "stale_version"

    _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v2, "APPROVE")
    assert _status(engine, ctx.execution_id, "intake") == "APPROVED"


def test_feedback_is_resolved_by_the_revision_that_answers_it(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v1 = _current_version(engine, ctx.execution_id, "intake")
    _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v1, "REQUEST_CHANGES", comment="More detail please")
    with Session(engine) as s:
        wf.run_rework(s, execution_id=ctx.execution_id, stage_key="intake")
    v2 = _current_version(engine, ctx.execution_id, "intake")
    with Session(engine) as s:
        cr = s.execute(select(ChangeRequest)).scalar_one()
        assert cr.status == "resolved" and cr.resulting_artifact_version_id == v2
    with Session(engine) as s:
        stage = s.execute(select(StageExecution).where(StageExecution.stage_key == "intake")
                          .where(StageExecution.workflow_execution_id == ctx.execution_id)).scalar_one()
        revision = s.execute(select(Artifact).where(Artifact.stage_execution_id == stage.id)).scalar_one()
        assert revision is not None
    with Session(engine) as s:
        content = s.execute(text("select content_json from artifact_versions where id = :v"), {"v": str(v2)}).scalar_one()
    assert content["feedback_addressed"] == 1 and content["revision"] == 2


def test_rework_loop_is_bounded(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    for _ in range(wf.MAX_REWORK_LOOPS):
        v = _current_version(engine, ctx.execution_id, "intake")
        _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "REQUEST_CHANGES", comment="again")
        with Session(engine) as s:
            wf.run_rework(s, execution_id=ctx.execution_id, stage_key="intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "REQUEST_CHANGES", comment="one more")
    with Session(engine) as s, pytest.raises(AppError) as exc:
        wf.run_rework(s, execution_id=ctx.execution_id, stage_key="intake")
    assert exc.value.code == "rework_limit_reached"


def test_reject_needs_a_comment_and_then_stops_the_stage(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    with pytest.raises(AppError) as exc:
        _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "REJECT", comment="   ")
    assert exc.value.code == "comment_required"
    _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "REJECT", comment="Wrong project")
    assert _status(engine, ctx.execution_id, "intake") == "REJECTED"


def test_only_members_with_a_policy_role_can_approve(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    reviewer_id = _signed_up(ctx, engine, "approver-reviewer@example.com")
    stranger_id = _signed_up(ctx, engine, "approver-stranger@example.com", add=False)

    with pytest.raises(AppError) as exc:
        _decide(engine, ctx.execution_id, stranger_id, "intake", v, "APPROVE")
    assert exc.value.code == "not_found"

    _add_member(engine, ctx.project_id, reviewer_id, "internal_reviewer")
    with pytest.raises(AppError) as exc:
        _decide(engine, ctx.execution_id, reviewer_id, "intake", v, "APPROVE")
    assert exc.value.code == "approval_not_permitted"  # intake's default policy needs the project owner


def _signed_up(ctx: Ctx, engine, email: str, add: bool = True) -> uuid.UUID:
    with TestClient(ctx.app) as other:
        signup_verify_login(other, engine, email, name=email.split("@")[0])
    return _user_id(engine, email)


def test_author_cannot_approve_their_own_version(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    with Session(engine) as s:
        stage = s.execute(select(StageExecution).where(StageExecution.stage_key == "intake",
                                                       StageExecution.workflow_execution_id == ctx.execution_id)).scalar_one()
        version = artifacts.create_version(s, project_id=ctx.project_id, stage_execution_id=stage.id, kind="intake",
                                           content={"word_count": 3, "note": "edited by owner"},
                                           author_user_id=ctx.owner_id)
        s.commit()
        version_id = version.id
    with pytest.raises(AppError) as exc:
        _decide(engine, ctx.execution_id, ctx.owner_id, "intake", version_id, "APPROVE")
    assert exc.value.code == "separation_of_duties"


def test_same_key_is_idempotent_and_a_second_approval_is_refused(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    key = "idem-key-0001"
    first = _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "APPROVE", idem=key)
    again = _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "APPROVE", idem=key)
    assert first["stage"]["status"] == again["stage"]["status"] == "APPROVED"
    assert _decision_rows(engine, v) == ["APPROVE"]
    with Session(engine) as s, pytest.raises(AppError) as exc:
        approvals.submit_decision(
            s, s.get(User, ctx.owner_id), execution_id=ctx.execution_id, stage_key="intake",
            artifact_version_id=v, decision="REJECT", comment="changed my mind", idempotency_key=key,
        )
    assert exc.value.code == "idempotency_conflict"


def test_approval_rows_and_versions_are_append_only(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "APPROVE")
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("update approval_decisions set comment = 'rewritten'"))
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("update artifact_versions set content_json = '{}'::jsonb"))


def test_decision_must_be_a_real_decision_value(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    with pytest.raises(AppError) as exc:
        _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "MAYBE")
    assert exc.value.code == "invalid_decision"


# --- multi-approver policies -----------------------------------------------------------------------

def _custom_run(ctx: Ctx, engine, template: dict, key: str = "review"):
    version_id = _publish(engine, template)
    with Session(engine) as s:
        execution = wf.start_execution(s, s.get(User, ctx.owner_id), project_id=ctx.project_id,
                                       workflow_version_id=version_id)
        execution_id = execution.id
    _run(engine, execution_id, key)
    return execution_id


def test_all_of_needs_both_roles_and_one_person_cannot_fill_both(ctx, engine):
    reviewer_id = _signed_up(ctx, engine, "joint-reviewer@example.com")
    _add_member(engine, ctx.project_id, reviewer_id, "internal_reviewer")
    execution_id = _custom_run(ctx, engine, JOINT)
    v = _current_version(engine, execution_id, "review")

    _decide(engine, execution_id, ctx.owner_id, "review", v, "APPROVE")
    assert _status(engine, execution_id, "review") == "AWAITING_HUMAN_REVIEW"
    with pytest.raises(AppError) as exc:
        _decide(engine, execution_id, ctx.owner_id, "review", v, "APPROVE")
    assert exc.value.code == "already_approved"

    _decide(engine, execution_id, reviewer_id, "review", v, "APPROVE")
    assert _status(engine, execution_id, "review") == "APPROVED"


def test_sequential_steps_open_in_order(ctx, engine):
    reviewer_id = _signed_up(ctx, engine, "ordered-reviewer@example.com")
    _add_member(engine, ctx.project_id, reviewer_id, "internal_reviewer")
    execution_id = _custom_run(ctx, engine, ORDERED)
    v = _current_version(engine, execution_id, "review")

    with pytest.raises(AppError) as exc:
        _decide(engine, execution_id, ctx.owner_id, "review", v, "APPROVE")
    assert exc.value.code == "approval_not_permitted"  # owner's step waits for the reviewer

    _decide(engine, execution_id, reviewer_id, "review", v, "APPROVE")
    assert _status(engine, execution_id, "review") == "AWAITING_HUMAN_REVIEW"
    _decide(engine, execution_id, ctx.owner_id, "review", v, "APPROVE")
    assert _status(engine, execution_id, "review") == "APPROVED"


def test_concurrent_approvals_produce_exactly_one_approved_transition(ctx, engine):
    reviewer_id = _signed_up(ctx, engine, "race-reviewer@example.com")
    _add_member(engine, ctx.project_id, reviewer_id, "internal_reviewer")
    execution_id = _custom_run(ctx, engine, JOINT)
    v = _current_version(engine, execution_id, "review")

    def approve(user_id: uuid.UUID) -> str:
        try:
            _decide(engine, execution_id, user_id, "review", v, "APPROVE")
            return "ok"
        except AppError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, [ctx.owner_id, reviewer_id]))
    assert results == ["ok", "ok"], results
    assert sorted(_decision_rows(engine, v)) == ["APPROVE", "APPROVE"]
    with Session(engine) as s:
        approved = s.execute(
            select(StageTransition).join(StageExecution, StageExecution.id == StageTransition.stage_execution_id)
            .where(StageExecution.workflow_execution_id == execution_id, StageTransition.to_status == "APPROVED")
        ).scalars().all()
    assert len(approved) == 1


# --- atomicity and invalidation -----------------------------------------------------------------------

def test_failure_after_the_approval_row_rolls_back_everything(ctx, engine, monkeypatch):
    _run(engine, ctx.execution_id, "intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    original = wf.append_event

    def boom(db, **kwargs):
        if kwargs.get("event_type") == "stage.approved":
            raise RuntimeError("injected failure")
        return original(db, **kwargs)

    monkeypatch.setattr(wf, "append_event", boom)
    with pytest.raises(RuntimeError, match="injected"):
        _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "APPROVE")
    monkeypatch.setattr(wf, "append_event", original)

    assert _decision_rows(engine, v) == []
    assert _status(engine, ctx.execution_id, "intake") == "AWAITING_HUMAN_REVIEW"
    assert _status(engine, ctx.execution_id, "outline") == "NOT_STARTED"


def test_upstream_change_invalidates_approved_downstream_work(ctx, engine):
    _run(engine, ctx.execution_id, "intake")
    v = _current_version(engine, ctx.execution_id, "intake")
    _decide(engine, ctx.execution_id, ctx.owner_id, "intake", v, "APPROVE")
    _run(engine, ctx.execution_id, "outline")
    v2 = _current_version(engine, ctx.execution_id, "outline")
    _decide(engine, ctx.execution_id, ctx.owner_id, "outline", v2, "APPROVE")
    assert _status(engine, ctx.execution_id, "outline") == "APPROVED"

    with Session(engine) as s:
        approvals.record_upstream_change(s, execution_id=ctx.execution_id, stage_key="intake",
                                         content={"word_count": 99, "revised": True})
    assert _status(engine, ctx.execution_id, "intake") == "AWAITING_HUMAN_REVIEW"
    assert _status(engine, ctx.execution_id, "outline") == "AWAITING_HUMAN_REVIEW"
    with Session(engine) as s:
        assert s.get(WorkflowExecution, ctx.execution_id).status == "RUNNING"

    # The old approval of the downstream stage no longer counts, even for the same version.
    new_v2 = _current_version(engine, ctx.execution_id, "outline")
    assert new_v2 == v2
    _decide(engine, ctx.execution_id, ctx.owner_id, "outline", v2, "APPROVE")
    assert _status(engine, ctx.execution_id, "outline") == "APPROVED"
