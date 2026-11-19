"""Generated code must really build and pass its tests before anyone can approve it."""

import io
import uuid
import zipfile

from sqlalchemy import text

from app.portal.lifecycle import STAGES, workflow_spec
from tests.test_portal import PROJECT, FakeSandbox, box, env  # noqa: F401  (fixtures)

BEFORE_CODE = [s for s in STAGES if s.in_scope("poc") and s.gated and s.id != "code_generation"][:3]
CODE, TESTS = "code_generation", "build_and_test"


def _reach_code(env):  # noqa: F811
    env.setup_team()
    person, h = env.holder()
    env.start()
    for stage in BEFORE_CODE:
        version = env.item(stage.id, person)["current_version_id"]
        assert env.decide(stage.id, version=version, client=person, headers=h).status_code == 200
    return person, h


def _evidence(env, source="sandbox"):  # noqa: F811
    with env.engine.connect() as conn:
        return conn.execute(text("select kind, outcome from sensor_evidence where project_id = :p and source = :s "
                                 "order by id"), {"p": uuid.UUID(env.project), "s": source}).all()


def test_passing_code_reaches_approval_with_real_results(env):  # noqa: F811
    person, h = _reach_code(env)
    assert env.step_status(CODE) == "Awaiting Review"
    assert env.box.jobs == [PROJECT]
    assert [tuple(r) for r in _evidence(env)] == [("build", "pass"), ("unit_tests", "pass")]
    item = env.item(CODE, person)
    assert item["versions"][0]["checks"] == [{"name": "Build", "passed": True, "summary": "Python files compile"},
                                             {"name": "Tests", "passed": True, "summary": "Tests: 1 passed"}]
    assert env.decide(CODE, version=item["current_version_id"], client=person, headers=h).status_code == 200
    assert env.step_status(TESTS) == "Awaiting Review"
    assert env.box.jobs == [PROJECT, PROJECT]  # the approved code is built and tested again at the next step


def test_failing_code_is_sent_back_with_the_real_failure_then_stops(env):  # noqa: F811
    env.box.results = [FakeSandbox.verdict(tests=False, output="assert 5 == 6") for _ in range(3)]
    person, h = _reach_code(env)
    assert env.step_status(CODE) == "Blocked" and len(env.box.jobs) == 3  # first try plus two automatic fixes
    assert "assert 5 == 6" in env.model.lead_requests()[-1]["user"]
    item = env.item(CODE, person)
    assert item["checks_blocking"] and not item["can_decide"] and len(item["versions"]) == 3
    r = env.decide(CODE, version=item["current_version_id"], client=person, headers=h)
    assert r.status_code == 409 and r.json()["title"] == "This deliverable is not waiting for a decision."


def test_a_fix_that_passes_continues_normally(env):  # noqa: F811
    env.box.results = [FakeSandbox.verdict(build=False, output="SyntaxError")]
    _reach_code(env)
    assert env.step_status(CODE) == "Awaiting Review" and len(env.box.jobs) == 2


def test_no_sandbox_means_no_approval_and_no_invented_result(env):  # noqa: F811
    env.box.down = True
    person, h = _reach_code(env)
    assert env.step_status(CODE) == "Blocked" and _evidence(env) == []
    assert len(env.model.lead_requests()) == 4  # no pointless regeneration when nothing was tested
    item = env.item(CODE, person)
    assert env.decide(CODE, version=item["current_version_id"], client=person, headers=h).status_code == 409
    env.box.down = False
    assert env.post(f"/stages/{CODE}/retry").status_code == 202
    assert env.step_status(CODE) == "Awaiting Review"


def test_nobody_can_overrule_a_sandbox_result_by_hand(env):  # noqa: F811
    env.box.results = [FakeSandbox.verdict(tests=False, output="boom") for _ in range(3)]
    person, h = _reach_code(env)
    version = env.item(CODE, person)["current_version_id"]
    with env.engine.connect() as conn:
        execution = conn.execute(text("select id from workflow_executions where project_id = :p"),
                                 {"p": uuid.UUID(env.project)}).scalar_one()
    url = f"/api/v1/workflow-executions/{execution}/stages/{CODE}/evidence"
    for kind in ("unit_tests", "build"):
        r = person.post(url, headers=h, json={"artifact_version_id": version, "kind": kind, "outcome": "pass",
                                              "summary": "Trust me"})
        assert r.status_code == 409 and r.json()["code"] == "sandbox_result"
    assert not _evidence(env, "human")


def test_owners_see_results_but_not_source_and_the_team_can_download_it(env):  # noqa: F811
    person, _ = _reach_code(env)
    with env.engine.begin() as conn:  # an owner who is not also an administrator
        conn.execute(text("update memberships set role = 'project_owner' where user_id = :u and organization_id = :o"),
                     {"u": env.owner, "o": uuid.UUID(env.org)})
    owner_view = env.item(CODE)
    assert owner_view["versions"][0]["content"]["source_files"] == "2 files generated"
    assert not owner_view["can_view_code"] and owner_view["versions"][0]["checks"][1]["passed"]
    version = owner_view["current_version_id"]
    assert env.client.get(f"{env.base}/versions/{version}/code.zip").status_code == 403
    assert env.item(CODE, person)["versions"][0]["content"]["source_files"] == PROJECT
    response = person.get(f"{env.base}/versions/{version}/code.zip")
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["calc.py", "test_calc.py"]
    other, _, _ = env.person()
    assert other.get(f"{env.base}/versions/{version}/code.zip").status_code == 404  # not on this project
    assert person.get(f"{env.base}/versions/{uuid.uuid4()}/code.zip").status_code == 404


def test_archives_leave_out_unsafe_paths(env):  # noqa: F811
    env.model.extra = {"source_files": [{"path": "../../evil.py", "content": "x"}, PROJECT[0]]}
    person, _ = _reach_code(env)
    version = env.item(CODE, person)["current_version_id"]
    with zipfile.ZipFile(io.BytesIO(person.get(f"{env.base}/versions/{version}/code.zip").content)) as archive:
        assert archive.namelist() == ["calc.py"]


def test_profiles_only_count_inside_their_own_organization(env):  # noqa: F811
    env.setup_team()
    env.start()
    person, h, user_id = env.person()
    with env.engine.begin() as conn:
        other_org = conn.execute(text("select organization_id from memberships where user_id = :u and "
                                      "role = 'org_admin'"), {"u": user_id}).scalar_one()
        conn.execute(text("insert into member_profiles (id, organization_id, user_id, profile_key, confirmed_by) "
                          "values (:i, :o, :u, 'business_analyst', :u)"),
                     {"i": uuid.uuid4(), "o": other_org, "u": user_id})
    from tests.test_approvals import _add_member

    _add_member(env.engine, uuid.UUID(env.project), user_id, "team_member")
    assert env.get("/deliverables", person)["items"] == []  # a profile from another organization grants nothing here
    r = env.decide("intent_capture", version=env.item("intent_capture")["current_version_id"], client=person, headers=h)
    assert r.status_code == 403


def test_workflows_send_code_to_the_sandbox():
    spec = {s["id"]: s for s in workflow_spec("feature")["stages"]}
    assert spec[CODE]["sandbox"] and spec[TESTS]["sandbox_source"] == CODE
    for key in (CODE, TESTS):
        assert {"code_builds", "unit_tests"} <= {s["key"] for s in spec[key]["sensors"] if s["mandatory"]}
