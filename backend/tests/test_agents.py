"""Agents and profiles: admin rules, versioning, lineage, context scope, handoffs and independent profiles."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agents.models import ReviewRecord
from app.workflows import service as wf
from app.workflows.compiler import CompileError
from app.workflows.models import StageExecution
from tests.fake_llm import FakeLLM
from tests.helpers import signup_verify_login
from tests.test_approvals import _publish
from tests.test_providers_run import _org_id, _provider, _route

BA_LEAD = {
    "profile": "business_analyst", "key": "ba-analyst", "kind": "lead",
    "instructions": "You are a business analyst. Draft requirements from the project input.",
    "required_keys": ["summary", "assumptions", "open_questions"], "model_route": "drafting",
    "context_sources": ["project_input", "feedback"], "tools": ["read_project"],
}
BA_REVIEWER = {
    "profile": "business_analyst", "key": "ba-critic", "kind": "reviewer",
    "instructions": "You review requirements critically and independently.",
    "required_keys": ["verdict", "findings"], "model_route": "drafting",
    "context_sources": ["stage_artifact"], "tools": [],
}
ARCH_LEAD = {
    "profile": "solution_architect", "key": "arch-designer", "kind": "lead",
    "instructions": "You are a solution architect. Propose components for the project.",
    "required_keys": ["summary", "components"], "model_route": "drafting",
    "context_sources": ["project_input"], "tools": [],
}
ARCH_REVIEWER = {
    "profile": "solution_architect", "key": "arch-critic", "kind": "reviewer",
    "instructions": "You review architecture critically.",
    "required_keys": ["verdict", "findings"], "model_route": "drafting",
    "context_sources": ["stage_artifact"], "tools": [],
}
DESCRIPTION = "Recruiting platform for remote teams with candidate scoring"


def _setup(client, engine, email: str):
    csrf = signup_verify_login(client, engine, email)
    org_id = _org_id(client)
    provider = _provider(client, csrf, org_id, "fake-llm", "openai_compatible", base_url="http://localhost:11434/v1")
    _route(client, csrf, org_id, "drafting", provider["id"], "fake-1")
    h = {"X-CSRF-Token": csrf}
    for key, name in [("business_analyst", "Business Analyst"), ("solution_architect", "Solution Architect")]:
        assert client.post(f"/api/v1/orgs/{org_id}/profiles", json={"key": key, "name": name}, headers=h).status_code == 201
    for agent in (BA_LEAD, BA_REVIEWER, ARCH_LEAD, ARCH_REVIEWER):
        r = client.post(f"/api/v1/orgs/{org_id}/agents", json=agent, headers=h)
        assert r.status_code == 201, r.text
    return csrf, org_id


def _stage(key: str, work: str, agent: str, reviewer: str, profile: str, required: list[str]) -> dict:
    return {"id": key, "name": key, "depends_on": [], "work": work, "agent": agent, "reviewer": reviewer,
            "profile": profile, "output_required_keys": required}


def _start(client, engine, version_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]
    org_id = _org_id(client)
    project = client.post(f"/api/v1/orgs/{org_id}/projects",
                          json={"name": "Hiring hub", "description": DESCRIPTION, "project_type": "SaaS Platform"},
                          headers={"X-CSRF-Token": csrf}).json()
    execution = client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                            json={"workflow_version_id": str(version_id)}, headers={"X-CSRF-Token": csrf}).json()
    return uuid.UUID(execution["id"]), uuid.UUID(project["id"])


def _run(engine, settings, fake: FakeLLM, execution_id: uuid.UUID, key: str):
    with Session(engine) as s:
        stage = wf.run_deterministic_stage(s, execution_id=execution_id, stage_key=key,
                                           settings=settings.model_copy(update={"provider_backoff_seconds": 0.0}),
                                           transport=fake.transport())
        return stage.status, stage.failure_reason


def _status(engine, execution_id: uuid.UUID, key: str) -> str:
    with Session(engine) as s:
        return s.execute(select(StageExecution.status).where(
            StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == key)).scalar_one()


def _runs(engine, execution_id: uuid.UUID) -> list[tuple[str, str, str | None]]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "select r.kind, r.status, cast(r.agent_version_id as text), r.context_manifest::text "
            "from agent_runs r join stage_executions s on s.id = r.stage_execution_id "
            "where s.workflow_execution_id = :e order by r.kind"), {"e": str(execution_id)}).all()
    return [(r[0], r[1], r[2]) for r in rows]


# --- admin rules ----------------------------------------------------------------------------------

def test_admin_creates_profiles_and_versioned_agents(client, engine):
    csrf, org_id = _setup(client, engine, "agents-admin@example.com")
    listed = client.get(f"/api/v1/orgs/{org_id}/agents").json()["items"]
    assert {a["key"] for a in listed} == {"ba-analyst", "ba-critic", "arch-designer", "arch-critic"}
    r = client.post(f"/api/v1/orgs/{org_id}/agents/ba-analyst/versions", json={
        "instructions": "Be sharper about acceptance criteria.", "required_keys": ["summary", "open_questions"],
        "model_route": "drafting", "context_sources": ["project_input", "feedback"], "tools": ["read_project"],
    }, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201 and r.json()["version"] == 2
    ba = next(a for a in client.get(f"/api/v1/orgs/{org_id}/agents").json()["items"] if a["key"] == "ba-analyst")
    assert ba["version"] == 2


def test_only_org_admins_manage_agents(client, engine):
    _setup(client, engine, "agents-rbac@example.com")
    org_id = _org_id(client)
    with TestClient(client.app) as stranger:
        stranger_csrf = signup_verify_login(stranger, engine, "agents-stranger@example.com", name="Stranger")
        r = stranger.post(f"/api/v1/orgs/{org_id}/profiles", json={"key": "qa", "name": "QA"},
                          headers={"X-CSRF-Token": stranger_csrf})
        assert r.status_code == 404
        assert stranger.get(f"/api/v1/orgs/{org_id}/agents").status_code == 404


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"context_sources": ["stage_artifact"]}, "invalid_context"),  # a lead may not read a reviewer's artifact
        ({"tools": ["publish_release"]}, "invalid_tools"),  # external side effects are not grantable here
        ({"tools": ["edit_rules"]}, "invalid_tools"),  # administrative tools are never granted to agents
        ({"tools": ["made_up_tool"]}, "invalid_tools"),
        ({"required_keys": ["Bad Key"]}, "invalid_keys"),
        ({"required_keys": ["a", "a"]}, "invalid_keys"),
        ({"instructions": "   "}, "invalid_instructions"),
    ],
)
def test_unsafe_agent_definitions_are_refused(client, engine, change, code):
    csrf, org_id = _setup(client, engine, f"agents-bad-{code}@example.com")
    body = {**BA_LEAD, "key": f"bad-{uuid.uuid4().hex[:6]}", **change}
    r = client.post(f"/api/v1/orgs/{org_id}/agents", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == code


def test_reviewer_cannot_read_project_input_and_profiles_must_exist(client, engine):
    csrf, org_id = _setup(client, engine, "agents-scope@example.com")
    h = {"X-CSRF-Token": csrf}
    bad = {**BA_REVIEWER, "key": "rev-scope", "context_sources": ["project_input"]}
    assert client.post(f"/api/v1/orgs/{org_id}/agents", json=bad, headers=h).json()["code"] == "invalid_context"
    orphan = {**BA_LEAD, "key": "orphan", "profile": "no_such_profile"}
    assert client.post(f"/api/v1/orgs/{org_id}/agents", json=orphan, headers=h).status_code == 404


def test_agent_versions_are_immutable(client, engine):
    _setup(client, engine, "agents-immutable@example.com")
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("update agent_config_versions set instructions = 'changed'"))


# --- independence and compile-time rules ---------------------------------------------------------

def test_a_stage_cannot_name_the_same_agent_as_reviewer(client, engine):
    _setup(client, engine, "agents-same@example.com")
    raw = {"key": f"same-{uuid.uuid4().hex[:6]}", "name": "same", "stages": [
        _stage("s", "ai:requirements_draft", "ba-analyst", "ba-analyst", "business_analyst", ["summary"])]}
    with Session(engine) as s, pytest.raises(CompileError) as exc:
        wf.publish_version(s, raw)
    assert any("must not be the lead agent" in p for p in exc.value.problems)


def test_a_clone_of_the_lead_is_refused_as_reviewer_at_run_time(client, engine, settings):
    csrf, org_id = _setup(client, engine, "agents-clone@example.com")
    clone = {**BA_REVIEWER, "key": "ba-clone", "clone_of": "ba-analyst"}
    assert client.post(f"/api/v1/orgs/{org_id}/agents", json=clone, headers={"X-CSRF-Token": csrf}).status_code == 201
    version = _publish(engine, {"key": f"clone-{uuid.uuid4().hex[:6]}", "name": "clone", "stages": [
        _stage("ba", "ai:requirements_draft", "ba-analyst", "ba-clone", "business_analyst", ["summary"])]})
    execution_id, _ = _start(client, engine, version)
    status, reason = _run(engine, settings, FakeLLM(), execution_id, "ba")
    assert status == "FAILED"
    assert reason == "review refused: reviewer shares a lineage with the lead agent"


# --- what each agent may see ----------------------------------------------------------------------

def test_reviewer_sees_only_the_artifact_and_lead_sees_only_its_sources(client, engine, settings):
    csrf, org_id = _setup(client, engine, "agents-scope-run@example.com")
    # A lead that may read only feedback: the project description must not reach it.
    client.post(f"/api/v1/orgs/{org_id}/agents", headers={"X-CSRF-Token": csrf}, json={
        **BA_LEAD, "key": "ba-feedback-only", "context_sources": ["feedback"], "tools": []})
    client.post(f"/api/v1/orgs/{org_id}/agents", headers={"X-CSRF-Token": csrf}, json={
        **BA_REVIEWER, "key": "ba-critic-2"})
    version = _publish(engine, {"key": f"scope-{uuid.uuid4().hex[:6]}", "name": "scope", "stages": [
        _stage("ba", "ai:requirements_draft", "ba-feedback-only", "ba-critic-2", "business_analyst", ["summary"])]})
    execution_id, _ = _start(client, engine, version)
    fake = FakeLLM()
    assert _run(engine, settings, fake, execution_id, "ba")[0] == "AWAITING_HUMAN_REVIEW"

    lead = fake.lead_requests()[0]["user"]
    review = fake.review_requests()[0]["user"]
    assert DESCRIPTION not in lead and "<project_input>" in lead
    assert DESCRIPTION not in review and "Hiring hub" not in review
    assert review.startswith("<stage_artifact>") and "summary written from the input" in review


def test_handoff_links_the_lead_run_to_the_review(client, engine, settings):
    _setup(client, engine, "agents-handoff@example.com")
    version = _publish(engine, {"key": f"handoff-{uuid.uuid4().hex[:6]}", "name": "handoff", "stages": [
        _stage("ba", "ai:requirements_draft", "ba-analyst", "ba-critic", "business_analyst", ["summary"])]})
    execution_id, _ = _start(client, engine, version)
    fake = FakeLLM(reviewer_verdict="changes_recommended", reviewer_findings=["Name the target users"])
    status, _ = _run(engine, settings, fake, execution_id, "ba")
    assert status == "AWAITING_HUMAN_REVIEW"  # advisory: the verdict informs the human, it does not block
    with Session(engine) as s:
        rec = s.execute(select(ReviewRecord)).scalar_one()
        lead_run = s.execute(text("select id::text from agent_runs where kind = 'lead'")).scalar_one()
    assert rec.verdict == "changes_recommended" and rec.findings == ["Name the target users"]
    assert rec.handoff["from_run_id"] == lead_run and rec.handoff["to_agent"] == "ba-critic"
    assert rec.handoff["open_questions"] == ["Name the target users"]


def test_an_agent_from_another_profile_is_refused(client, engine, settings):
    _setup(client, engine, "agents-profile@example.com")
    version = _publish(engine, {"key": f"mismatch-{uuid.uuid4().hex[:6]}", "name": "mismatch", "stages": [
        _stage("ba", "ai:requirements_draft", "ba-analyst", "ba-critic", "solution_architect", ["summary"])]})
    execution_id, _ = _start(client, engine, version)
    status, reason = _run(engine, settings, FakeLLM(), execution_id, "ba")
    assert status == "FAILED" and reason == "agent refused: agent belongs to a different profile than this stage"


def test_review_verdict_reaches_the_owner_review_view(client, engine, settings):
    _setup(client, engine, "agents-view@example.com")
    version = _publish(engine, {"key": f"view-{uuid.uuid4().hex[:6]}", "name": "view", "stages": [
        _stage("ba", "ai:requirements_draft", "ba-analyst", "ba-critic", "business_analyst", ["summary"])]})
    execution_id, _ = _start(client, engine, version)
    _run(engine, settings, FakeLLM(reviewer_verdict="pass"), execution_id, "ba")
    view = client.get(f"/api/v1/workflow-executions/{execution_id}/stages/ba/review").json()
    assert view["reviews"][0]["verdict"] == "pass" and view["reviews"][0]["findings"] == []


# --- the exit criterion: profiles execute independently --------------------------------------------

def test_two_professional_profiles_execute_independently(client, engine, settings):
    _setup(client, engine, "agents-two@example.com")
    version = _publish(engine, {"key": f"two-{uuid.uuid4().hex[:6]}", "name": "two profiles", "stages": [
        _stage("ba_intake", "ai:requirements_draft", "ba-analyst", "ba-critic", "business_analyst", ["summary"]),
        _stage("arch_design", "ai:requirements_draft", "arch-designer", "arch-critic", "solution_architect",
               ["components"]),
    ]})
    execution_id, _ = _start(client, engine, version)
    fake = FakeLLM()
    assert _run(engine, settings, fake, execution_id, "ba_intake")[0] == "AWAITING_HUMAN_REVIEW"
    assert _run(engine, settings, fake, execution_id, "arch_design")[0] == "AWAITING_HUMAN_REVIEW"

    with engine.connect() as conn:
        pairs = conn.execute(text(
            "select s.stage_key, a.key, r.kind from agent_runs r join agent_config_versions v on v.id = r.agent_version_id "
            "join agent_configurations a on a.id = v.agent_id join stage_executions s on s.id = r.stage_execution_id "
            "where s.workflow_execution_id = :e order by s.stage_key, r.kind"), {"e": str(execution_id)}).all()
        profiles = conn.execute(text(
            "select a.key, p.key from agent_configurations a join profiles p on p.id = a.profile_id")).all()
    by_stage: dict[str, set[str]] = {}
    for stage_key, agent_key, _ in pairs:
        by_stage.setdefault(stage_key, set()).add(agent_key)
    assert by_stage == {"ba_intake": {"ba-analyst", "ba-critic"}, "arch_design": {"arch-designer", "arch-critic"}}
    profile_of = dict(profiles)
    assert profile_of["ba-analyst"] == profile_of["ba-critic"] == "business_analyst"
    assert profile_of["arch-designer"] == profile_of["arch-critic"] == "solution_architect"

    # Each profile's prompts carry only its own stage's material.
    arch_lead = next(r for r in fake.lead_requests() if "architect" in r["system"])
    assert "business analyst" not in arch_lead["system"].lower()
    assert "ba-analyst" not in arch_lead["user"]
    with Session(engine) as s:
        reviews = s.execute(select(ReviewRecord)).scalars().all()
    assert len(reviews) == 2 and {r.handoff["to_agent"] for r in reviews} == {"ba-critic", "arch-critic"}
