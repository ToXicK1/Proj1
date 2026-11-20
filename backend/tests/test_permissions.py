"""One table of who may do what, checked through the API for every kind of person.

The server is the authority (never the frontend): each row is a real request with that person's session.
Outsiders get 404 rather than 403 so they cannot learn that a project exists.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.portal.lifecycle import BY_STAGE
from tests.helpers import signup_verify_login
from tests.test_collab import _overseer, _owner_only
from tests.test_portal import FIRST, Portal, _email, box  # noqa: F401  (fixture)

PEOPLE = ("owner", "admin", "manager", "approver", "other_professional", "member", "outsider")


@pytest.fixture
def team(client, engine, settings, box):  # noqa: F811
    env = Portal(client, engine, settings, _email())
    env.box = box
    env.setup_team()
    approver = env.holder(BY_STAGE[FIRST].profile)
    other_profile = "devops_release" if BY_STAGE[FIRST].profile != "devops_release" else "business_analyst"
    other = env.holder(other_profile)
    admin = _overseer(env, "org_admin")
    manager = _overseer(env, "project_manager")
    member = env.person()
    _owner_only(env)
    outsider = TestClient(client.app)
    outsider_csrf = signup_verify_login(outsider, engine, _email(), name="Outsider")
    env.start()
    env.people = {
        "owner": (env.client, env.h),
        "admin": admin[:2],
        "manager": manager[:2],
        "approver": approver,
        "other_professional": other,
        "member": member[:2],
        "outsider": (outsider, {"X-CSRF-Token": outsider_csrf}),
    }
    env.member_id = member[2]
    return env


def _status(team, who, method, path, body=None):
    client, headers = team.people[who]
    return client.request(method, path, headers=headers if method != "GET" else None, json=body).status_code


def _check(team, method, path, expected, body=None):
    got = {who: _status(team, who, method, path, body) for who in expected}
    assert got == expected


def test_reading_a_project(team):
    _check(team, "GET", team.base, {
        "owner": 200, "admin": 200, "manager": 200, "approver": 200, "other_professional": 200,
        "member": 404, "outsider": 404,
    })


def test_only_the_assigned_professional_approves(team):
    version = team.item(FIRST)["current_version_id"]

    def body():
        return {"version_id": version, "decision": "APPROVE", "comment": "", "idempotency_key": uuid.uuid4().hex}

    path = f"{team.base}/deliverables/{FIRST}/decision"
    denied = {"owner": 403, "admin": 403, "manager": 403, "other_professional": 403, "member": 404, "outsider": 404}
    for who, code in denied.items():
        assert _status(team, who, "POST", path, body()) == code, who
    assert team.step_status(FIRST) == "Awaiting Review"  # nobody above moved it
    assert _status(team, "approver", "POST", path, body()) == 200
    assert team.step_status(FIRST) == "Approved"
    with team.engine.connect() as conn:
        actors = conn.execute(text("select actor_type from stage_transitions st join stage_executions se "
                                   "on se.id = st.stage_execution_id where se.stage_key = :s and "
                                   "st.to_status = 'APPROVED'"), {"s": FIRST}).scalars().all()
    assert actors == ["human"]


def test_only_the_owner_steers_delivery(team):
    path = f"{team.base}/stages/{FIRST}/retry"
    _check(team, "POST", path, {"admin": 403, "manager": 403, "approver": 403, "other_professional": 403,
                                "member": 404, "outsider": 404})


def test_oversight_shows_this_project_only_to_its_administrators_and_project_managers(team):
    """Anyone who administers their own workspace has an oversight page, but only for their own organization."""
    seen = {}
    for who in PEOPLE:
        response = team.people[who][0].get("/api/v1/oversight")
        projects = [p["id"] for p in response.json()["projects"]] if response.status_code == 200 else []
        seen[who] = (response.status_code, team.project in projects)
    assert seen["owner"] == (403, False)
    assert seen["admin"] == (200, True) and seen["manager"] == (200, True)
    for who in ("approver", "other_professional", "member", "outsider"):
        assert seen[who][1] is False, who


def test_only_administrators_change_roles(team):
    path = f"/api/v1/orgs/{team.org}/members/{team.member_id}/access"
    body = {"role": "member", "profiles": ["qa_security"]}
    _check(team, "PUT", path, {"owner": 403, "manager": 403, "approver": 403, "other_professional": 403,
                               "member": 403, "outsider": 404}, body)
    assert _status(team, "admin", "PUT", path, body) == 200


def test_administrators_are_kept_out_of_team_chat_and_owners_too(team):
    channels = {who: team.people[who][0].get("/api/v1/team-chat/channels").json()["items"]
                for who in ("owner", "admin", "manager", "approver")}
    assert channels["owner"] == [] and channels["admin"] == []
    assert len(channels["manager"]) == 7
    assert [c["key"] for c in channels["approver"]] == ["general", BY_STAGE[FIRST].profile]


@pytest.mark.parametrize("who", PEOPLE)
def test_nobody_reads_the_job_queue_or_storage_records_through_the_api(team, who):
    client, _ = team.people[who]
    for path in ("/api/v1/jobs", "/api/v1/storage", f"/api/v1/orgs/{team.org}/jobs"):
        assert client.get(path).status_code == 404
