"""Engine behaviour against a real database: transitions, readiness, locking, audit and the API."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import org_chain, verify_chain
from app.auth.models import User
from app.core.errors import AppError
from app.workflows import service
from app.workflows.models import StageExecution, StageTransition, WorkflowExecution
from app.workflows.seed import seed_templates
from app.workflows.state_machine import ActorType, StageStatus
from app.workflows.work import WORK_FUNCTIONS
from tests.helpers import signup_verify_login

S = StageStatus


def _seeded_version(engine) -> uuid.UUID:
    with Session(engine) as s:
        seed_templates(s)
        from app.workflows.models import WorkflowDefinition, WorkflowVersion

        definition = s.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.key == "discovery-foundation")
        ).scalar_one()
        version = s.execute(
            select(WorkflowVersion).where(WorkflowVersion.definition_id == definition.id)
        ).scalar_one()
        return version.id


def _owner_and_project(client, engine, email: str):
    csrf = signup_verify_login(client, engine, email)
    org_id = client.get("/api/v1/orgs").json()["items"][0]["id"]
    project = client.post(
        f"/api/v1/orgs/{org_id}/projects",
        json={"name": "Recruitment platform", "description": "Candidates and job descriptions for matching",
              "project_type": "SaaS Platform"},
        headers={"X-CSRF-Token": csrf},
    ).json()
    return csrf, project


def _stage_status(engine, execution_id: str, key: str) -> str:
    with Session(engine) as s:
        return s.execute(
            select(StageExecution.status).join(WorkflowExecution, WorkflowExecution.id == StageExecution.workflow_execution_id)
            .where(WorkflowExecution.id == uuid.UUID(execution_id), StageExecution.stage_key == key)
        ).scalar_one()


def test_start_creates_stages_with_roots_ready(client, engine):
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-start@example.com")
    r = client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                    json={"workflow_version_id": str(version_id)}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201, r.text
    body = r.json()
    assert [s["status"] for s in body["stages"]] == ["READY", "NOT_STARTED"]
    assert body["workflow"]["key"] == "discovery-foundation"


def test_deterministic_run_stops_at_human_review_and_downstream_waits(engine, client):
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-run@example.com")
    execution_id = client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                               json={"workflow_version_id": str(version_id)},
                               headers={"X-CSRF-Token": csrf}).json()["id"]
    with Session(engine) as s:
        owner = s.execute(select(User).where(User.email == "wf-run@example.com")).scalar_one()
        assert owner is not None
        service.run_deterministic_stage(s, execution_id=uuid.UUID(execution_id), stage_key="intake")

    assert _stage_status(engine, execution_id, "intake") == "AWAITING_HUMAN_REVIEW"
    # The downstream stage needs an APPROVED upstream, which needs the approval engine (Milestone 4).
    assert _stage_status(engine, execution_id, "outline") == "NOT_STARTED"

    with Session(engine) as s:
        rows = s.execute(
            select(StageTransition.from_status, StageTransition.to_status, StageTransition.actor_type)
            .join(StageExecution, StageExecution.id == StageTransition.stage_execution_id)
            .where(StageExecution.stage_key == "intake")
            .order_by(StageTransition.id)
        ).all()
    assert [r[1] for r in rows] == ["RUNNING", "AI_COMPLETED", "VALIDATING", "AWAITING_HUMAN_REVIEW"]
    assert {r[2] for r in rows} == {"system"}


def test_every_transition_is_in_the_tamper_evident_audit(engine, client):
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-audit@example.com")
    execution_id = client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                               json={"workflow_version_id": str(version_id)},
                               headers={"X-CSRF-Token": csrf}).json()["id"]
    with Session(engine) as s:
        service.run_deterministic_stage(s, execution_id=uuid.UUID(execution_id), stage_key="intake")
    with Session(engine) as s:
        assert verify_chain(s, org_chain(uuid.UUID(project["organization_id"]))) == []
    with engine.connect() as conn:
        from sqlalchemy import text

        types = {r[0] for r in conn.execute(text("select event_type from audit_events where project_id = :p"),
                                            {"p": project["id"]})}
    assert {"workflow.started", "stage.running", "stage.ai_completed", "stage.awaiting_human_review"} <= types


def test_illegal_and_ai_driven_transitions_are_refused(engine, client):
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-illegal@example.com")
    execution_id = uuid.UUID(client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                                         json={"workflow_version_id": str(version_id)},
                                         headers={"X-CSRF-Token": csrf}).json()["id"])
    with Session(engine) as s:
        with pytest.raises(AppError) as exc:
            service.transition_stage(s, execution_id=execution_id, stage_key="intake",
                                     to_status=S.AWAITING_HUMAN_REVIEW, actor=ActorType.SYSTEM)
        assert exc.value.code == "invalid_transition"
    with Session(engine) as s:
        with pytest.raises(AppError) as exc:
            service.transition_stage(s, execution_id=execution_id, stage_key="intake",
                                     to_status=S.RUNNING, actor=ActorType.AI_AGENT, actor_id="agent-1")
        assert exc.value.code == "invalid_transition"
    with Session(engine) as s:
        with pytest.raises(AppError) as exc:
            service.transition_stage(s, execution_id=execution_id, stage_key="intake",
                                     to_status=S.APPROVED, actor=ActorType.HUMAN)
        assert exc.value.code == "invalid_transition"  # READY -> APPROVED is not an edge
    assert _stage_status(engine, str(execution_id), "intake") == "READY"

    with Session(engine) as s:
        service.run_deterministic_stage(s, execution_id=execution_id, stage_key="intake")
    with Session(engine) as s:
        with pytest.raises(AppError) as exc:
            service.transition_stage(s, execution_id=execution_id, stage_key="intake",
                                     to_status=S.APPROVED, actor=ActorType.HUMAN)
        # The edge exists for humans, but the approval engine (Milestone 4) must do the approving.
        assert exc.value.code == "approval_required"
    assert _stage_status(engine, str(execution_id), "intake") == "AWAITING_HUMAN_REVIEW"


def test_stale_expected_version_is_a_conflict(engine, client):
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-version@example.com")
    execution_id = uuid.UUID(client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                                         json={"workflow_version_id": str(version_id)},
                                         headers={"X-CSRF-Token": csrf}).json()["id"])
    with Session(engine) as s:
        with pytest.raises(AppError) as exc:
            service.transition_stage(s, execution_id=execution_id, stage_key="intake",
                                     to_status=S.RUNNING, actor=ActorType.SYSTEM, expected_version=99)
        assert exc.value.code == "version_conflict"


def test_concurrent_transitions_on_one_stage_have_exactly_one_winner(engine, client):
    """Two workers try to start the same stage at once: the row lock lets exactly one through."""
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-race@example.com")
    execution_id = uuid.UUID(client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                                         json={"workflow_version_id": str(version_id)},
                                         headers={"X-CSRF-Token": csrf}).json()["id"])

    def attempt(_: int) -> str:
        with Session(engine) as s:
            try:
                service.transition_stage(s, execution_id=execution_id, stage_key="intake",
                                         to_status=S.RUNNING, actor=ActorType.SYSTEM)
                return "won"
            except AppError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count("won") == 1, results
    assert set(results) - {"won"} == {"invalid_transition"}, results
    with Session(engine) as s:
        running = s.execute(
            select(StageTransition).join(StageExecution, StageExecution.id == StageTransition.stage_execution_id)
            .where(StageExecution.stage_key == "intake", StageTransition.to_status == "RUNNING")
        ).scalars().all()
    assert len(running) == 1


def test_missing_required_output_blocks_the_stage(engine, client, monkeypatch):
    monkeypatch.setitem(WORK_FUNCTIONS, "intake_summary", lambda ctx: {"something_else": True})
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-block@example.com")
    execution_id = uuid.UUID(client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                                         json={"workflow_version_id": str(version_id)},
                                         headers={"X-CSRF-Token": csrf}).json()["id"])
    with Session(engine) as s:
        stage = service.run_deterministic_stage(s, execution_id=execution_id, stage_key="intake")
        assert stage.status == "BLOCKED"


def test_work_exception_fails_the_stage_and_says_why(engine, client, monkeypatch):
    def boom(ctx):
        raise RuntimeError("disk on fire")

    monkeypatch.setitem(WORK_FUNCTIONS, "intake_summary", boom)
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-fail@example.com")
    execution_id = uuid.UUID(client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                                         json={"workflow_version_id": str(version_id)},
                                         headers={"X-CSRF-Token": csrf}).json()["id"])
    with Session(engine) as s:
        stage = service.run_deterministic_stage(s, execution_id=execution_id, stage_key="intake")
        assert stage.status == "FAILED"
        assert stage.failure_reason == "work failed: RuntimeError"


def test_only_project_owner_can_start_and_non_members_see_not_found(client, engine):
    from fastapi.testclient import TestClient as TC

    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-owner@example.com")
    with TC(client.app) as stranger:
        stranger_csrf = signup_verify_login(stranger, engine, "wf-stranger@example.com", name="Stranger")
        start = stranger.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                              json={"workflow_version_id": str(version_id)},
                              headers={"X-CSRF-Token": stranger_csrf})
        assert start.status_code == 404
    unknown = client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                          json={"workflow_version_id": str(uuid.uuid4())}, headers={"X-CSRF-Token": csrf})
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "unknown_workflow_version"


def test_start_requires_csrf_and_rejects_status_in_body(client, engine):
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-csrf@example.com")
    url = f"/api/v1/projects/{project['id']}/workflow-executions"
    assert client.post(url, json={"workflow_version_id": str(version_id)}).status_code == 403
    bad = client.post(url, json={"workflow_version_id": str(version_id), "status": "APPROVED"},
                      headers={"X-CSRF-Token": csrf})
    assert bad.status_code == 422


def test_read_view_hides_outputs_and_internal_fields(engine, client):
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-view@example.com")
    execution_id = client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                               json={"workflow_version_id": str(version_id)},
                               headers={"X-CSRF-Token": csrf}).json()["id"]
    with Session(engine) as s:
        service.run_deterministic_stage(s, execution_id=uuid.UUID(execution_id), stage_key="intake")
    view = client.get(f"/api/v1/workflow-executions/{execution_id}").json()
    assert "output_json" not in str(view)
    assert set(view["stages"][0]) == {"key", "name", "status", "version"}


def test_other_users_cannot_read_an_execution(engine, client):
    version_id = _seeded_version(engine)
    csrf, project = _owner_and_project(client, engine, "wf-read-owner@example.com")
    execution_id = client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                               json={"workflow_version_id": str(version_id)},
                               headers={"X-CSRF-Token": csrf}).json()["id"]
    with TestClient(client.app) as other:
        signup_verify_login(other, engine, "wf-read-other@example.com", name="Other")
        missing = other.get(f"/api/v1/workflow-executions/{uuid.uuid4()}")
        forbidden = other.get(f"/api/v1/workflow-executions/{execution_id}")
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json()["title"] == missing.json()["title"]
