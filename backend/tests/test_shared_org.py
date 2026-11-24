"""One shared organization: the first account administers it and everyone else waits for confirmation."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.bootstrap import prepare_shared_org, seed_lifecycle
from app.main import create_app
from app.organizations.models import Organization
from app.providers.models import AiProvider, ModelRoute
from tests.helpers import PASSWORD, verify_token_from


def _email() -> str:
    return f"s-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture
def shared(settings, engine):
    with engine.begin() as conn:
        conn.execute(text("update organizations set is_default = false"))
    config = settings.model_copy(update={"signup_mode": "shared", "default_llm_base_url": "http://localhost:11434/v1",
                                         "default_llm_model": "local-model"})
    application = create_app(config)
    with Session(engine) as db:
        seed_lifecycle(db)
    with TestClient(application):
        yield application, config
    application.state.engine.dispose()
    with engine.begin() as conn:
        conn.execute(text("update organizations set is_default = false"))


def _join(application, engine, role="project_owner"):
    client = TestClient(application)
    email = _email()
    assert client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Person",
                                                    "requested_role": role}).status_code == 202
    assert client.post("/api/v1/auth/verify-email", json={"token": verify_token_from(engine, email)}).status_code == 200
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return client, {"X-CSRF-Token": login.json()["csrf_token"]}, login.json()["user"]["id"]


def test_first_account_administers_and_the_platform_is_ready(shared, engine):
    application, _ = shared
    admin, _, _ = _join(application, engine)
    access = admin.get("/api/v1/orgs/access").json()
    assert access["status"] == "active" and access["is_admin"] and access["can_create_projects"]
    org = admin.get("/api/v1/orgs").json()["items"][0]["id"]
    catalog = admin.get(f"/api/v1/orgs/{org}/studio/catalog").json()
    assert catalog["model_routes"] == ["default"] and len(catalog["profiles"]) == 7
    with Session(engine) as db:
        assert db.execute(select(AiProvider.name).where(AiProvider.organization_id == uuid.UUID(org))).scalar_one() \
            == "Local AI"
        assert db.execute(select(ModelRoute.primary_model).where(
            ModelRoute.organization_id == uuid.UUID(org))).scalar_one() == "local-model"


def test_later_accounts_wait_and_cannot_grant_themselves_anything(shared, engine):
    application, _ = shared
    admin, ah, _ = _join(application, engine)
    org = admin.get("/api/v1/orgs").json()["items"][0]["id"]
    person, h, user_id = _join(application, engine, "business_analyst")
    access = person.get("/api/v1/orgs/access").json()
    assert access["status"] == "pending" and access["requested_role"] == "business_analyst"
    assert not access["profiles"] and not access["can_create_projects"]
    assert person.get("/api/v1/orgs").json()["items"] == []
    assert person.post(f"/api/v1/orgs/{org}/projects", headers=h, json={
        "name": "P", "description": "", "project_type": "API"}).status_code == 404
    assert person.put(f"/api/v1/orgs/{org}/members/{user_id}/access", headers=h,
                      json={"role": "org_admin", "profiles": ["business_analyst"]}).status_code == 404
    listed = {m["user_id"]: m for m in admin.get(f"/api/v1/orgs/{org}/members").json()["members"]}
    assert listed[user_id]["status"] == "pending" and listed[user_id]["requested_role"] == "business_analyst"

    project = admin.post(f"/api/v1/orgs/{org}/projects", headers=ah, json={
        "name": "Existing", "description": "", "project_type": "API"}).json()["id"]
    assert admin.put(f"/api/v1/orgs/{org}/members/{user_id}/access", headers=ah,
                     json={"role": "member", "profiles": ["not_real"]}).json()["code"] == "unknown_profile"
    assert admin.put(f"/api/v1/orgs/{org}/members/{user_id}/access", headers=ah,
                     json={"role": "member", "profiles": ["business_analyst"]}).status_code == 200
    access = person.get("/api/v1/orgs/access").json()
    assert access["status"] == "active" and access["profiles"] == ["business_analyst"]
    assert person.get(f"/api/v1/projects/{project}").status_code == 200  # placed on existing projects
    assert person.post(f"/api/v1/orgs/{org}/projects", headers=h, json={
        "name": "P", "description": "", "project_type": "API"}).status_code == 403  # not a project owner
    newer = admin.post(f"/api/v1/orgs/{org}/projects", headers=ah, json={
        "name": "Newer", "description": "", "project_type": "API"}).json()["id"]
    assert person.get(f"/api/v1/projects/{newer}").status_code == 200  # and on new ones

    admin_id = admin.get("/api/v1/auth/me").json()["user"]["id"]
    assert admin.put(f"/api/v1/orgs/{org}/members/{admin_id}/access", headers=ah,
                     json={"role": "org_admin", "profiles": ["business_analyst"]}).json()[
        "code"] == "cannot_change_own_role"
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from audit_events where event_type = 'member.access_confirmed' "
                                 "and organization_id = :o"), {"o": uuid.UUID(org)}).scalar() == 1


def test_a_project_owner_can_create_projects_after_confirmation(shared, engine):
    application, _ = shared
    admin, ah, _ = _join(application, engine)
    org = admin.get("/api/v1/orgs").json()["items"][0]["id"]
    owner, h, user_id = _join(application, engine)
    admin.put(f"/api/v1/orgs/{org}/members/{user_id}/access", headers=ah, json={"role": "project_owner", "profiles": []})
    created = owner.post(f"/api/v1/orgs/{org}/projects", headers=h, json={
        "name": "Mine", "description": "", "project_type": "API"})
    assert created.status_code == 201
    assert owner.get(f"/api/v1/orgs/{org}/members").status_code == 403


def test_an_existing_account_can_be_made_the_administrator_at_startup(shared, engine):
    _, config = shared
    with engine.begin() as conn:
        org_id, user_id, email = uuid.uuid4(), uuid.uuid4(), _email()
        conn.execute(text("insert into organizations (id, name, slug, status) values (:o, 'Mine', :s, 'active')"),
                     {"o": org_id, "s": f"mine-{org_id.hex[:8]}"})
        conn.execute(text("insert into users (id, email, password_hash, display_name, status, failed_login_count) "
                          "values (:u, :e, 'x', 'Me', 'active', 0)"), {"u": user_id, "e": email})
        conn.execute(text("insert into memberships (id, organization_id, user_id, role) values (:i, :o, :u, "
                          "'org_admin')"), {"i": uuid.uuid4(), "o": org_id, "u": user_id})
    with Session(engine) as db:
        prepare_shared_org(db, config.model_copy(update={"bootstrap_admin_email": email}))
        assert db.get(Organization, org_id).is_default
        assert db.execute(select(ModelRoute.key).where(ModelRoute.organization_id == org_id)).scalar_one() == "default"
        prepare_shared_org(db, config.model_copy(update={"bootstrap_admin_email": email}))  # safe to repeat
        assert db.get(User, user_id).status == "active"
