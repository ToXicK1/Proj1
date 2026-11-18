"""HTTP surface of the approval engine: what the owner sees, what they can submit, what is hidden."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact
from app.workflows import service as wf
from app.workflows.models import StageExecution
from tests.helpers import signup_verify_login
from tests.test_approvals import _seeded_version, _start

KEY = "api-key-0000001"


def _run_intake(engine, execution_id):
    with Session(engine) as s:
        wf.run_deterministic_stage(s, execution_id=execution_id, stage_key="intake")


def _intake_version(engine, execution_id) -> str:
    with Session(engine) as s:
        stage = s.execute(select(StageExecution).where(StageExecution.workflow_execution_id == execution_id,
                                                       StageExecution.stage_key == "intake")).scalar_one()
        return str(s.execute(select(Artifact.current_version_id).where(Artifact.stage_execution_id == stage.id)).scalar_one())


def test_review_view_shows_the_deliverable_and_policy_but_no_internal_fields(client, engine):
    ctx = _start(client, engine, "api-review@example.com", _seeded_version(engine))
    _run_intake(engine, ctx.execution_id)
    r = client.get(f"/api/v1/workflow-executions/{ctx.execution_id}/stages/intake/review")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"]["status"] == "AWAITING_HUMAN_REVIEW"
    assert body["artifact"]["content"]["project_name"] == "Hiring hub"
    assert body["artifact"]["version_number"] == 1
    assert body["can_decide"] is True
    assert body["policy"]["slots"][0]["roles"] == ["project_owner"]
    text = str(body)
    for hidden in ("validation_snapshot", "idempotency_key", "approver_user_id", "password", "prompt", "provider"):
        assert hidden not in text, hidden


def test_owner_submits_an_approval_over_http(client, engine):
    ctx = _start(client, engine, "api-approve@example.com", _seeded_version(engine))
    _run_intake(engine, ctx.execution_id)
    version = _intake_version(engine, ctx.execution_id)
    url = f"/api/v1/workflow-executions/{ctx.execution_id}/stages/intake/decisions"
    body = {"artifact_version_id": version, "decision": "APPROVE", "idempotency_key": KEY}

    assert client.post(url, json=body).status_code == 403  # no CSRF token
    r = client.post(url, json=body, headers={"X-CSRF-Token": ctx.owner_csrf})
    assert r.status_code == 200, r.text
    assert r.json()["stage"]["status"] == "APPROVED"
    assert r.json()["can_decide"] is False
    workflow = client.get(f"/api/v1/workflow-executions/{ctx.execution_id}").json()
    assert [s["status"] for s in workflow["stages"]] == ["APPROVED", "READY"]


def test_decision_body_is_strict(client, engine):
    ctx = _start(client, engine, "api-strict@example.com", _seeded_version(engine))
    _run_intake(engine, ctx.execution_id)
    version = _intake_version(engine, ctx.execution_id)
    url = f"/api/v1/workflow-executions/{ctx.execution_id}/stages/intake/decisions"
    headers = {"X-CSRF-Token": ctx.owner_csrf}
    # A client cannot set the status or the actor.
    r = client.post(url, json={"artifact_version_id": version, "decision": "APPROVE", "idempotency_key": KEY,
                               "status": "APPROVED"}, headers=headers)
    assert r.status_code == 422
    r = client.post(url, json={"artifact_version_id": version, "decision": "APPROVE", "idempotency_key": KEY,
                               "approver_user_id": str(uuid.uuid4())}, headers=headers)
    assert r.status_code == 422
    r = client.post(url, json={"artifact_version_id": version, "decision": "APPROVE", "idempotency_key": "short"},
                    headers=headers)
    assert r.status_code == 422
    r = client.post(url, json={"artifact_version_id": version, "decision": "PUBLISH", "idempotency_key": KEY},
                    headers=headers)
    assert r.status_code == 422


def test_non_members_cannot_see_or_decide(client, engine):
    ctx = _start(client, engine, "api-private@example.com", _seeded_version(engine))
    _run_intake(engine, ctx.execution_id)
    version = _intake_version(engine, ctx.execution_id)
    with TestClient(client.app) as stranger:
        csrf = signup_verify_login(stranger, engine, "api-stranger@example.com", name="Stranger")
        view = stranger.get(f"/api/v1/workflow-executions/{ctx.execution_id}/stages/intake/review")
        missing = stranger.get(f"/api/v1/workflow-executions/{uuid.uuid4()}/stages/intake/review")
        assert view.status_code == missing.status_code == 404
        assert view.json()["title"] == missing.json()["title"]
        r = stranger.post(f"/api/v1/workflow-executions/{ctx.execution_id}/stages/intake/decisions",
                          json={"artifact_version_id": version, "decision": "APPROVE", "idempotency_key": KEY},
                          headers={"X-CSRF-Token": csrf})
        assert r.status_code == 404


def test_request_changes_then_revision_is_visible_with_feedback(client, engine):
    ctx = _start(client, engine, "api-changes@example.com", _seeded_version(engine))
    _run_intake(engine, ctx.execution_id)
    version = _intake_version(engine, ctx.execution_id)
    url = f"/api/v1/workflow-executions/{ctx.execution_id}/stages/intake/decisions"
    r = client.post(url, json={"artifact_version_id": version, "decision": "REQUEST_CHANGES",
                               "comment": "Name the target users", "idempotency_key": KEY},
                    headers={"X-CSRF-Token": ctx.owner_csrf})
    assert r.status_code == 200, r.text
    review = r.json()
    assert review["stage"]["status"] == "CHANGES_REQUESTED"
    assert review["change_requests"][0]["comment"] == "Name the target users"
    assert review["change_requests"][0]["status"] == "open"
    assert review["decisions"][0]["approver"] == "Test User"
