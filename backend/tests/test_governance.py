"""M7 end to end: mandatory sensors, risk acceptance, hooks, rule inheritance and governed learning."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.approvals import service as approvals
from app.approvals.models import ApprovalDecision, ChangeRequest
from app.core.errors import AppError
from app.hooks.models import HookExecution
from app.notifications.models import Notification
from app.rules import service as rules
from app.sensors.models import RiskAcceptance
from app.workflows import service as wf
from app.workflows.work import WORK_FUNCTIONS
from tests.fake_llm import FakeLLM
from tests.helpers import signup_verify_login
from tests.test_agents import BA_LEAD, _start
from tests.test_approvals import _add_member, _publish, _user_id
from tests.test_providers_run import _org_id, _provider, _route

GOOD = {"goal": "Hire faster", "note": "plain text"}


class Env:
    def __init__(self, client, engine, settings, email):
        self.client, self.engine = client, engine
        self.settings = settings.model_copy(update={"provider_backoff_seconds": 0.0})
        self.csrf = signup_verify_login(client, engine, email)
        self.h = {"X-CSRF-Token": self.csrf}
        self.org = _org_id(client)
        self.owner = _user_id(engine, email)

    def flow(self, *sensors, stage="doc", extra=None):
        spec = {"id": stage, "name": stage, "work": "intake_summary", "sensors": list(sensors), **(extra or {})}
        version = _publish(self.engine, {"key": f"g-{uuid.uuid4().hex[:8]}", "name": "g", "stages": [spec]})
        execution, project = _start(self.client, self.engine, version)
        return execution, project

    def run(self, execution, stage="doc", transport=None):
        with Session(self.engine) as s:
            r = wf.run_deterministic_stage(s, execution_id=execution, stage_key=stage, settings=self.settings,
                                           transport=transport)
            return r.status, r.failure_reason

    def rework(self, execution, stage="doc"):
        with Session(self.engine) as s:
            r = wf.run_rework(s, execution_id=execution, stage_key=stage, settings=self.settings)
            return r.status, r.failure_reason

    def view(self, execution, stage="doc", client=None):
        return (client or self.client).get(f"/api/v1/workflow-executions/{execution}/stages/{stage}/review").json()

    def decide(self, execution, decision="APPROVE", stage="doc", comment=""):
        version = self.view(execution, stage)["artifact"]["version_id"]
        return self.client.post(f"/api/v1/workflow-executions/{execution}/stages/{stage}/decisions", headers=self.h,
                                json={"artifact_version_id": version, "decision": decision, "comment": comment,
                                      "idempotency_key": f"k-{uuid.uuid4().hex}"})

    def validate(self, execution, stage="doc"):
        return self.client.post(f"/api/v1/workflow-executions/{execution}/stages/{stage}/validate", headers=self.h)

    def member(self, project, email, role):
        other = TestClient(self.client.app)
        csrf = signup_verify_login(other, self.engine, email, name=role)
        uid = _user_id(self.engine, email)
        _add_member(self.engine, project, uid, role)
        return other, {"X-CSRF-Token": csrf}, uid

    def hook(self, key, **body):
        base = {"event": "stage.started", "phase": "pre", "action": "require_approval",
                "action_config": {"stages": ["nope"]}, "permissions": ["READ"], "failure_policy": "fail_closed"}
        return self.client.put(f"/api/v1/orgs/{self.org}/hooks/{key}", headers=self.h, json={**base, **body})

    def rule(self, key, scope="organization", scope_key="", kind="convention", content="Use plain language."):
        return self.client.post(f"/api/v1/orgs/{self.org}/rules", headers=self.h, json={
            "key": key, "scope_type": scope, "scope_key": scope_key, "kind": kind, "name": key, "content": content})


@pytest.fixture
def env(client, engine, settings, monkeypatch, request):
    monkeypatch.setitem(WORK_FUNCTIONS, "intake_summary", lambda ctx: dict(GOOD))
    return Env(client, engine, settings, f"gov-{uuid.uuid4().hex[:10]}@example.com")


SECTION = {"key": "required_sections", "config": {"sections": ["missing_section"]}}


def _evidence(client, headers, execution, version, kind="unit_tests", outcome="pass", stage="doc"):
    return client.post(f"/api/v1/workflow-executions/{execution}/stages/{stage}/evidence", headers=headers, json={
        "artifact_version_id": version, "kind": kind, "outcome": outcome, "summary": "CI run 41"})


def _version_id(env, execution, stage="doc"):
    with env.engine.connect() as conn:
        return str(conn.execute(text(
            "select a.current_version_id from artifacts a join stage_executions s on s.id = a.stage_execution_id "
            "where s.workflow_execution_id = :e and s.stage_key = :k"), {"e": str(execution), "k": stage}).scalar_one())


# --- mandatory sensors ------------------------------------------------------------------------------

def test_a_failing_mandatory_sensor_blocks_the_gate(env):
    execution, _ = env.flow(SECTION)
    status, reason = env.run(execution)
    assert status == "BLOCKED" and reason == "mandatory sensors not satisfied: required_sections"
    view = env.view(execution)
    assert view["sensors"][0]["status"] == "FAIL" and view["sensors"][0]["blocking"] is True
    assert view["can_decide"] is False
    assert env.decide(execution).json()["code"] == "not_awaiting_review"


def test_an_advisory_failure_is_shown_but_does_not_block(env):
    execution, _ = env.flow({**SECTION, "mandatory": False})
    assert env.run(execution)[0] == "AWAITING_HUMAN_REVIEW"
    assert env.view(execution)["sensors"][0]["status"] == "FAIL"
    assert env.decide(execution).json()["stage"]["status"] == "APPROVED"


def test_rework_answers_blocking_findings_with_a_new_version(env, monkeypatch):
    monkeypatch.setitem(WORK_FUNCTIONS, "intake_summary",
                        lambda ctx: {"missing_section": "added"} if any("missing_section" in f for f in ctx.feedback)
                        else {"other": 1})
    execution, _ = env.flow(SECTION)
    assert env.run(execution)[0] == "BLOCKED"
    assert env.rework(execution)[0] == "AWAITING_HUMAN_REVIEW"
    assert env.view(execution)["artifact"]["version_number"] == 2


def test_a_model_cannot_pass_a_check_by_claiming_it_passed(env, monkeypatch):
    monkeypatch.setitem(WORK_FUNCTIONS, "intake_summary",
                        lambda ctx: {"unit_tests": "PASS", "sensor_results": {"unit_tests": "PASS"}})
    execution, _ = env.flow({"key": "unit_tests"})
    assert env.run(execution)[0] == "BLOCKED"
    assert env.view(execution)["sensors"][0]["status"] == "ERROR"


def test_sensor_results_are_append_only(env):
    execution, _ = env.flow(SECTION)
    env.run(execution)
    with pytest.raises(Exception, match="append-only"), env.engine.begin() as conn:
        conn.execute(text("update sensor_executions set status = 'PASS'"))


def test_findings_in_the_review_view_do_not_expose_a_secret(env, monkeypatch):
    secret = "sk-abcdefghijklmnop1234"
    monkeypatch.setitem(WORK_FUNCTIONS, "intake_summary", lambda ctx: {"note": secret})
    execution, _ = env.flow({"key": "secret_detection"})
    assert env.run(execution)[0] == "BLOCKED"
    assert secret not in json.dumps(env.view(execution)["sensors"])
    with env.engine.connect() as conn:
        assert secret not in conn.execute(text("select findings::text from sensor_executions")).scalar_one()


def test_evidence_comes_from_authorized_people_and_clears_the_gate(env):
    execution, project = env.flow({"key": "unit_tests"})
    assert env.run(execution)[0] == "BLOCKED"
    version = _version_id(env, execution)
    assert _evidence(env.client, env.h, execution, version).status_code == 403  # the owner cannot vouch
    reviewer, h, _ = env.member(project, f"rev-{uuid.uuid4().hex[:8]}@example.com", "internal_reviewer")
    assert _evidence(reviewer, h, execution, version, outcome="fail").status_code == 201
    assert env.validate(execution).json()["status"] == "BLOCKED"
    assert _evidence(reviewer, h, execution, version, outcome="pass").status_code == 201
    assert env.validate(execution).json() == {"status": "AWAITING_HUMAN_REVIEW", "reason": None}
    assert env.decide(execution).json()["stage"]["status"] == "APPROVED"


def test_only_reviewers_record_security_evidence(env):
    execution, project = env.flow({"key": "security_scan"})
    env.run(execution)
    member, h, _ = env.member(project, f"mem-{uuid.uuid4().hex[:8]}@example.com", "team_member")
    assert _evidence(member, h, execution, _version_id(env, execution), kind="security_scan").status_code == 403


def test_a_new_version_needs_validation_before_approval(env):
    execution, _ = env.flow({"key": "required_sections", "config": {"sections": ["goal"]}})
    env.run(execution)
    assert env.decide(execution).json()["stage"]["status"] == "APPROVED"
    with Session(env.engine) as s:
        approvals.record_upstream_change(s, execution_id=execution, stage_key="doc", content={"goal": "changed"})
    refused = env.decide(execution)
    assert refused.status_code == 409 and refused.json()["code"] == "sensor_blocking"
    assert env.validate(execution).json()["status"] == "AWAITING_HUMAN_REVIEW"
    assert env.decide(execution).json()["stage"]["status"] == "APPROVED"


# --- risk acceptance --------------------------------------------------------------------------------

REASON = "Accepted for the pilot; the section is added before launch."


def _accept(env, execution, sensor="required_sections", client=None, headers=None):
    return (client or env.client).post(
        f"/api/v1/workflow-executions/{execution}/stages/doc/risk-acceptances", headers=headers or env.h,
        json={"artifact_version_id": _version_id(env, execution), "sensor": sensor, "reason": REASON,
              "expires_in_days": 7})


def test_an_admin_can_accept_a_risk_only_where_the_stage_allows_it(env):
    closed, _ = env.flow(SECTION)
    env.run(closed)
    assert _accept(env, closed).json()["code"] == "risk_not_acceptable"
    execution, _ = env.flow({**SECTION, "allow_risk_acceptance": True})
    assert env.run(execution)[0] == "BLOCKED"
    assert _accept(env, execution).status_code == 201
    assert env.validate(execution).json()["status"] == "AWAITING_HUMAN_REVIEW"
    assert env.view(execution)["sensors"][0]["risk_accepted"] is True
    decided = env.decide(execution).json()
    assert decided["stage"]["status"] == "APPROVED"
    with Session(env.engine) as s:
        snapshot = s.execute(select(ApprovalDecision.validation_snapshot)).scalar_one()
    assert snapshot["sensors"][0]["risk_accepted"] is True


def test_non_admins_cannot_accept_risk_and_an_expired_acceptance_stops_counting(env):
    execution, project = env.flow({**SECTION, "allow_risk_acceptance": True})
    env.run(execution)
    reviewer, h, _ = env.member(project, f"risk-{uuid.uuid4().hex[:8]}@example.com", "internal_reviewer")
    assert _accept(env, execution, client=reviewer, headers=h).status_code == 404
    with Session(env.engine) as s:
        row = s.execute(text("select id from stage_executions where workflow_execution_id = :e"),
                        {"e": str(execution)}).scalar_one()
        s.add(RiskAcceptance(id=uuid.uuid4(), organization_id=uuid.UUID(env.org), project_id=project,
                             stage_execution_id=row, artifact_version_id=uuid.UUID(_version_id(env, execution)),
                             sensor_key="required_sections", reason=REASON, accepted_by=env.owner,
                             expires_at=datetime.now(UTC) - timedelta(days=1)))
        s.commit()
    assert env.validate(execution).json()["status"] == "BLOCKED"


# --- hooks ------------------------------------------------------------------------------------------

def test_a_mandatory_pre_execution_hook_blocks_the_stage(env):
    assert env.hook("needs-approval").status_code == 201
    execution, _ = env.flow()
    status, reason = env.run(execution)
    assert status == "BLOCKED" and "needs-approval" in reason
    runs = env.client.get(f"/api/v1/orgs/{env.org}/hook-executions").json()["items"]
    assert runs[0]["status"] == "failed" and runs[0]["event"] == "stage.started"


def test_disabling_or_scoping_a_hook_removes_it(env):
    env.hook("off-hook")
    env.client.post(f"/api/v1/orgs/{env.org}/hooks/off-hook/enabled", headers=env.h, json={"enabled": False})
    env.hook("other-stage", conditions={"stages": ["elsewhere"]})
    execution, _ = env.flow()
    assert env.run(execution)[0] == "AWAITING_HUMAN_REVIEW"


def test_an_advisory_hook_failure_is_logged_and_work_continues(env):
    env.hook("soft", failure_policy="advisory", max_retries=2)
    execution, _ = env.flow()
    assert env.run(execution)[0] == "AWAITING_HUMAN_REVIEW"
    run = env.client.get(f"/api/v1/orgs/{env.org}/hook-executions").json()["items"][0]
    assert run["status"] == "failed" and run["attempts"] == 3


def test_a_hook_can_run_a_sensor_after_generation(env):
    env.hook("check-output", event="stage.ai_completed", phase="post", action="run_sensor",
             action_config={"sensor": "required_sections", "config": {"sections": ["absent"]}})
    execution, _ = env.flow()
    status, reason = env.run(execution)
    assert status == "BLOCKED" and "check-output" in reason


def test_a_pre_approval_hook_refuses_the_decision_and_keeps_the_record(env):
    env.hook("release-check", event="stage.approved")
    execution, _ = env.flow()
    assert env.run(execution)[0] == "AWAITING_HUMAN_REVIEW"
    refused = env.decide(execution)
    assert refused.status_code == 409 and refused.json()["code"] == "hook_blocked"
    with Session(env.engine) as s:
        assert s.execute(select(ApprovalDecision)).first() is None
        assert s.execute(select(HookExecution.status)).scalars().all() == ["failed"]
    assert env.view(execution)["stage"]["status"] == "AWAITING_HUMAN_REVIEW"


def test_notify_reaches_only_people_in_the_role(env):
    assert env.hook("tell-owner", event="stage.approval_requested", phase="post", action="notify",
                    permissions=["WRITE"], failure_policy="advisory",
                    action_config={"role": "project_owner", "message": "Ready for your review"}).status_code == 201
    execution, project = env.flow()
    other, _, _ = env.member(project, f"note-{uuid.uuid4().hex[:8]}@example.com", "team_member")
    env.run(execution)
    items = env.client.get("/api/v1/notifications").json()["items"]
    assert [i["message"] for i in items] == ["Ready for your review"]
    assert other.get("/api/v1/notifications").json()["items"] == []
    assert other.post(f"/api/v1/notifications/{items[0]['id']}/read",
                      headers={"X-CSRF-Token": other.get("/api/v1/auth/me").json()["csrf_token"]}).status_code == 404
    with Session(env.engine) as s:
        assert len(s.execute(select(Notification)).scalars().all()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"event": "stage.failed", "phase": "post"},  # cannot be blocked, so cannot be fail_closed
        {"event": "stage.reopened"},  # never emitted
        {"action": "run_shell", "action_config": {"command": "whoami"}},
        {"permissions": ["EXECUTE"]},
        {"action": "run_sensor", "action_config": {"sensor": "nope"}},
        {"timeout_ms": 0},
    ],
)
def test_unsafe_hooks_are_refused(env, body):
    r = env.hook("bad-hook", **body)
    assert r.status_code == 422 and r.json()["code"] == "invalid_hook", r.text


def test_hook_versions_are_immutable_and_admin_only(env):
    env.hook("frozen")
    assert env.hook("frozen", priority=5).json()["version"] == 2
    with pytest.raises(Exception, match="append-only"), env.engine.begin() as conn:
        conn.execute(text("update hook_versions set priority = 1"))
    stranger = TestClient(env.client.app)
    h = {"X-CSRF-Token": signup_verify_login(stranger, env.engine, f"h-{uuid.uuid4().hex[:8]}@example.com")}
    assert stranger.put(f"/api/v1/orgs/{env.org}/hooks/x-hook", headers=h, json={
        "event": "stage.started", "action": "notify", "permissions": ["WRITE"],
        "action_config": {"role": "viewer", "message": "x"}}).status_code == 404


# --- rules ------------------------------------------------------------------------------------------

def _agent_setup(env):
    provider = _provider(env.client, env.csrf, env.org, "fake", "openai_compatible", base_url="http://localhost:11435/v1")
    _route(env.client, env.csrf, env.org, "drafting", provider["id"], "fake-1")
    assert env.client.post(f"/api/v1/orgs/{env.org}/profiles", headers=env.h,
                           json={"key": "business_analyst", "name": "BA"}).status_code == 201
    assert env.client.post(f"/api/v1/orgs/{env.org}/agents", headers=env.h, json=BA_LEAD).status_code == 201


def _agent_flow(env):
    return _start(env.client, env.engine, _publish(env.engine, {
        "key": f"r-{uuid.uuid4().hex[:8]}", "name": "r", "stages": [{
            "id": "ba", "name": "ba", "work": "ai:requirements_draft", "agent": "ba-analyst",
            "profile": "business_analyst", "output_required_keys": ["summary"]}]}))


def test_rules_are_inherited_in_order_and_recorded_on_the_run(env):
    _agent_setup(env)
    env.client.post(f"/api/v1/orgs/{env.org}/teams", headers=env.h, json={"key": "core", "name": "Core"})
    _, project = _agent_flow(env)
    env.client.put(f"/api/v1/orgs/{env.org}/projects/{project}/teams/core", headers=env.h)
    for key, scope, scope_key in [("r-org", "organization", ""), ("r-team", "team", "core"),
                                  ("r-project", "project", str(project)), ("r-profile", "profile", "business_analyst"),
                                  ("r-stage", "stage", "ba"), ("r-agent", "agent", "ba-analyst"),
                                  ("r-other", "stage", "elsewhere")]:
        assert env.rule(key, scope, scope_key, content=f"TEXT {key}").status_code == 201
    version = _publish(env.engine, {"key": f"r2-{uuid.uuid4().hex[:8]}", "name": "r", "stages": [{
        "id": "ba", "name": "ba", "work": "ai:requirements_draft", "agent": "ba-analyst",
        "profile": "business_analyst", "output_required_keys": ["summary"]}]})
    started = env.client.post(f"/api/v1/projects/{project}/workflow-executions", headers=env.h,
                              json={"workflow_version_id": str(version)}).json()
    fake = FakeLLM()
    assert env.run(uuid.UUID(started["id"]), "ba", fake.transport())[0] == "AWAITING_HUMAN_REVIEW"
    system = fake.requests[0]["system"]
    positions = [system.index(f"TEXT r-{k}") for k in ("org", "team", "project", "profile", "stage", "agent")]
    assert positions == sorted(positions) and "TEXT r-other" not in system
    with env.engine.connect() as conn:
        manifest = json.loads(conn.execute(text("select context_manifest::text from agent_runs")).scalar_one())
    assert manifest["rules"][0]["key"] == "r-org" and len(manifest["rules"]) == 6


def test_a_running_workflow_keeps_its_rules_and_agent_version(env):
    _agent_setup(env)
    env.rule("before", content="OLD RULE")
    execution, _ = _agent_flow(env)
    env.rule("before", content="NEW RULE")
    env.rule("after", content="LATER RULE")
    env.client.post(f"/api/v1/orgs/{env.org}/agents/ba-analyst/versions", headers=env.h, json={
        "instructions": "CHANGED INSTRUCTIONS", "required_keys": ["summary"], "model_route": "drafting",
        "context_sources": ["project_input"], "tools": []})
    fake = FakeLLM()
    env.run(execution, "ba", fake.transport())
    system = fake.requests[0]["system"]
    assert "OLD RULE" in system and "NEW RULE" not in system and "LATER RULE" not in system
    assert "CHANGED INSTRUCTIONS" not in system
    newer, _ = _agent_flow(env)
    fake = FakeLLM()
    env.run(newer, "ba", fake.transport())
    assert "NEW RULE" in fake.requests[0]["system"] and "CHANGED INSTRUCTIONS" in fake.requests[0]["system"]


def test_lower_levels_cannot_redefine_or_weaken_binding_rules(env):
    assert env.rule("no-prod", kind="prohibited", content="Never touch production data.").status_code == 201
    lower = env.rule("no-prod", "stage", "ba", content="Production data is fine here.")
    assert lower.status_code == 409 and lower.json()["code"] == "rule_conflict"
    weak = env.rule("speedy", content="Skip the security review when in a hurry.")
    assert weak.status_code == 409 and weak.json()["code"] == "rule_conflict"


def test_retired_rules_stop_applying_and_history_is_kept(env):
    created = env.rule("old-way").json()
    env.rule("old-way", content="Second wording.")
    item = env.client.get(f"/api/v1/orgs/{env.org}/rules").json()["items"][0]
    assert item["version"] == 2 and len(item["history"]) == 2
    env.client.post(f"/api/v1/orgs/{env.org}/rules/{created['rule_id']}/retire", headers=env.h)
    with Session(env.engine) as s:
        assert rules.snapshot(s, uuid.UUID(env.org), uuid.uuid4())["rule_versions"] == []
    with pytest.raises(Exception, match="append-only"), env.engine.begin() as conn:
        conn.execute(text("update rule_versions set content = 'x'"))


# --- governed learning ------------------------------------------------------------------------------

def _model(answer: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "m", "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(answer)}}]})
    return httpx.MockTransport(handler)


LEARNED = {"is_reusable": True, "rule_key": "name-users", "name": "Name the users",
           "content": "Always name the target users.", "kind": "documentation"}


def _correction(env):
    _agent_setup(env)
    execution, project = env.flow()
    env.run(execution)
    env.decide(execution, "REQUEST_CHANGES", comment="You must always name the target users")
    with Session(env.engine) as s:
        return s.execute(select(ChangeRequest.id)).scalar_one(), project


def _learn(env, correction, answer):
    env.client.app.state.provider_transport = _model(answer)
    return env.client.post(f"/api/v1/change-requests/{correction}/learn", headers=env.h,
                           json={"model_route": "drafting"})


def test_a_correction_becomes_a_rule_only_after_a_person_approves_it(env):
    correction, project = _correction(env)
    proposal = _learn(env, correction, LEARNED).json()["proposal"]
    assert proposal["status"] == "pending" and proposal["proposer_type"] == "ai_agent"
    assert proposal["payload"]["scope_key"] == str(project)
    with Session(env.engine) as s:
        assert rules.snapshot(s, uuid.UUID(env.org), project)["rule_versions"] == []
    decided = env.client.post(f"/api/v1/orgs/{env.org}/proposals/{proposal['id']}/decision", headers=env.h,
                              json={"approve": True, "note": "Agreed"}).json()
    assert decided["status"] == "approved"
    item = env.client.get(f"/api/v1/orgs/{env.org}/rules").json()["items"][0]
    assert item["key"] == "name-users" and item["history"][0]["author"] == str(env.owner)
    again = env.client.post(f"/api/v1/orgs/{env.org}/proposals/{proposal['id']}/decision", headers=env.h,
                            json={"approve": True})
    assert again.json()["code"] == "already_decided"


def test_a_correction_that_is_not_reusable_creates_nothing(env):
    correction, _ = _correction(env)
    assert _learn(env, correction, {"is_reusable": False}).json() == {"proposal": None}


def test_a_model_cannot_propose_a_binding_rule(env):
    correction, _ = _correction(env)
    r = _learn(env, correction, {**LEARNED, "kind": "mandatory"})
    assert r.status_code == 502  # output outside the allowed kinds is rejected, then the call fails


def test_a_proposal_that_weakens_controls_cannot_be_approved(env):
    correction, _ = _correction(env)
    proposal = _learn(env, correction, {**LEARNED, "content": "Skip the approval step for small changes."}).json()["proposal"]
    assert proposal["conflicts"]
    r = env.client.post(f"/api/v1/orgs/{env.org}/proposals/{proposal['id']}/decision", headers=env.h,
                        json={"approve": True})
    assert r.status_code == 409 and r.json()["code"] == "proposal_conflict"


def test_an_ai_hook_proposal_has_no_effect_until_approved(env):
    with Session(env.engine) as s:
        proposal = rules.propose_hook(s, uuid.UUID(env.org), proposer_type="ai_agent", proposer=None, key="ai-hook",
                                      definition={"event": "stage.started", "phase": "pre", "failure_policy": "fail_closed",
                                                  "action": "require_approval", "action_config": {"stages": ["nope"]},
                                                  "permissions": ["READ"]})
        s.commit()
        proposal_id = proposal.id
    first, _ = env.flow()
    assert env.run(first)[0] == "AWAITING_HUMAN_REVIEW"
    env.client.post(f"/api/v1/orgs/{env.org}/proposals/{proposal_id}/decision", headers=env.h, json={"approve": True})
    second, _ = env.flow()
    assert env.run(second)[0] == "BLOCKED"


def test_people_cannot_approve_their_own_proposal_and_members_cannot_decide(env):
    body = {"target": "rule", "key": "my-rule", "payload": {"scope_type": "organization", "scope_key": "",
                                                           "kind": "convention", "name": "Mine", "content": "Be brief."}}
    proposal = env.client.post(f"/api/v1/orgs/{env.org}/proposals", headers=env.h, json=body).json()
    r = env.client.post(f"/api/v1/orgs/{env.org}/proposals/{proposal['id']}/decision", headers=env.h,
                        json={"approve": True})
    assert r.status_code == 403 and r.json()["code"] == "separation_of_duties"
    with Session(env.engine) as s, pytest.raises(AppError) as exc:
        rules.decide(s, _stranger(s, env), organization_id=uuid.UUID(env.org),
                     proposal_id=uuid.UUID(proposal["id"]), approve=True, note="")
    assert exc.value.code == "not_found"


@pytest.mark.parametrize(
    "body",
    [
        {"target": "hook", "key": "odd-hook", "payload": {"event": ["x"], "action": {"a": 1}, "priority": "high"}},
        {"target": "rule", "key": "odd-rule", "payload": {"scope_type": "organization", "scope_key": "",
                                                          "kind": "convention", "name": 5, "content": ["x"]}},
    ],
)
def test_malformed_proposals_are_handled_without_a_server_error(env, body):
    r = env.client.post(f"/api/v1/orgs/{env.org}/proposals", headers=env.h, json=body)
    assert r.status_code in (201, 422), r.text
    if r.status_code == 201:
        assert r.json()["conflicts"] == ["the hook definition is malformed"]


def _stranger(session, env):
    other = TestClient(env.client.app)
    email = f"s-{uuid.uuid4().hex[:8]}@example.com"
    signup_verify_login(other, env.engine, email)
    from app.auth.models import User

    return session.get(User, _user_id(env.engine, email))
