"""Workflow Studio: drafts, publishing, tenant isolation and import/export."""

import json
import uuid

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.helpers import signup_verify_login
from tests.test_agents import BA_LEAD, BA_REVIEWER
from tests.test_approvals import _add_member, _publish, _user_id
from tests.test_governance import Env
from tests.test_providers_run import _org_id, _provider, _route


def _email() -> str:
    return f"s-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def admin(client, engine, settings):
    return Env(client, engine, settings, _email())


def _key() -> str:
    return f"wf-{uuid.uuid4().hex[:8]}"


def _stage(stage_id="doc", **extra):
    return {"id": stage_id, "name": stage_id.title(), "work": "intake_summary", **extra}


def _spec(key, *stages):
    return {"key": key, "name": "Custom flow", "stages": list(stages) or [_stage()]}


def _url(env, path=""):
    return f"/api/v1/orgs/{env.org}/studio{path}"


def _save(env, spec, revision=None):
    return env.client.put(_url(env, f"/workflows/{spec['key']}/draft"), headers=env.h,
                          json={"spec": spec, "expected_revision": revision})


def _publish_draft(env, key, revision=1):
    return env.client.post(_url(env, f"/workflows/{key}/publish"), headers=env.h,
                           json={"expected_revision": revision})


def _problems(env, spec):
    assert _save(env, spec).status_code == 200
    r = _publish_draft(env, spec["key"])
    assert r.status_code == 422 and r.json()["code"] == "invalid_workflow"
    return " | ".join(r.json()["problems"])


def _project(env, client=None, headers=None, org=None):
    return (client or env.client).post(f"/api/v1/orgs/{org or env.org}/projects", headers=headers or env.h,
                                       json={"name": "P", "description": "d", "project_type": "API"}).json()["id"]


def _start(env, project, version, client=None, headers=None):
    return (client or env.client).post(f"/api/v1/projects/{project}/workflow-executions", headers=headers or env.h,
                                       json={"workflow_version_id": version})


def _other(env):
    client = TestClient(env.client.app)
    csrf = signup_verify_login(client, env.engine, _email(), name="Other")
    return client, {"X-CSRF-Token": csrf}, _org_id(client)


def _agents(env):
    provider = _provider(env.client, env.csrf, env.org, "fake", "openai_compatible",
                         base_url="http://localhost:11434/v1")
    _route(env.client, env.csrf, env.org, "drafting", provider["id"], "fake-1")
    base = f"/api/v1/orgs/{env.org}"
    assert env.client.post(f"{base}/profiles", headers=env.h,
                           json={"key": "business_analyst", "name": "BA"}).status_code == 201
    for agent in (BA_LEAD, BA_REVIEWER):
        assert env.client.post(f"{base}/agents", headers=env.h, json=agent).status_code == 201


def test_an_admin_publishes_a_custom_profile_stage_and_gate_that_really_gates(admin):
    assert admin.client.post(f"/api/v1/orgs/{admin.org}/profiles", headers=admin.h,
                             json={"key": "compliance", "name": "Compliance"}).status_code == 201
    key = _key()
    spec = _spec(key, _stage("review", profile="compliance", output_required_keys=["word_count"],
                             approval_policy={"type": "single", "role": "internal_reviewer"}))
    assert _save(admin, spec).json()["revision"] == 1
    published = _publish_draft(admin, key)
    assert published.status_code == 201 and published.json()["version"] == 1

    project = _project(admin)
    execution = _start(admin, project, published.json()["id"])
    assert execution.status_code == 201
    execution = execution.json()["id"]
    assert admin.run(execution, "review")[0] == "AWAITING_HUMAN_REVIEW"
    assert admin.decide(execution, stage="review").status_code == 403  # the gate wants a reviewer, not the owner

    reviewer = TestClient(admin.client.app)
    email = _email()
    csrf = signup_verify_login(reviewer, admin.engine, email, name="Reviewer")
    _add_member(admin.engine, uuid.UUID(project), _user_id(admin.engine, email), "internal_reviewer")
    version = admin.view(execution, "review")["artifact"]["version_id"]
    r = reviewer.post(f"/api/v1/workflow-executions/{execution}/stages/review/decisions",
                      headers={"X-CSRF-Token": csrf},
                      json={"artifact_version_id": version, "decision": "APPROVE", "comment": "",
                            "idempotency_key": f"k-{uuid.uuid4().hex}"})
    assert r.status_code == 200, r.text
    with admin.engine.connect() as conn:
        payload = conn.execute(text("select payload from audit_events where event_type = 'workflow.published' "
                                    "order by occurred_at desc limit 1")).scalar_one()
    assert payload["workflow_key"] == key and payload["version"] == 1


@pytest.mark.parametrize("stages, expected", [
    ([_stage(work="unknown_work")], "unknown work function"),
    ([_stage("a", depends_on=["b"]), _stage("b", depends_on=["a"])], "circular dependency"),
    ([_stage(depends_on=["missing"])], "unknown stage 'missing'"),
    ([_stage(approval_policy={"type": "single", "role": "ceo"})], "approval_policy"),
    ([_stage(sensors=[{"key": "not_a_sensor"}])], "unknown sensor"),
    ([_stage(profile="missing")], "unknown profile"),
    ([_stage(output_required_keys=["never_made"])], "never produces 'never_made'"),
    ([_stage(work="ai:requirements_draft", model_route="missing")], "unknown model route"),
    ([_stage(work="ai:requirements_draft", agent="missing")], "unknown agent"),
])
def test_invalid_workflows_save_as_drafts_but_never_publish(admin, stages, expected):
    key = _key()
    assert expected in _problems(admin, _spec(key, *stages))
    with admin.engine.connect() as conn:
        assert conn.execute(text("select count(*) from workflow_definitions where key = :k"), {"k": key}).scalar() == 0


def test_every_problem_is_reported_at_once(admin):
    found = admin.client.post(_url(admin, "/validate"), headers=admin.h, json={"spec": _spec(
        "BAD KEY", _stage("a", work="nope"), _stage("b", profile="missing"))}).json()
    assert not found["valid"]
    joined = " ".join(found["problems"])
    assert "key:" in joined and "unknown work function" in joined and "unknown profile" in joined
    shape = admin.client.post(_url(admin, "/validate"), headers=admin.h, json={"spec": {"stages": "x"}}).json()
    assert not shape["valid"] and shape["problems"]


def test_agent_references_must_be_the_right_kind_and_independent(admin):
    _agents(admin)
    base = _stage(work="ai:requirements_draft")
    assert "not a lead agent" in _problems(admin, _spec(_key(), {**base, "agent": "ba-critic"}))
    assert admin.client.post(f"/api/v1/orgs/{admin.org}/agents", headers=admin.h, json={
        **BA_REVIEWER, "key": "ba-clone", "clone_of": "ba-analyst"}).status_code == 201
    assert "not independent" in _problems(admin, _spec(_key(), {**base, "agent": "ba-analyst",
                                                                "reviewer": "ba-clone"}))
    assert admin.client.post(f"/api/v1/orgs/{admin.org}/agents", headers=admin.h, json={
        **BA_LEAD, "key": "second-lead"}).status_code == 201
    assert "not a reviewer agent" in _problems(admin, _spec(_key(), {**base, "agent": "ba-analyst",
                                                                     "reviewer": "second-lead"}))
    assert "does not belong to profile" in _problems(admin, _spec(_key(), {**base, "agent": "ba-analyst",
                                                                           "profile": "missing"}))
    good = _spec(_key(), {**base, "agent": "ba-analyst", "reviewer": "ba-critic", "profile": "business_analyst",
                          "output_required_keys": ["summary"]})
    assert _save(admin, good).status_code == 200
    assert _publish_draft(admin, good["key"]).status_code == 201


def test_only_admins_of_the_organization_use_the_studio(admin):
    key = _key()
    _save(admin, _spec(key))
    stranger, h, _ = _other(admin)
    assert stranger.get(_url(admin, "/workflows")).status_code == 404
    assert stranger.get(_url(admin, "/catalog")).status_code == 404
    assert stranger.get(_url(admin, f"/workflows/{key}")).status_code == 404
    assert stranger.get(_url(admin, f"/workflows/{key}/export")).status_code == 404
    assert stranger.put(_url(admin, f"/workflows/{key}/draft"), headers=h,
                        json={"spec": _spec(key), "expected_revision": 1}).status_code == 404
    assert stranger.post(_url(admin, f"/workflows/{key}/publish"), headers=h,
                         json={"expected_revision": 1}).status_code == 404
    assert stranger.post(_url(admin, "/import"), headers=h,
                         json={"format": "json", "content": json.dumps(_spec(_key()))}).status_code == 404
    assert stranger.post(_url(admin, "/validate"), headers=h, json={"spec": _spec(key)}).status_code == 404

    with admin.engine.begin() as conn:
        conn.execute(text("insert into memberships (id, organization_id, user_id, role) "
                          "select :id, :org, id, 'member' from users where email = (select email from users u "
                          "join memberships m on m.user_id = u.id where m.organization_id = :other limit 1)"),
                     {"id": uuid.uuid4(), "org": uuid.UUID(admin.org), "other": uuid.UUID(_org_id(stranger))})
    assert stranger.get(_url(admin, "/workflows")).status_code == 403
    assert stranger.post(_url(admin, f"/workflows/{key}/publish"), headers=h,
                         json={"expected_revision": 1}).status_code == 403
    assert stranger.put(_url(admin, f"/workflows/{key}/draft"), headers=h,
                        json={"spec": _spec(key), "expected_revision": 1}).status_code == 403
    assert admin.client.post(_url(admin, f"/workflows/{key}/publish"),
                             json={"expected_revision": 1}).status_code == 403  # no CSRF token


def test_a_published_workflow_stays_inside_its_organization(admin):
    key = _key()
    _save(admin, _spec(key))
    version = _publish_draft(admin, key).json()["id"]
    other, h, other_org = _other(admin)
    project = _project(admin, other, h, other_org)
    r = _start(admin, project, version, other, h)
    assert r.status_code == 404 and r.json()["code"] == "unknown_workflow_version"
    assert key not in [w["key"] for w in other.get(f"/api/v1/orgs/{other_org}/studio/workflows").json()["items"]]
    # the same key is free for another organization
    assert other.put(f"/api/v1/orgs/{other_org}/studio/workflows/{key}/draft", headers=h,
                     json={"spec": _spec(key)}).status_code == 200
    second = other.post(f"/api/v1/orgs/{other_org}/studio/workflows/{key}/publish", headers=h,
                        json={"expected_revision": 1})
    assert second.status_code == 201 and second.json()["version"] == 1
    assert _start(admin, project, second.json()["id"], other, h).status_code == 201


def test_platform_templates_stay_usable_but_their_keys_are_reserved(admin):
    key = _key()
    version = _publish(admin.engine, _spec(key))
    items = {w["key"]: w for w in admin.client.get(_url(admin, "/workflows")).json()["items"]}
    assert items[key]["scope"] == "platform"
    assert _start(admin, _project(admin), str(version)).status_code == 201
    assert "reserved by a platform template" in _problems(admin, _spec(key))
    copied = admin.client.get(_url(admin, f"/workflows/{key}")).json()
    assert copied["scope"] == "platform" and copied["versions"][0]["version"] == 1


def test_edits_cannot_overwrite_each_other_and_versions_are_kept(admin):
    key = _key()
    assert _save(admin, _spec(key)).status_code == 200
    assert _save(admin, _spec(key)).json()["code"] == "draft_conflict"  # no revision given for an existing draft
    assert _save(admin, _spec(key), 7).json()["code"] == "draft_conflict"
    first = _publish_draft(admin, key).json()
    assert _publish_draft(admin, key).json()["code"] == "no_changes"
    changed = _spec(key, _stage("doc"), _stage("next", depends_on=["doc"]))
    assert _save(admin, changed, 1).json()["revision"] == 2
    assert _publish_draft(admin, key, 1).json()["code"] == "draft_conflict"
    second = _publish_draft(admin, key, 2).json()
    assert second["version"] == 2 and second["sha256"] != first["sha256"]
    detail = admin.client.get(_url(admin, f"/workflows/{key}")).json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert len(detail["versions"][1]["spec"]["stages"]) == 1
    wrong = admin.client.put(_url(admin, f"/workflows/{_key()}/draft"), headers=admin.h, json={"spec": _spec(key)})
    assert wrong.json()["code"] == "key_mismatch"
    bad = admin.client.put(_url(admin, "/workflows/Bad%20Key/draft"), headers=admin.h,
                           json={"spec": _spec("Bad Key")})
    assert bad.json()["code"] == "invalid_key"
    huge = _spec(key, _stage(name="x" * 300_000))
    assert _save(admin, huge, 2).status_code == 413


@pytest.mark.parametrize("fmt", ["json", "yaml"])
def test_export_and_import_round_trip_to_a_draft(admin, fmt):
    key = _key()
    _save(admin, _spec(key, _stage(approval_policy={"type": "any_of", "roles": ["project_owner", "viewer"]})))
    assert _publish_draft(admin, key).status_code == 201
    exported = admin.client.get(_url(admin, f"/workflows/{key}/export"), params={"format": fmt, "version": 1}).json()
    assert exported["filename"] == f"{key}.{fmt}"
    data = yaml.safe_load(exported["content"])
    assert data["stages"][0]["approval_policy"]["type"] == "any_of"
    new_key = _key()
    content = exported["content"].replace(key, new_key)
    r = admin.client.post(_url(admin, "/import"), headers=admin.h, json={"format": fmt, "content": content})
    assert r.status_code == 201 and r.json()["problems"] == [] and r.json()["draft"]["revision"] == 1
    assert admin.client.get(_url(admin, f"/workflows/{new_key}")).json()["versions"] == []  # nothing published
    assert admin.client.get(_url(admin, f"/workflows/{key}/export"), params={"version": 9}).status_code == 404


def test_imports_report_problems_and_refuse_unsafe_content(admin):
    key = _key()
    r = admin.client.post(_url(admin, "/import"), headers=admin.h,
                          json={"format": "yaml", "content": yaml.safe_dump(_spec(key, _stage(work="nope")))})
    assert r.status_code == 201 and "unknown work function" in r.json()["problems"][0]
    assert _publish_draft(admin, key).status_code == 422
    existing = admin.client.post(_url(admin, "/import"), headers=admin.h,
                                 json={"format": "json", "content": json.dumps(_spec(key))})
    assert existing.json()["code"] == "draft_conflict"
    for fmt, content in [
        ("yaml", f"key: {_key()}\nname: x\nstages: !!python/object/apply:os.system ['echo hi']\n"),
        ("yaml", f"key: {_key()}\nbase: &a [1]\nstages: *a\n"),
        ("yaml", f"key: {_key()}\nwhen: 2026-01-01\n"),
        ("yaml", "key: [unclosed"),
        ("yaml", "- just\n- a list\n"),
        ("json", "{not json"),
        ("json", "[1, 2]"),
        ("json", '{"name": "no key"}'),
    ]:
        r = admin.client.post(_url(admin, "/import"), headers=admin.h, json={"format": fmt, "content": content})
        assert r.status_code == 422 and r.json()["code"] == "invalid_import", content


def test_catalog_offers_only_what_the_platform_supports(admin):
    _agents(admin)
    data = admin.client.get(_url(admin, "/catalog")).json()
    assert {"key": "intake_summary", "ai": False} in data["work"]
    assert "drafting" in data["model_routes"] and data["profiles"][0]["key"] == "business_analyst"
    tools = {t["key"]: t for t in data["tools"]}
    assert tools["read_project"]["grantable"] and not tools["publish_release"]["grantable"]
    assert len(data["sensors"]) == 17 and "properties" in data["sensors"][0]["config_schema"]
    assert "api_key" not in json.dumps(data).lower()
