"""P1 (RD-20): the Project Manager is the seventh professional profile, assigned per project, and coordinates
without overriding the departments."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import service as agents
from app.auth.models import User
from app.portal.lifecycle import TEAM
from tests.test_accounts import NEW, _first_admin, _login, _person, managed  # noqa: F401  (fixture)

BA = "business_analyst"


def _profiles(engine, org):
    """The departments an organization has once its team is set up (the AI connection does this in production)."""
    with Session(engine) as db:
        admin = db.execute(select(User).where(User.email == "root@example.com")).scalar_one()
        for member in TEAM[1:]:  # the PM profile is created with the first PM account
            agents.create_profile(db, admin, organization_id=uuid.UUID(org), key=member.profile, name=member.title)


def _signed_in(app, made):
    c, r = _login(app, made["user"]["email"], made["temporary_password"])
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    assert c.post("/api/v1/auth/password", headers=h, json={"current_password": made["temporary_password"],
                                                            "new_password": NEW}).status_code == 200
    return c, h


def _setup(managed, engine):  # noqa: F811
    c, h, org, _ = _first_admin(managed, engine)
    _profiles(engine, org)
    client = _person(c, h, org, "olu@example.com", "project_owner")
    pm = _person(c, h, org, "pam@example.com", "project_manager")
    other_pm = _person(c, h, org, "pete@example.com", "project_manager")
    analyst = _person(c, h, org, "bea@example.com", "member", [BA])
    project = c.post(f"/api/v1/orgs/{org}/projects", headers=h, json={
        "name": "Clinic booking", "description": "", "project_type": "Web Application",
        "owner_user_id": client["user"]["id"], "delivery_scope": "ba-department"}).json()["id"]
    return c, h, org, project, {"client": client, "pm": pm, "other_pm": other_pm, "analyst": analyst}


def test_the_pm_is_the_seventh_profile_and_is_assigned_per_project(managed, engine):  # noqa: F811
    c, h, org, project, people = _setup(managed, engine)
    assert TEAM[0].profile == "project_manager" and len(TEAM) == 7
    members = {m["email"]: m for m in c.get(f"/api/v1/orgs/{org}/members").json()["members"]}
    assert "project_manager" in members["pam@example.com"]["profiles"]  # a PM account holds the PM profile

    team = c.get(f"/api/v1/projects/{project}/work/team").json()["departments"]
    assert team[0]["profile"] == "project_manager" and len(team) == 7
    assert team[0]["people"] == []  # no PM until an administrator assigns one

    refused = c.put(f"/api/v1/projects/{project}/manager", headers=h, json={"user_id": people["analyst"]["user"]["id"]})
    assert refused.status_code == 422  # only someone holding the PM profile
    ok = c.put(f"/api/v1/projects/{project}/manager", headers=h, json={"user_id": people["pm"]["user"]["id"]})
    assert ok.status_code == 200
    team = c.get(f"/api/v1/projects/{project}/work/team").json()["departments"]
    assert team[0]["people"] == ["Pam"]  # exactly the assigned PM, not every PM in the organization

    pm, ph = _signed_in(managed, people["pm"])
    other, _ = _signed_in(managed, people["other_pm"])
    assert pm.put(f"/api/v1/projects/{project}/manager", headers=ph,
                  json={"user_id": people["pm"]["user"]["id"]}).status_code == 403  # administrators assign
    mine = pm.get(f"/api/v1/projects/{project}/work/team").json()["departments"][0]
    assert mine["can_edit"] is True
    theirs = other.get(f"/api/v1/projects/{project}/work/team").json()["departments"][0]
    assert theirs["can_edit"] is False and theirs["visible"] is True  # oversees, but is not this project's PM


def test_the_pm_coordinates_but_never_decides_for_a_department(managed, engine):  # noqa: F811
    c, h, org, project, people = _setup(managed, engine)
    c.put(f"/api/v1/projects/{project}/manager", headers=h, json={"user_id": people["pm"]["user"]["id"]})
    pm, ph = _signed_in(managed, people["pm"])
    analyst, ah = _signed_in(managed, people["analyst"])
    w = f"/api/v1/projects/{project}/work"
    req = {"kind": "requirement", "title": "Book a visit",
           "body": {"description": "Patients book online", "type": "functional"}}
    assert pm.post(f"{w}/{BA}/items", headers=ph, json=req).status_code == 403  # not the BA's work to write
    item = analyst.post(f"{w}/{BA}/items", headers=ah, json=req).json()
    assert pm.put(f"{w}/items/{item['id']}", headers=ph, json={"expected_version": 1,
                                                               "title": "Changed by the PM"}).status_code == 403
    package = analyst.post(f"{w}/{BA}/packages", headers=ah, json={"item_ids": [item["id"]]}).json()
    decided = pm.post(f"{w}/packages/{package['id']}/decision", headers=ph, json={"decision": "approve"})
    assert decided.status_code == 403  # the PM cannot approve the department's package
    assert pm.get(f"{w}/{BA}/items").status_code == 200  # but can follow the work
    assert pm.post(f"/api/v1/orgs/{org}/projects", headers=ph, json={
        "name": "x", "description": "", "project_type": "Web Application",
        "owner_user_id": people["client"]["user"]["id"]}).status_code == 403  # administrators create projects
    assert pm.post(f"/api/v1/orgs/{org}/people", headers=ph, json={
        "email": "z@example.com", "display_name": "Z", "role": "member"}).status_code == 403  # nor accounts
