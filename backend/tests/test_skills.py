"""Skills and provider pinning: admin rules, pinned versions, immutability, fallback control."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.workflows import service as wf
from tests.fake_llm import FakeLLM
from tests.helpers import signup_verify_login
from tests.test_agents import _start
from tests.test_approvals import _publish
from tests.test_providers_run import _org_id, _provider, _route


def _base(client, engine, email: str) -> tuple[str, str]:
    """Owner, two providers (the first always fails with 503, the second is the fake model), a route
    through both, and the two profiles. Returns (csrf, org_id)."""
    csrf = signup_verify_login(client, engine, email)
    org_id = _org_id(client)
    primary = _provider(client, csrf, org_id, "primary-down", "openai_compatible",
                        base_url="http://localhost:11434/v1")
    backup = _provider(client, csrf, org_id, "backup-fake", "openai_compatible",
                       base_url="http://localhost:11435/v1")
    _route(client, csrf, org_id, "drafting", primary["id"], "fake-1",
           fallbacks=[{"provider_id": backup["id"], "model": "fake-1"}])
    h = {"X-CSRF-Token": csrf}
    for key, name in [("business_analyst", "BA"), ("solution_architect", "Architect")]:
        assert client.post(f"/api/v1/orgs/{org_id}/profiles", json={"key": key, "name": name}, headers=h).status_code == 201
    return csrf, org_id


def _outage_then_fake(fake: FakeLLM):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 11434:
            return httpx.Response(503, json={"error": "down"})
        return fake.handler(request)

    return httpx.MockTransport(handler)


def _agent(client, org_id, csrf, **kw) -> dict:
    body = {"profile": "business_analyst", "kind": "lead", "instructions": "You are a business analyst.",
            "required_keys": ["summary"], "model_route": "drafting", "context_sources": ["project_input"],
            "tools": ["read_project"], **kw}
    r = client.post(f"/api/v1/orgs/{org_id}/agents", json=body, headers={"X-CSRF-Token": csrf})
    return {"status": r.status_code, "body": r.json()}


def _skill(client, org_id, csrf, **kw) -> dict:
    body = {"instructions": "Write in plain English.", "required_tools": [], "compatible_profiles": [], **kw}
    r = client.post(f"/api/v1/orgs/{org_id}/skills", json=body, headers={"X-CSRF-Token": csrf})
    return {"status": r.status_code, "body": r.json()}


# --- skill administration -------------------------------------------------------------------------

def test_admins_create_and_version_skills(client, engine):
    csrf, org_id = _base(client, engine, "skill-admin@example.com")
    assert _skill(client, org_id, csrf, key="plain-english")["status"] == 201
    assert _skill(client, org_id, csrf, key="plain-english")["status"] == 409
    r = client.post(f"/api/v1/orgs/{org_id}/skills/plain-english/versions",
                    json={"instructions": "Write in plain English. Avoid jargon.", "required_tools": [],
                          "compatible_profiles": []}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201 and r.json()["version"] == 2
    listed = client.get(f"/api/v1/orgs/{org_id}/skills").json()["items"]
    assert listed == [{"key": "plain-english", "version": 2, "required_tools": [], "compatible_profiles": []}]


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"required_tools": ["publish_release"]}, "invalid_tools"),
        ({"required_tools": ["edit_rules"]}, "invalid_tools"),
        ({"compatible_profiles": ["no_such_profile"]}, "unknown_profile"),
        ({"instructions": "   "}, "invalid_instructions"),
        ({"key": "Bad Key"}, "invalid_key"),
    ],
)
def test_unsafe_skills_are_refused(client, engine, kw, code):
    csrf, org_id = _base(client, engine, f"skill-bad-{code}-{len(kw)}@example.com")
    body = {"key": "safe-key", **kw}
    response = _skill(client, org_id, csrf, **body)
    assert response["status"] == 422
    assert response["body"]["code"] == code


def test_skills_are_admin_only(client, engine):
    _base(client, engine, "skill-rbac@example.com")
    org_id = _org_id(client)
    from fastapi.testclient import TestClient

    with TestClient(client.app) as stranger:
        csrf = signup_verify_login(stranger, engine, "skill-stranger@example.com", name="Stranger")
        r = stranger.post(f"/api/v1/orgs/{org_id}/skills", json={"key": "x-skill", "instructions": "x"},
                          headers={"X-CSRF-Token": csrf})
        assert r.status_code == 404


# --- pinning an agent to skill versions -----------------------------------------------------------

def test_agents_pin_skill_versions_and_checks_apply(client, engine):
    csrf, org_id = _base(client, engine, "skill-pin@example.com")
    _skill(client, org_id, csrf, key="plain-english")
    _skill(client, org_id, csrf, key="needs-read", required_tools=["read_artifact"])
    _skill(client, org_id, csrf, key="architects-only", compatible_profiles=["solution_architect"])

    ok = _agent(client, org_id, csrf, key="pinned-ok", skills=["plain-english"])
    assert ok["status"] == 201
    missing = _agent(client, org_id, csrf, key="pin-missing", skills=["nope"])
    assert missing["status"] == 404
    incompatible = _agent(client, org_id, csrf, key="pin-profile", skills=["architects-only"])
    assert incompatible["body"]["code"] == "skill_not_compatible"
    tool = _agent(client, org_id, csrf, key="pin-tool", skills=["needs-read"], tools=["read_project"])
    assert tool["body"]["code"] == "skill_tool_missing"  # the agent does not hold the skill's tool

    with Session(engine) as s:
        pins = s.execute(text(
            "select v.skills::text from agent_config_versions v join agent_configurations a on a.id = v.agent_id "
            "where a.key = 'pinned-ok'")).scalar_one()
    assert json.loads(pins) == [{"key": "plain-english", "version": 1}]


def test_a_pinned_skill_version_does_not_change_when_the_skill_is_edited(client, engine, settings):
    csrf, org_id = _base(client, engine, "skill-immutable@example.com")
    _skill(client, org_id, csrf, key="voice", instructions="Speak in short sentences.")
    assert _agent(client, org_id, csrf, key="voice-agent", skills=["voice"])["status"] == 201
    client.post(f"/api/v1/orgs/{org_id}/skills/voice/versions", headers={"X-CSRF-Token": csrf},
                json={"instructions": "Speak formally.", "required_tools": [], "compatible_profiles": []})

    version = _publish(engine, {"key": f"voice-{uuid.uuid4().hex[:6]}", "name": "voice", "stages": [{
        "id": "ba", "name": "BA", "depends_on": [], "work": "ai:requirements_draft", "agent": "voice-agent",
        "profile": "business_analyst", "output_required_keys": ["summary"]}]})
    execution_id, _ = _start(client, engine, version)
    fake = FakeLLM()
    with Session(engine) as s:
        wf.run_deterministic_stage(s, execution_id=execution_id, stage_key="ba",
                                   settings=settings.model_copy(update={"provider_backoff_seconds": 0.0}),
                                   transport=_outage_then_fake(fake))
    system = fake.lead_requests()[0]["system"]
    assert "Speak in short sentences." in system and "Speak formally." not in system
    with engine.connect() as conn:
        manifest = conn.execute(text(
            "select context_manifest::text from agent_runs where kind = 'lead' and status = 'succeeded'")).scalar_one()
    assert json.loads(manifest)["skills"] == [{"key": "voice", "version": 1}]


def test_skill_versions_are_immutable(client, engine):
    csrf, org_id = _base(client, engine, "skill-immutable-db@example.com")
    _skill(client, org_id, csrf, key="frozen")
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("update skill_versions set instructions = 'changed'"))


# --- provider pinning ----------------------------------------------------------------------------

def _review_flow(client, engine, settings, org_id: str, csrf: str, allow_fallback: bool, tag: str):
    """A lead (which may fall back) and a reviewer (pinned or not) on the same route."""
    lead = _agent(client, org_id, csrf, key=f"lead-{tag}", kind="lead")
    assert lead["status"] == 201, lead["body"]
    reviewer = _agent(client, org_id, csrf, key=f"critic-{tag}", kind="reviewer", profile="business_analyst",
                      instructions="You review critically.", required_keys=["verdict", "findings"],
                      context_sources=["stage_artifact"], tools=[], allow_fallback=allow_fallback)
    assert reviewer["status"] == 201, reviewer["body"]
    version = _publish(engine, {"key": f"pin-{tag}-{uuid.uuid4().hex[:6]}", "name": "pin", "stages": [{
        "id": "ba", "name": "BA", "depends_on": [], "work": "ai:requirements_draft", "agent": f"lead-{tag}",
        "reviewer": f"critic-{tag}", "profile": "business_analyst", "output_required_keys": ["summary"]}]})
    execution_id, _ = _start(client, engine, version)
    fake = FakeLLM()
    with Session(engine) as s:
        stage = wf.run_deterministic_stage(s, execution_id=execution_id, stage_key="ba",
                                           settings=settings.model_copy(update={"provider_backoff_seconds": 0.0}),
                                           transport=_outage_then_fake(fake))
        return stage.status, stage.failure_reason, fake


def test_a_pinned_reviewer_does_not_fall_back_to_another_provider(client, engine, settings):
    csrf, org_id = _base(client, engine, "pin-reviewer@example.com")
    status, reason, fake = _review_flow(client, engine, settings, org_id, csrf, allow_fallback=False, tag="pinned")
    assert status == "FAILED" and reason == "review failed: unavailable"
    assert fake.review_requests() == []  # the backup provider never saw the review


def test_an_unpinned_reviewer_falls_back_and_completes(client, engine, settings):
    csrf, org_id = _base(client, engine, "pin-free@example.com")
    status, reason, fake = _review_flow(client, engine, settings, org_id, csrf, allow_fallback=True, tag="free")
    assert status == "AWAITING_HUMAN_REVIEW", reason
    assert len(fake.review_requests()) == 1
