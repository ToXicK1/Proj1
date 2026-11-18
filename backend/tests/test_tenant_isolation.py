"""Tenant and project isolation. Every cross-tenant attempt must look like a missing resource."""

import uuid

from sqlalchemy.orm import Session

from app.audit.service import org_chain, verify_chain
from tests.helpers import signup_verify_login


def _orgs(client) -> list[dict]:
    return client.get("/api/v1/orgs").json()["items"]


def _create_project(client, csrf: str, org_id: str, name: str = "Recruitment platform") -> dict:
    return client.post(
        f"/api/v1/orgs/{org_id}/projects",
        json={"name": name, "description": "Candidates and job descriptions", "project_type": "SaaS Platform"},
        headers={"X-CSRF-Token": csrf},
    )


def test_projects_require_authentication(client):
    assert client.get("/api/v1/projects").status_code == 401


def test_owner_creates_project_and_is_its_project_owner(client, engine):
    csrf = signup_verify_login(client, engine, "owner@example.com")
    org_id = _orgs(client)[0]["id"]
    r = _create_project(client, csrf, org_id)
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["organization_id"] == org_id and project["status"] == "active"
    listed = client.get("/api/v1/projects").json()["items"]
    assert [p["id"] for p in listed] == [project["id"]]


def test_other_user_cannot_see_or_open_project(client, engine):
    from fastapi.testclient import TestClient

    csrf_a = signup_verify_login(client, engine, "alice@example.com")
    project = _create_project(client, csrf_a, _orgs(client)[0]["id"]).json()

    with TestClient(client.app) as other:
        csrf_b = signup_verify_login(other, engine, "bob@example.com", name="Bob")
        assert other.get("/api/v1/projects").json()["items"] == []
        forbidden = other.get(f"/api/v1/projects/{project['id']}")
        missing = other.get(f"/api/v1/projects/{uuid.uuid4()}")
        # Same status and body whether the project exists or not: no existence oracle.
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json()["title"] == missing.json()["title"]
        # Bob cannot create a project inside Alice's organization either.
        r = _create_project(other, csrf_b, project["organization_id"])
        assert r.status_code == 404


def test_create_project_requires_csrf(client, engine):
    signup_verify_login(client, engine, "csrf@example.com")
    org_id = _orgs(client)[0]["id"]
    r = client.post(
        f"/api/v1/orgs/{org_id}/projects",
        json={"name": "No token", "description": "", "project_type": "Custom Project"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_failed"


def test_cross_site_post_without_session_cannot_create(client, engine):
    """A forged request from another site has no cookie and no CSRF token."""
    csrf = signup_verify_login(client, engine, "victim@example.com")
    org_id = _orgs(client)[0]["id"]
    client.cookies.clear()
    r = _create_project(client, csrf, org_id)
    assert r.status_code == 401


def test_project_validation(client, engine):
    csrf = signup_verify_login(client, engine, "val@example.com")
    org_id = _orgs(client)[0]["id"]
    empty = client.post(
        f"/api/v1/orgs/{org_id}/projects",
        json={"name": "   ", "description": "", "project_type": "Web Application"},
        headers={"X-CSRF-Token": csrf},
    )
    assert empty.status_code == 422
    extra = client.post(
        f"/api/v1/orgs/{org_id}/projects",
        json={"name": "x", "description": "", "project_type": "Web Application", "owner_id": "someone"},
        headers={"X-CSRF-Token": csrf},
    )
    assert extra.status_code == 422


def test_project_creation_is_in_tamper_evident_audit(client, engine):
    csrf = signup_verify_login(client, engine, "audit@example.com")
    org_id = _orgs(client)[0]["id"]
    project = _create_project(client, csrf, org_id).json()
    with Session(engine) as s:
        assert verify_chain(s, org_chain(uuid.UUID(org_id))) == []
    with engine.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(
            text("select event_type, project_id::text from audit_events where event_type = 'project.created'")
        ).one()
    assert row[0] == "project.created" and row[1] == project["id"]


def test_organization_list_is_scoped_to_caller(client, engine):
    from fastapi.testclient import TestClient

    signup_verify_login(client, engine, "org1@example.com", name="Org One")
    org_one = _orgs(client)[0]["id"]
    with TestClient(client.app) as other:
        signup_verify_login(other, engine, "org2@example.com", name="Org Two")
        assert [o["id"] for o in _orgs(other)] != [org_one]
        assert org_one not in [o["id"] for o in _orgs(other)]
