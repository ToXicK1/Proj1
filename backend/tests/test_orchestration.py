"""Phase 6 orchestration: tool calling with permissions, execution records, routing policies and specialists."""

import json

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agents import tool_runtime
from app.portal.lifecycle import LEAD_TOOLS, STAGES
from app.providers.models import AgentRun, ToolExecution
from app.workflows import service as engine
from app.workflows.models import StageExecution
from tests.test_portal import FIRST, _email, box, env  # noqa: F401  (fixtures)
from tests.test_providers_run import _provider, _route

SECOND = [s.id for s in STAGES if s.in_scope("poc") and s.gated][1]


class ToolUser:
    """Wraps the scripted model: when tools are offered and none has been used yet, it asks for one first."""

    def __init__(self, model, calls):
        self.model, self.calls, self.offered = model, calls, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.offered.append(bool(body.get("tools")))
        used = any(m.get("role") == "tool" for m in body["messages"])
        if body.get("tools") and (not used or self.calls == "always"):
            calls = self.calls if isinstance(self.calls, list) else [("list_approved_work", {})]
            return httpx.Response(200, json={"model": body["model"], "choices": [{"finish_reason": "tool_calls",
                "message": {"content": "", "tool_calls": [
                    {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                    for i, (n, a) in enumerate(calls)]}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
        return self.model.handler(request)

    def install(self, env):  # noqa: F811
        env.client.app.state.provider_transport = httpx.MockTransport(self.handler)


def _approve_first(env):  # noqa: F811
    person, h = env.holder()
    env.start()
    version = env.item(FIRST, person)["current_version_id"]
    assert env.decide(FIRST, version=version, client=person, headers=h).status_code == 200
    return person, h


def _runs(env, task):  # noqa: F811
    with Session(env.engine) as db:
        return db.execute(select(AgentRun).where(AgentRun.task == task).order_by(AgentRun.created_at)).scalars().all()


# Tools ------------------------------------------------------------------------------------------------------------

def test_a_lead_reads_approved_earlier_work_through_a_tool_and_the_call_is_recorded(env):  # noqa: F811
    env.setup_team()
    person, h = env.holder()
    env.start()
    version = env.item(FIRST, person)["current_version_id"]
    tools = ToolUser(env.model, [("read_artifact", {"stage": FIRST})])
    tools.install(env)
    assert env.decide(FIRST, version=version, client=person, headers=h).status_code == 200
    assert env.step_status(SECOND) == "Awaiting Review"
    with Session(env.engine) as db:
        calls = db.execute(select(ToolExecution)).scalars().all()
    read = [c for c in calls if c.tool == "read_artifact"]
    assert read and read[0].status == "ok" and read[0].permission_class == "READ"
    assert read[0].arguments == {"stage": FIRST} and read[0].result_chars > 50
    # the tool's answer went back to the model as data, in the same conversation
    later = [r for r in env.model.requests if FIRST in r["user"] or "problem_statement" in r["user"]]
    assert later
    feed = env.client.get(f"{env.base}/activity").json()  # the owner may not read the log...
    assert feed.get("code") == "not_permitted"


def _scope(env, stage_key, grants=LEAD_TOOLS):  # noqa: F811
    db = Session(env.engine)
    stage = db.execute(select(StageExecution).where(StageExecution.stage_key == stage_key)).scalar_one()
    return tool_runtime.ToolScope(db=db, stage_execution_id=stage.id, grants=tuple(grants))


def test_tools_see_only_approved_upstream_work_and_only_what_is_granted(env):  # noqa: F811
    env.setup_team()
    _approve_first(env)
    scope = _scope(env, SECOND)
    listing = json.loads(tool_runtime.execute(scope, "list_approved_work", "{}").content)["data"]
    assert [item["stage"] for item in listing] == [FIRST]  # setup steps have no deliverable; nothing later shows
    later = [s.id for s in STAGES if s.in_scope("poc") and s.gated][2]
    refused = tool_runtime.execute(scope, "read_artifact", json.dumps({"stage": later}))
    assert refused.status == "refused" and "not approved earlier work" in refused.summary
    field = tool_runtime.execute(scope, "read_artifact", json.dumps({"stage": FIRST, "field": "problem_statement"}))
    assert field.status == "ok" and "problem_statement" in field.content
    found = tool_runtime.execute(scope, "search_approved_work", json.dumps({"query": "written from the input"}))
    assert found.status == "ok" and json.loads(found.content)["data"]
    project = json.loads(tool_runtime.execute(scope, "read_project", "{}").content)["data"]
    assert project["name"] == "Hiring hub" and project["confirmed_brief"]
    narrow = _scope(env, SECOND, grants=("read_project",))
    assert tool_runtime.execute(narrow, "read_artifact", json.dumps({"stage": FIRST})).status == "refused"
    assert tool_runtime.execute(narrow, "write_note", "{}").summary == "refused: unknown write_note"
    assert tool_runtime.execute(narrow, "publish_release", "{}").status == "refused"
    assert tool_runtime.execute(scope, "read_artifact", "not json").status == "error"
    assert tool_runtime.execute(scope, "read_artifact", json.dumps({"stage": FIRST, "x": 1})).status == "error"
    assert tool_runtime.execute(scope, "search_approved_work", json.dumps({"query": "a"})).status == "error"


def test_the_first_stage_has_no_earlier_work_to_read(env):  # noqa: F811
    env.setup_team()
    env.start()
    scope = _scope(env, FIRST)
    assert json.loads(tool_runtime.execute(scope, "list_approved_work", "{}").content)["data"] == []


def test_tool_use_is_bounded_and_the_model_must_then_answer(env):  # noqa: F811
    env.setup_team()
    tools = ToolUser(env.model, "always")
    tools.install(env)
    env.start()
    assert env.step_status(FIRST) == "Awaiting Review"  # it answered once tools were no longer offered
    assert tools.offered[:5] == [True, True, True, True, False]
    with Session(env.engine) as db:
        assert db.execute(text("select count(*) from tool_executions")).scalar() == 4


def test_a_tool_call_limit_stops_runaway_use(env):  # noqa: F811
    env.setup_team()
    env.start()
    scope = _scope(env, FIRST)
    results = [tool_runtime.execute(scope, "read_project", "{}") for _ in range(tool_runtime.MAX_CALLS_PER_RUN + 2)]
    assert [r.status for r in results][-2:] == ["refused", "refused"]


# Execution records --------------------------------------------------------------------------------------------------

def test_every_lead_run_records_what_it_was_given_allowed_and_produced(env):  # noqa: F811
    env.setup_team()
    _approve_first(env)
    lead = [r for r in _runs(env, "lead") if r.output_artifact_version_id][-1]
    assert lead.profile_key and lead.correlation_id
    assert len(lead.context_digest) == 64
    assert sorted(lead.tool_grants) == sorted(LEAD_TOOLS)
    with Session(env.engine) as db:
        first_version = db.execute(text(
            "select av.id from artifact_versions av join artifacts a on a.id = av.artifact_id where a.kind = :k"),
            {"k": FIRST}).scalar_one()
        produced = db.execute(text("select a.kind from artifact_versions av join artifacts a on a.id = av.artifact_id "
                                   "where av.id = :v"), {"v": lead.output_artifact_version_id}).scalar_one()
    assert lead.input_versions == [str(first_version)]  # the approved version it was given, by id
    assert produced == SECOND
    reviewer = _runs(env, "reviewer")[-1]
    assert reviewer.input_versions == [str(lead.output_artifact_version_id)]


# Routing policies ---------------------------------------------------------------------------------------------------

def _policy(env, rules, client=None, headers=None):  # noqa: F811
    return (client or env.client).put(f"/api/v1/orgs/{env.org}/routing-policies", headers=headers or env.h,
                                      json={"rules": rules})


def test_routing_policy_chooses_the_route_per_task_and_department(env):  # noqa: F811
    env.setup_team()
    other = _provider(env.client, env.csrf, env.org, "second-vendor", "openai_compatible",
                      base_url="http://localhost:11435/v1")
    _route(env.client, env.csrf, env.org, "analysis-route", other["id"], "analysis-model")
    r = _policy(env, [{"task": "lead", "profile": "business_analyst", "route": "analysis-route"}])
    assert r.status_code == 200, r.text
    env.start()
    lead = _runs(env, "lead")[-1]
    assert lead.route_key == "analysis-route" and lead.model == "analysis-model"
    assert all(r.route_key == "private-route" for r in _runs(env, "reviewer"))  # no rule for reviewers


def test_an_independent_review_must_use_another_provider_when_the_policy_says_so(env):  # noqa: F811
    env.setup_team()
    assert _policy(env, [{"task": "reviewer", "route": "private-route",
                          "require_different_provider": True}]).status_code == 200
    env.start()  # the only provider wrote the work, so no independent reviewer is available
    with Session(env.engine) as db:
        reason = db.execute(select(StageExecution.failure_reason).where(StageExecution.stage_key == FIRST)).scalar()
    assert reason == "review failed: no_independent_provider"


def test_with_a_second_provider_the_review_comes_from_it(env):  # noqa: F811
    env.setup_team()
    other = _provider(env.client, env.csrf, env.org, "second-vendor", "openai_compatible",
                      base_url="http://localhost:11435/v1")
    first = next(p for p in env.client.get(f"/api/v1/orgs/{env.org}/providers").json()["items"]
             if p["name"] == "secret-vendor")
    _route(env.client, env.csrf, env.org, "review-route", first["id"], "private-model-9",
           fallbacks=[{"provider_id": other["id"], "model": "review-model"}])
    assert _policy(env, [{"task": "reviewer", "route": "review-route",
                          "require_different_provider": True}]).status_code == 200
    env.start()
    lead, review = _runs(env, "lead")[-1], _runs(env, "reviewer")[-1]
    assert review.provider_id != lead.provider_id and review.model == "review-model"
    assert env.step_status(FIRST) == "Awaiting Review"


def test_routing_policies_are_validated_and_for_administrators_only(env):  # noqa: F811
    env.setup_team()
    bad = _policy(env, [{"task": "lead", "route": "nowhere"},
                        {"task": "lead", "route": "private-route", "require_different_provider": True}])
    assert bad.status_code == 422 and "no model route" in bad.text and "only reviewer rules" in bad.text
    dup = _policy(env, [{"task": "triage", "route": "private-route"}, {"task": "triage", "route": "private-route"}])
    assert dup.status_code == 422
    person, h, _ = env.person()
    assert _policy(env, [], client=person, headers=h).status_code == 403
    assert person.get(f"/api/v1/orgs/{env.org}/routing-policies").status_code == 403


# Specialists and the registry ---------------------------------------------------------------------------------------

def test_a_specialist_advises_the_lead_and_is_recorded_on_its_own(env, monkeypatch):  # noqa: F811
    env.setup_team()
    r = env.client.post(f"/api/v1/orgs/{env.org}/agents", headers=env.h, json={
        "key": "ba-market-specialist", "kind": "specialist", "profile": "business_analyst",
        "instructions": "You know the recruitment market well.", "required_keys": ["advice"],
        "model_route": "private-route", "context_sources": ["project_input"], "tools": []})
    assert r.status_code == 201, r.text
    original = engine.stage_spec

    def with_specialist(version, stage_key):
        spec = dict(original(version, stage_key))
        if stage_key == FIRST:
            spec["specialists"] = ["ba-market-specialist"]
        return spec

    monkeypatch.setattr(engine, "stage_spec", with_specialist)
    original_start = engine.start_execution

    def start_with_specialist(db, user, **kw):
        execution = original_start(db, user, **kw)
        from app.agents import service as agents

        execution.config_snapshot = {**execution.config_snapshot, "agent_versions": {
            **execution.config_snapshot["agent_versions"],
            **agents.snapshot_versions(db, execution.organization_id, {"ba-market-specialist"})}}
        db.commit()
        return execution

    monkeypatch.setattr(engine, "start_execution", start_with_specialist)
    env.start()
    specialist = _runs(env, "specialist")
    assert specialist and specialist[0].profile_key == "business_analyst"
    lead_prompt = next(r for r in env.model.requests if "KEYS: problem_statement" in r["system"])
    assert "advice from support specialists (advisory; you decide): ba-market-specialist:" in lead_prompt["user"]
    assert env.step_status(FIRST) == "Awaiting Review"


def test_specialist_settings_are_checked_when_a_workflow_is_compiled():
    from app.portal.lifecycle import workflow_spec
    from app.workflows.compiler import CompileError, compile_workflow
    from app.workflows.work import KNOWN_WORK

    spec = workflow_spec("poc")
    stage = next(s for s in spec["stages"] if s.get("agent"))
    stage["specialists"] = [stage["agent"], "Not Valid"]
    with pytest.raises(CompileError) as refused:
        compile_workflow(spec, known_work=set(KNOWN_WORK))
    problems = " ".join(refused.value.problems)
    assert "already this stage's lead" in problems and "not a valid agent key" in problems


def test_the_registry_lists_each_departments_agents(env):  # noqa: F811
    env.setup_team()
    registry = env.client.get(f"/api/v1/orgs/{env.org}/agent-registry").json()["departments"]
    ba = next(d for d in registry if d["profile"] == "business_analyst")
    assert {e["key"] for e in ba["reviewers"]} == {"business-analyst-reviewer"}
    assert ba["leads"] and all(sorted(e["tools"]) == sorted(LEAD_TOOLS) for e in ba["leads"])
    person, _, _ = env.person()
    assert person.get(f"/api/v1/orgs/{env.org}/agent-registry").status_code == 403


def test_existing_teams_get_the_read_tools_on_their_next_provisioning(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.portal.lifecycle.LEAD_TOOLS", ())  # a team set up before tools existed
    env.setup_team()
    monkeypatch.undo()
    env.setup_team()  # provisioning again brings older leads up to date with a new version
    registry = env.client.get(f"/api/v1/orgs/{env.org}/agent-registry").json()["departments"]
    leads = [e for d in registry for e in d["leads"]]
    assert leads and all(sorted(e["tools"]) == sorted(LEAD_TOOLS) and e["version"] == 2 for e in leads)
