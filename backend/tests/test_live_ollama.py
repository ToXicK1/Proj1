"""Live test against a local Ollama server (OpenAI-compatible endpoint). Runs only when configured.

Set these before running:
    AIDLC_LIVE_OLLAMA_URL=http://127.0.0.1:11434/v1
    AIDLC_LIVE_OLLAMA_MODEL=qwen3-vl:4b-instruct
then:  .venv\\Scripts\\python -m pytest -m live

Without the variables the tests are skipped, so CI stays offline and free.
"""

import os

import pytest

from app.providers.adapters import build_adapter
from app.providers.base import CompletionRequest
from tests.helpers import signup_verify_login
from tests.test_providers_run import _execution, _org_id, _provider, _route, _run, _runs

URL = os.environ.get("AIDLC_LIVE_OLLAMA_URL")
MODEL = os.environ.get("AIDLC_LIVE_OLLAMA_MODEL", "qwen3-vl:4b-instruct")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not URL, reason="AIDLC_LIVE_OLLAMA_URL not set; live Ollama test skipped"),
]


def test_adapter_gets_a_real_structured_answer_from_ollama():
    adapter = build_adapter("openai_compatible", api_key=None, base_url=URL, app_env="test")
    result = adapter.complete(CompletionRequest(
        system="Reply with one JSON object only. KEYS: summary, assumptions, open_questions",
        user="A remote hiring tool for recruiters.",
        model=MODEL,
        max_tokens=512,
        timeout_seconds=300,
    ))
    assert "summary" in result.text
    assert result.usage.output_tokens > 0


def test_stage_runs_through_the_product_on_the_local_model(client, engine, settings):
    csrf = signup_verify_login(client, engine, "live-ollama@example.com")
    org_id = _org_id(client)
    ollama = _provider(client, csrf, org_id, "ollama-local", "openai_compatible", base_url=URL)
    _route(client, csrf, org_id, "local-drafting", ollama["id"], MODEL)
    execution_id = _execution(client, engine, "local-drafting")

    probe = client.post(f"/api/v1/orgs/{org_id}/providers/{ollama['id']}/health", json={"model": MODEL},
                        headers={"X-CSRF-Token": csrf})
    assert probe.json()["ok"] is True, probe.text

    status, reason = _run(engine, settings, None, execution_id)
    assert status == "AWAITING_HUMAN_REVIEW", reason
    assert _runs(engine, execution_id) == [(1, "succeeded", None, "openai_compatible")]


def test_lead_and_reviewer_agents_run_on_the_local_model(client, engine, settings):
    """Two agents with separate lineage: the lead drafts, the reviewer checks the draft alone."""
    from sqlalchemy.orm import Session

    from app.workflows import service as wf
    from tests.test_agents import BA_LEAD, BA_REVIEWER, _start
    from tests.test_approvals import _publish

    csrf = signup_verify_login(client, engine, "live-agents@example.com")
    org_id = _org_id(client)
    provider = _provider(client, csrf, org_id, "ollama-agents", "openai_compatible", base_url=URL)
    _route(client, csrf, org_id, "drafting", provider["id"], MODEL)
    h = {"X-CSRF-Token": csrf}
    assert client.post(f"/api/v1/orgs/{org_id}/profiles", json={"key": "business_analyst", "name": "BA"}, headers=h).status_code == 201
    for agent in (BA_LEAD, BA_REVIEWER):
        assert client.post(f"/api/v1/orgs/{org_id}/agents", json=agent, headers=h).status_code == 201

    version = _publish(engine, {"key": "live-agent-stage", "name": "live", "stages": [{
        "id": "ba", "name": "BA", "depends_on": [], "work": "ai:requirements_draft", "agent": "ba-analyst",
        "reviewer": "ba-critic", "profile": "business_analyst", "output_required_keys": ["summary"]}]})
    execution_id, _ = _start(client, engine, version)
    with Session(engine) as s:
        stage = wf.run_deterministic_stage(s, execution_id=execution_id, stage_key="ba",
                                           settings=settings.model_copy(update={"provider_backoff_seconds": 0.0}))
        status, reason = stage.status, stage.failure_reason
    assert status == "AWAITING_HUMAN_REVIEW", reason


def test_skill_rule_and_sensor_apply_on_the_local_model(client, engine, settings):
    """A pinned skill and an organization rule reach the model; a sensor checks what it wrote."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.workflows import service as wf
    from tests.test_agents import BA_LEAD, _start
    from tests.test_approvals import _publish

    csrf = signup_verify_login(client, engine, "live-governed@example.com")
    org_id = _org_id(client)
    h = {"X-CSRF-Token": csrf}
    provider = _provider(client, csrf, org_id, "ollama-governed", "openai_compatible", base_url=URL)
    _route(client, csrf, org_id, "drafting", provider["id"], MODEL)
    assert client.post(f"/api/v1/orgs/{org_id}/profiles", json={"key": "business_analyst", "name": "BA"},
                       headers=h).status_code == 201
    assert client.post(f"/api/v1/orgs/{org_id}/skills", headers=h, json={
        "key": "plain-language", "instructions": "Use short, plain sentences."}).status_code == 201
    assert client.post(f"/api/v1/orgs/{org_id}/agents", headers=h,
                       json={**BA_LEAD, "skills": ["plain-language"]}).status_code == 201
    assert client.post(f"/api/v1/orgs/{org_id}/rules", headers=h, json={
        "key": "state-assumptions", "scope_type": "organization", "scope_key": "", "kind": "documentation",
        "name": "State assumptions", "content": "List every assumption you make."}).status_code == 201
    version = _publish(engine, {"key": "live-governed", "name": "live", "stages": [{
        "id": "ba", "name": "BA", "work": "ai:requirements_draft", "agent": "ba-analyst",
        "profile": "business_analyst", "output_required_keys": ["summary"],
        "sensors": [{"key": "required_sections", "config": {"sections": ["summary"]}},
                    {"key": "secret_detection"}, {"key": "artifact_version"}]}]})
    execution_id, _ = _start(client, engine, version)
    with Session(engine) as s:
        stage = wf.run_deterministic_stage(s, execution_id=execution_id, stage_key="ba",
                                           settings=settings.model_copy(update={"provider_backoff_seconds": 0.0}))
        assert stage.status == "AWAITING_HUMAN_REVIEW", stage.failure_reason
    with engine.connect() as conn:
        statuses = set(conn.execute(text("select status from sensor_executions")).scalars())
        manifest = conn.execute(text("select context_manifest::text from agent_runs where status = 'succeeded'")).scalar_one()
    assert statuses == {"PASS"}
    assert "plain-language" in manifest and "state-assumptions" in manifest
