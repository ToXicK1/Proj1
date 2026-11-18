"""Skill dependencies, stage limits, and the role checks on lead and reviewer agents."""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.workflows import service as wf
from tests.fake_llm import FakeLLM
from tests.test_agents import _start
from tests.test_approvals import _publish
from tests.test_skills import _agent, _base, _outage_then_fake, _skill


def _version(client, org_id, csrf, key, **kw):
    body = {"instructions": "Updated.", "required_tools": [], "compatible_profiles": [], **kw}
    return client.post(f"/api/v1/orgs/{org_id}/skills/{key}/versions", json=body, headers={"X-CSRF-Token": csrf})


def _pins(engine, agent_key: str) -> list[dict]:
    with Session(engine) as s:
        raw = s.execute(text(
            "select v.skills::text from agent_config_versions v join agent_configurations a on a.id = v.agent_id "
            "where a.key = :k order by v.version desc limit 1"), {"k": agent_key}).scalar_one()
    return json.loads(raw)


def _run(client, engine, settings, agent: str, stage: str = "ba", reviewer: str | None = None):
    spec = {"id": stage, "name": stage, "depends_on": [], "work": "ai:requirements_draft", "agent": agent,
            "profile": "business_analyst", "output_required_keys": ["summary"]}
    if reviewer:
        spec["reviewer"] = reviewer
    version = _publish(engine, {"key": f"dep-{uuid.uuid4().hex[:8]}", "name": "dep", "stages": [spec]})
    execution_id, _ = _start(client, engine, version)
    fake = FakeLLM()
    with Session(engine) as s:
        result = wf.run_deterministic_stage(
            s, execution_id=execution_id, stage_key=stage,
            settings=settings.model_copy(update={"provider_backoff_seconds": 0.0}),
            transport=_outage_then_fake(fake),
        )
        return result.status, result.failure_reason, fake


def test_dependencies_are_pinned_first_and_reach_the_prompt_in_order(client, engine, settings):
    csrf, org_id = _base(client, engine, "dep-order@example.com")
    _skill(client, org_id, csrf, key="base-style", instructions="BASE TEXT")
    _skill(client, org_id, csrf, key="middle", instructions="MIDDLE TEXT", dependencies=["base-style"])
    _skill(client, org_id, csrf, key="top", instructions="TOP TEXT", dependencies=["middle"])
    assert _agent(client, org_id, csrf, key="dep-agent", skills=["top"])["status"] == 201
    assert _pins(engine, "dep-agent") == [
        {"key": "base-style", "version": 1}, {"key": "middle", "version": 1}, {"key": "top", "version": 1},
    ]
    status, reason, fake = _run(client, engine, settings, "dep-agent")
    assert status == "AWAITING_HUMAN_REVIEW", reason
    system = fake.lead_requests()[0]["system"]
    assert system.index("BASE TEXT") < system.index("MIDDLE TEXT") < system.index("TOP TEXT")


def test_a_dependency_stays_at_the_version_it_was_pinned_to(client, engine):
    csrf, org_id = _base(client, engine, "dep-pin@example.com")
    _skill(client, org_id, csrf, key="base-style")
    _skill(client, org_id, csrf, key="top", dependencies=["base-style"])
    assert _version(client, org_id, csrf, "base-style").json()["version"] == 2
    assert _agent(client, org_id, csrf, key="pin-agent", skills=["top"])["status"] == 201
    assert {"key": "base-style", "version": 1} in _pins(engine, "pin-agent")


def test_conflicting_versions_of_one_skill_are_refused(client, engine):
    csrf, org_id = _base(client, engine, "dep-conflict@example.com")
    _skill(client, org_id, csrf, key="base-style")
    _skill(client, org_id, csrf, key="uses-old", dependencies=["base-style"])
    _version(client, org_id, csrf, "base-style")
    _skill(client, org_id, csrf, key="uses-new", dependencies=["base-style"])
    refused = _agent(client, org_id, csrf, key="conflict-agent", skills=["uses-old", "uses-new"])
    assert refused["status"] == 422 and refused["body"]["code"] == "skill_version_conflict"
    joined = _skill(client, org_id, csrf, key="joined", dependencies=["uses-old", "uses-new"])
    assert joined["status"] == 422 and joined["body"]["code"] == "skill_version_conflict"


def test_self_and_circular_dependencies_are_refused(client, engine):
    csrf, org_id = _base(client, engine, "dep-cycle@example.com")
    _skill(client, org_id, csrf, key="alpha")
    assert _version(client, org_id, csrf, "alpha", dependencies=["alpha"]).json()["code"] == "invalid_dependency"
    _skill(client, org_id, csrf, key="beta", dependencies=["alpha"])
    r = _version(client, org_id, csrf, "alpha", dependencies=["beta"])
    assert r.status_code == 422 and r.json()["code"] == "invalid_dependency"
    assert _skill(client, org_id, csrf, key="gamma", dependencies=["missing"])["status"] == 404


def test_dependency_rules_apply_to_the_agent_that_pins_them(client, engine):
    csrf, org_id = _base(client, engine, "dep-rules@example.com")
    _skill(client, org_id, csrf, key="needs-read", required_tools=["read_artifact"])
    _skill(client, org_id, csrf, key="wrapper-a", dependencies=["needs-read"])
    missing = _agent(client, org_id, csrf, key="tool-agent", skills=["wrapper-a"], tools=["read_project"])
    assert missing["body"]["code"] == "skill_tool_missing"
    _skill(client, org_id, csrf, key="arch-only", compatible_profiles=["solution_architect"])
    _skill(client, org_id, csrf, key="wrapper-b", dependencies=["arch-only"])
    wrong = _agent(client, org_id, csrf, key="profile-agent", skills=["wrapper-b"])
    assert wrong["body"]["code"] == "skill_not_compatible"


def test_stage_limits_are_enforced_when_the_stage_runs(client, engine, settings):
    csrf, org_id = _base(client, engine, "dep-stage@example.com")
    _skill(client, org_id, csrf, key="intake-only", compatible_stages=["intake"])
    assert _agent(client, org_id, csrf, key="stage-agent", skills=["intake-only"])["status"] == 201
    status, reason, fake = _run(client, engine, settings, "stage-agent", stage="design")
    assert status == "FAILED"
    assert reason == "agent refused: Skill 'intake-only' cannot be used in stage 'design'"
    assert fake.requests == []
    status, reason, _ = _run(client, engine, settings, "stage-agent", stage="intake")
    assert status == "AWAITING_HUMAN_REVIEW", reason


def test_stage_keys_are_validated(client, engine):
    csrf, org_id = _base(client, engine, "dep-badstage@example.com")
    r = _skill(client, org_id, csrf, key="bad-stage", compatible_stages=["Not A Stage"])
    assert r["status"] == 422 and r["body"]["code"] == "invalid_stage"


def test_agents_must_hold_the_role_the_stage_gives_them(client, engine, settings):
    csrf, org_id = _base(client, engine, "dep-kind@example.com")
    assert _agent(client, org_id, csrf, key="real-lead")["status"] == 201
    assert _agent(client, org_id, csrf, key="other-lead")["status"] == 201
    status, reason, fake = _run(client, engine, settings, "real-lead", reviewer="other-lead")
    assert status == "FAILED" and reason == "review refused: agent 'other-lead' is not a reviewer"
    assert fake.review_requests() == []
    assert _agent(client, org_id, csrf, key="only-critic", kind="reviewer", required_keys=["verdict", "findings"],
                  context_sources=["stage_artifact"], tools=[])["status"] == 201
    status, reason, _ = _run(client, engine, settings, "only-critic")
    assert status == "FAILED" and reason == "agent refused: agent 'only-critic' is not a lead"
