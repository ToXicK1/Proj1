"""Invitations, organization membership and project roles."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.helpers import PASSWORD, latest_email, signup_verify_login, verify_token_from
from tests.test_approvals import _user_id
from tests.test_governance import Env, _evidence, _version_id
from tests.test_providers_run import _org_id


def _email() -> str:
    return f"m-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def admin(client, engine, settings, monkeypatch):
    from app.workflows.work import WORK_FUNCTIONS

    monkeypatch.setitem(WORK_FUNCTIONS, "intake_summary", lambda ctx: {"goal": "x"})
    return Env(client, engine, settings, _email())


def _invite(env, email, **body):
    return env.client.post(f"/api/v1/orgs/{env.org}/invitations", headers=env.h, json={"email": email, **body})


def _token(engine, email) -> str:
    return re.search(r"token=([A-Za-z0-9_\-]+)", latest_email(engine, "org_invitation", email)).group(1)


def _user(env, email):
    other = TestClient(env.client.app)
    csrf = signup_verify_login(other, env.engine, email, name="Invited")
    return other, {"X-CSRF-Token": csrf}, _user_id(env.engine, email)


def _accept(client, headers, token):
    return client.post("/api/v1/invitations/accept", headers=headers, json={"token": token})


def _project(env):
    return env.client.post(f"/api/v1/orgs/{env.org}/projects", headers=env.h,
                           json={"name": "Shared", "description": "", "project_type": "SaaS Platform"}).json()


def test_invited_person_joins_the_organization_and_project(admin):
    project = _project(admin)
    email = _email()
    created = _invite(admin, f"  {email.upper()} ", project_id=project["id"], project_role="team_member")
    assert created.status_code == 201 and created.json()["email"] == email
    token = _token(admin.engine, email)
    assert token not in str(created.json())
    with admin.engine.connect() as conn:
        assert token not in " ".join(str(v) for v in conn.execute(text("select * from organization_invitations")).one())
        assert email not in " ".join(conn.execute(text("select payload::text from audit_events")).scalars())

    preview = admin.client.post("/api/v1/invitations/preview", json={"token": token}).json()
    assert preview["project"] == "Shared" and preview["email_hint"] == f"{email[0]}***@example.com"

    other, h, user_id = _user(admin, email)
    assert other.get(f"/api/v1/projects/{project['id']}").status_code == 404
    assert _accept(other, h, token).status_code == 200
    assert other.get(f"/api/v1/projects/{project['id']}").status_code == 200
    assert admin.org in [o["id"] for o in other.get("/api/v1/orgs").json()["items"]]
    assert _accept(other, h, token).json()["code"] == "invalid_or_expired_invitation"
    people = {m["user_id"]: m["role"] for m in admin.client.get(f"/api/v1/orgs/{admin.org}/members").json()["members"]}
    assert people[str(user_id)] == "member"
    team = admin.client.get(f"/api/v1/projects/{project['id']}/members").json()["items"]
    assert {m["role"] for m in team} == {"project_owner", "team_member"}


def test_only_the_invited_account_can_accept(admin):
    email = _email()
    _invite(admin, email)
    other, h, _ = _user(admin, _email())
    r = _accept(other, h, _token(admin.engine, email))
    assert r.status_code == 403 and r.json()["code"] == "invitation_wrong_account"
    assert admin.org not in [o["id"] for o in other.get("/api/v1/orgs").json()["items"]]
    assert other.post("/api/v1/invitations/accept", json={"token": _token(admin.engine, email)}).status_code == 403


def test_accepting_needs_a_verified_signed_in_account(admin):
    email = _email()
    _invite(admin, email)
    token = _token(admin.engine, email)
    anonymous = TestClient(admin.client.app)
    assert anonymous.post("/api/v1/invitations/accept", json={"token": token}).status_code == 401
    anonymous.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "New"})
    assert anonymous.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 403
    assert verify_token_from(admin.engine, email)


def test_revoked_expired_and_unknown_invitations_stop_working(admin):
    revoked, expired = _email(), _email()
    invitation = _invite(admin, revoked).json()
    assert admin.client.post(f"/api/v1/orgs/{admin.org}/invitations/{invitation['id']}/revoke",
                             headers=admin.h).status_code == 200
    assert admin.client.post("/api/v1/invitations/preview",
                             json={"token": _token(admin.engine, revoked)}).status_code == 400
    assert _invite(admin, revoked).status_code == 201  # a revoked address can be invited again
    _invite(admin, expired)
    with admin.engine.begin() as conn:
        conn.execute(text("update organization_invitations set expires_at = :t where email = :e"),
                     {"t": datetime.now(UTC) - timedelta(days=1), "e": expired})
    other, h, _ = _user(admin, expired)
    assert _accept(other, h, _token(admin.engine, expired)).status_code == 400
    assert _invite(admin, expired).status_code == 201  # an expired one does not block a new invitation
    assert admin.client.post("/api/v1/invitations/preview", json={"token": "x" * 40}).status_code == 400


def test_duplicate_invitations_and_existing_members_are_refused(admin):
    email = _email()
    assert _invite(admin, email).status_code == 201
    assert _invite(admin, email).json()["code"] == "invitation_pending"
    other, h, _ = _user(admin, email)
    _accept(other, h, _token(admin.engine, email))
    assert _invite(admin, email).json()["code"] == "already_member"


def test_only_org_admins_invite_and_manage(admin):
    project = _project(admin)
    member_email = _email()
    _invite(admin, member_email)
    member, h, member_id = _user(admin, member_email)
    _accept(member, h, _token(admin.engine, member_email))
    org = f"/api/v1/orgs/{admin.org}"
    assert member.post(f"{org}/invitations", headers=h, json={"email": _email()}).status_code == 403
    assert member.get(f"{org}/members").status_code == 403
    assert member.put(f"/api/v1/projects/{project['id']}/members/{member_id}", headers=h,
                      json={"role": "internal_reviewer"}).status_code == 403
    stranger, sh, _ = _user(admin, _email())
    assert stranger.post(f"{org}/invitations", headers=sh, json={"email": _email()}).status_code == 404
    assert stranger.get(f"/api/v1/projects/{project['id']}/members").status_code == 404
    assert admin.client.post(f"{org}/invitations", json={"email": _email()}).status_code == 403  # no CSRF token
    other_org = _org_id(stranger)
    assert _invite(admin, _email(), project_id=project["id"], project_role="bad").status_code == 422
    assert admin.client.post(f"/api/v1/orgs/{other_org}/invitations", headers=admin.h,
                             json={"email": _email()}).status_code == 404


def test_an_invitation_cannot_point_at_another_organizations_project(admin):
    stranger, sh, _ = _user(admin, _email())
    foreign = stranger.post(f"/api/v1/orgs/{_org_id(stranger)}/projects", headers=sh,
                            json={"name": "Theirs", "description": "", "project_type": "API"}).json()
    r = _invite(admin, _email(), project_id=foreign["id"], project_role="viewer")
    assert r.status_code == 404
    assert _invite(admin, _email(), project_id=foreign["id"]).status_code == 422


def _joined(env, role="member", **body):
    email = _email()
    _invite(env, email, role=role, **body)
    client, h, user_id = _user(env, email)
    assert _accept(client, h, _token(env.engine, email)).status_code == 200
    return client, h, user_id


def test_nobody_changes_their_own_access(admin):
    project = _project(admin)
    me = admin.owner
    r = admin.client.put(f"/api/v1/projects/{project['id']}/members/{me}", headers=admin.h,
                         json={"role": "internal_reviewer"})
    assert r.status_code == 403 and r.json()["code"] == "cannot_change_own_role"
    assert admin.client.put(f"/api/v1/orgs/{admin.org}/members/{me}", headers=admin.h,
                            json={"role": "member"}).json()["code"] == "cannot_change_own_role"
    assert admin.client.delete(f"/api/v1/orgs/{admin.org}/members/{me}", headers=admin.h).status_code == 403


def test_nobody_removes_themselves_from_a_project(admin):
    project = _project(admin)
    r = admin.client.delete(f"/api/v1/projects/{project['id']}/members/{admin.owner}", headers=admin.h)
    assert r.status_code == 403 and r.json()["code"] == "cannot_change_own_role"


def test_members_cannot_change_other_peoples_access(admin):
    project = _project(admin)
    member, h, _ = _joined(admin)
    _, _, colleague = _joined(admin, project_id=project["id"], project_role="viewer")
    url = f"/api/v1/projects/{project['id']}/members/{colleague}"
    for r in (member.put(url, headers=h, json={"role": "internal_reviewer"}), member.delete(url, headers=h)):
        assert r.status_code == 403 and r.json()["code"] != "cannot_change_own_role"
    team = {m["user_id"]: m["role"] for m in admin.client.get(f"/api/v1/projects/{project['id']}/members").json()["items"]}
    assert team[str(colleague)] == "viewer"


def test_only_this_organizations_admins_can_revoke(admin):
    email = _email()
    invitation = _invite(admin, email).json()["id"]
    member, h, _ = _joined(admin)
    assert member.post(f"/api/v1/orgs/{admin.org}/invitations/{invitation}/revoke", headers=h).status_code == 403
    stranger, sh, _ = _user(admin, _email())
    assert stranger.post(f"/api/v1/orgs/{_org_id(stranger)}/invitations/{invitation}/revoke",
                         headers=sh).status_code == 404
    assert admin.client.post("/api/v1/invitations/preview",
                             json={"token": _token(admin.engine, email)}).status_code == 200


def test_every_project_keeps_an_owner(admin):
    project = _project(admin)
    second_admin, h2, second_id = _joined(admin, role="org_admin")
    url = f"/api/v1/projects/{project['id']}/members/{admin.owner}"
    assert second_admin.delete(url, headers=h2).json()["code"] == "last_project_owner"
    assert second_admin.put(url, headers=h2, json={"role": "viewer"}).json()["code"] == "last_project_owner"
    assert second_admin.delete(f"/api/v1/orgs/{admin.org}/members/{admin.owner}",
                               headers=h2).json()["code"] == "last_project_owner"
    assert admin.client.get(f"/api/v1/projects/{project['id']}").status_code == 200
    assert admin.client.put(f"/api/v1/projects/{project['id']}/members/{second_id}", headers=admin.h,
                            json={"role": "project_owner"}).status_code == 200
    assert second_admin.put(url, headers=h2, json={"role": "viewer"}).status_code == 200


def test_removing_a_member_ends_their_project_access(admin):
    project = _project(admin)
    member, _, member_id = _joined(admin, project_id=project["id"], project_role="team_member")
    assert member.get(f"/api/v1/projects/{project['id']}").status_code == 200
    assert admin.client.delete(f"/api/v1/orgs/{admin.org}/members/{member_id}", headers=admin.h).status_code == 200
    assert member.get(f"/api/v1/projects/{project['id']}").status_code == 404
    assert admin.org not in [o["id"] for o in member.get("/api/v1/orgs").json()["items"]]


def test_project_roles_apply_only_to_organization_members(admin):
    project = _project(admin)
    _, _, stranger_id = _user(admin, _email())
    assert admin.client.put(f"/api/v1/projects/{project['id']}/members/{stranger_id}", headers=admin.h,
                            json={"role": "viewer"}).status_code == 404


def test_invitations_are_rate_limited_per_organization(admin):
    admin.client.app.state.invite_limiter._limit = 1
    assert _invite(admin, _email()).status_code == 201
    assert _invite(admin, _email()).status_code == 429


def test_an_invited_reviewer_can_clear_evidence_through_the_api(admin):
    execution, project = admin.flow({"key": "security_scan"})
    assert admin.run(execution)[0] == "BLOCKED"
    reviewer, h, _ = _joined(admin, project_id=str(project), project_role="internal_reviewer")
    version = _version_id(admin, execution)
    assert _evidence(admin.client, admin.h, execution, version, kind="security_scan").status_code == 403
    assert _evidence(reviewer, h, execution, version, kind="security_scan").status_code == 201
    assert admin.validate(execution).json()["status"] == "AWAITING_HUMAN_REVIEW"
    assert admin.decide(execution).json()["stage"]["status"] == "APPROVED"
