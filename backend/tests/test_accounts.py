"""P0 (RD-22): administrators create every account and project; a temporary password must be changed first."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.auth.models import User
from app.main import create_app
from app.organizations.people import create_first_admin

NEW = "a-brand-new-password-42"


@pytest.fixture
def managed(settings):
    application = create_app(settings.model_copy(update={"account_mode": "managed", "signup_mode": "shared"}))
    yield application
    application.state.engine.dispose()


def _login(app, email, password):
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    return c, r


def _first_admin(app, engine):
    with Session(engine) as db:
        temp = create_first_admin(db, app.state.settings, email="root@example.com", display_name="Root Admin",
                                  organization_name="Clinic Co")
    c, r = _login(app, "root@example.com", temp)
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    assert c.post("/api/v1/auth/password", headers=h, json={"current_password": temp,
                                                            "new_password": NEW}).status_code == 200
    org = c.get("/api/v1/orgs").json()["items"][0]["id"]
    return c, h, org, temp


def _person(c, h, org, email, role, profiles=()):
    r = c.post(f"/api/v1/orgs/{org}/people", headers=h, json={
        "email": email, "display_name": email.split("@")[0].title(), "role": role, "profiles": list(profiles)})
    assert r.status_code == 201, r.text
    return r.json()


def test_nothing_works_until_the_temporary_password_is_changed(managed, engine):
    with Session(engine) as db:
        temp = create_first_admin(db, managed.state.settings, email="root@example.com", display_name="Root",
                                  organization_name="Clinic Co")
    c, r = _login(managed, "root@example.com", temp)
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    assert c.get("/api/v1/auth/me").json()["user"]["must_change_password"] is True
    blocked = c.get("/api/v1/orgs")
    assert blocked.status_code == 403 and blocked.json()["code"] == "password_change_required"
    wrong = c.post("/api/v1/auth/password", headers=h, json={"current_password": "nope", "new_password": NEW})
    assert wrong.status_code == 403
    same = c.post("/api/v1/auth/password", headers=h, json={"current_password": temp, "new_password": temp})
    assert same.status_code == 422 and same.json()["code"] == "same_password"
    weak = c.post("/api/v1/auth/password", headers=h, json={"current_password": temp, "new_password": "short"})
    assert weak.status_code == 422
    ok = c.post("/api/v1/auth/password", headers=h, json={"current_password": temp, "new_password": NEW})
    assert ok.status_code == 200 and ok.json()["user"]["must_change_password"] is False
    assert c.get("/api/v1/orgs").status_code == 200  # this session carries on
    assert _login(managed, "root@example.com", temp)[1].status_code == 401  # the temporary one is gone


def test_an_administrator_creates_people_and_the_password_is_shown_once(managed, engine):
    c, h, org, _ = _first_admin(managed, engine)
    made = _person(c, h, org, "pam@example.com", "project_manager")
    temp = made["temporary_password"]
    assert len(temp) == 23 and temp.count("-") == 3
    listed = c.get(f"/api/v1/orgs/{org}/members").text
    assert temp not in listed
    with engine.connect() as conn:
        stored = conn.execute(text("select password_hash from users where email = 'pam@example.com'")).scalar_one()
        audit = " ".join(conn.execute(text("select payload::text from audit_events")).scalars())
    assert temp not in stored and temp not in audit
    assert "member.created" in " ".join(engine.connect().execute(text(
        "select event_type from audit_events")).scalars())
    _, r = _login(managed, "pam@example.com", temp)
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    assert _person(c, h, org, "pam2@example.com", "member")["user"]["email"] == "pam2@example.com"
    again = c.post(f"/api/v1/orgs/{org}/people", headers=h, json={
        "email": "PAM@example.com", "display_name": "Pam", "role": "member"})
    assert again.status_code == 409


def test_only_administrators_create_people_and_nobody_signs_up(managed, engine):
    c, h, org, _ = _first_admin(managed, engine)
    temp = _person(c, h, org, "pam@example.com", "project_manager")["temporary_password"]
    pm, r = _login(managed, "pam@example.com", temp)
    ph = {"X-CSRF-Token": r.json()["csrf_token"]}
    pm.post("/api/v1/auth/password", headers=ph, json={"current_password": temp, "new_password": NEW})
    refused = pm.post(f"/api/v1/orgs/{org}/people", headers=ph, json={
        "email": "x@example.com", "display_name": "X", "role": "member"})
    assert refused.status_code == 403
    anon = TestClient(managed)
    assert anon.get("/api/v1/auth/config").json() == {"account_mode": "managed"}
    signup = anon.post("/api/v1/auth/signup", json={"email": "self@example.com", "password": NEW,
                                                    "display_name": "Self"})
    assert signup.status_code == 403 and signup.json()["code"] == "signup_disabled"


def test_an_expired_temporary_password_is_refused(managed, engine):
    c, h, org, _ = _first_admin(managed, engine)
    temp = _person(c, h, org, "late@example.com", "member")["temporary_password"]
    with Session(engine) as db:
        db.execute(update(User).where(User.email == "late@example.com")
                   .values(temp_password_expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()
    _, r = _login(managed, "late@example.com", temp)
    assert r.status_code == 403 and r.json()["code"] == "temporary_password_expired"


def test_a_reset_ends_sessions_and_issues_a_new_temporary_password(managed, engine):
    c, h, org, _ = _first_admin(managed, engine)
    made = _person(c, h, org, "bea@example.com", "member")
    bea, r = _login(managed, "bea@example.com", made["temporary_password"])
    bh = {"X-CSRF-Token": r.json()["csrf_token"]}
    bea.post("/api/v1/auth/password", headers=bh, json={"current_password": made["temporary_password"],
                                                        "new_password": NEW})
    assert bea.get("/api/v1/orgs").status_code == 200
    reset = c.post(f"/api/v1/orgs/{org}/people/{made['user']['id']}/reset-password", headers=h)
    assert reset.status_code == 200
    assert bea.get("/api/v1/orgs").status_code == 401  # signed out everywhere
    assert _login(managed, "bea@example.com", NEW)[1].status_code == 401
    _, again = _login(managed, "bea@example.com", reset.json()["temporary_password"])
    assert again.json()["user"]["must_change_password"] is True
    own = c.post(f"/api/v1/orgs/{org}/people/{c.get('/api/v1/auth/me').json()['user']['id']}/reset-password",
                 headers=h)
    assert own.status_code == 403


def test_administrators_create_projects_for_a_client(managed, engine):
    c, h, org, _ = _first_admin(managed, engine)
    client_made = _person(c, h, org, "olu@example.com", "project_owner")
    pm_made = _person(c, h, org, "pam@example.com", "project_manager")
    body = {"name": "Clinic booking", "description": "", "project_type": "Web Application"}
    assert c.post(f"/api/v1/orgs/{org}/projects", headers=h, json=body).status_code == 422  # client required
    wrong = c.post(f"/api/v1/orgs/{org}/projects", headers=h, json={**body, "owner_user_id": pm_made["user"]["id"]})
    assert wrong.status_code == 422  # only a client can own a project
    unscoped = c.post(f"/api/v1/orgs/{org}/projects", headers=h,
                      json={**body, "owner_user_id": client_made["user"]["id"]})
    assert unscoped.status_code == 422 and unscoped.json()["code"] == "scope_required"  # decided at creation
    made = c.post(f"/api/v1/orgs/{org}/projects", headers=h, json={**body, "owner_user_id": client_made["user"]["id"],
                                                                   "delivery_scope": "ba-department"})
    assert made.status_code == 201, made.text
    assert made.json()["delivery_scope"] == "ba-department"
    with engine.connect() as conn:
        roles = dict(conn.execute(text("select u.email, m.project_role from project_members m join users u "
                                       "on u.id = m.user_id where m.project_id = :p"),
                                  {"p": uuid.UUID(made.json()["id"])}).all())
    assert roles["olu@example.com"] == "project_owner" and roles["root@example.com"] == "viewer"
    assert roles["pam@example.com"] == "viewer"  # managers oversee every project
    # The client and the PM cannot create projects themselves.
    for made_person in (client_made, pm_made):
        p, r = _login(managed, made_person["user"]["email"], made_person["temporary_password"])
        ph = {"X-CSRF-Token": r.json()["csrf_token"]}
        p.post("/api/v1/auth/password", headers=ph, json={"current_password": made_person["temporary_password"],
                                                          "new_password": NEW})
        assert p.post(f"/api/v1/orgs/{org}/projects", headers=ph, json=body).status_code == 403
    with Session(engine) as db:
        assert db.execute(select(User).where(User.email == "olu@example.com")).scalar_one().verified_at is not None
