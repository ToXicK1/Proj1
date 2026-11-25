"""P4: the Project Brief is assembled by the platform from the validated intake and the confirmed meetings, approved
by the PM, and handed to the BA department, which starts the lifecycle with the brief as its project input. The
client's form no longer starts anything (D3)."""

import uuid

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents import service as agents
from app.auth.models import User
from app.bootstrap import seed_lifecycle
from app.portal.lifecycle import PM_ASSISTANT, PM_PERSONA
from tests.test_meetings import INTAKE, MEETING, managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _setup, _signed_in
from tests.test_pm_analysis import Model


def _ready(managed, engine):  # noqa: F811
    c, h, org, project, people = _setup(managed, engine)
    model = Model({})
    managed.state.provider_transport = httpx.MockTransport(model.handler)
    provider = c.post(f"/api/v1/orgs/{org}/providers", headers=h, json={
        "name": "local", "adapter_type": "openai_compatible", "base_url": "http://localhost:11434/v1"}).json()
    c.post(f"/api/v1/orgs/{org}/model-routes", headers=h, json={
        "key": "default", "primary_provider_id": provider["id"], "primary_model": "qwen-test", "fallbacks": []})
    assert c.post(f"/api/v1/orgs/{org}/studio/default-lifecycle", headers=h,
                  json={"model_route": "default"}).status_code == 201
    with Session(engine) as db:
        seed_lifecycle(db)
        db.commit()
    with Session(engine) as db:
        if agents.latest(db, uuid.UUID(org), PM_ASSISTANT) is None:  # pragma: no cover (provisioning adds it)
            admin = db.execute(text("select id from users where email = 'root@example.com'")).scalar_one()
            agents.create_agent(db, db.get(User, admin), organization_id=uuid.UUID(org),
                                profile_key="project_manager", key=PM_ASSISTANT, kind="lead",
                                instructions=PM_PERSONA, required_keys=["answer"], model_route="default",
                                context_sources=["project_input"], tools=[])
    c.put(f"/api/v1/projects/{project}/manager", headers=h, json={"user_id": people["pm"]["user"]["id"]})
    pm, ph = _signed_in(managed, people["pm"])
    w = f"/api/v1/projects/{project}/work"
    pm.post(f"{w}/project_manager/items", headers=ph, json={"kind": "meeting", "title": "Discovery with Olu",
                                                            "body": MEETING})
    return c, h, pm, ph, w, project, people, model


def _kickoff(pm, ph, w):
    """The PM holds the kickoff (once); its checklist passes because the BA is assigned."""
    if pm.get(f"{w}/kickoff").json()["kickoff"] is None:
        r = pm.post(f"{w}/kickoff", headers=ph, json={"held_at": "2026-11-25 10:00", "attendees": ["Olu", "Pam"]})
        assert r.status_code == 201, r.text


def _client_approves(managed, people, project, package_id):  # noqa: F811
    client, ch = _signed_in(managed, people["client"])
    r = client.post(f"/api/v1/portal/projects/{project}/project-brief/decision", headers=ch,
                    json={"package_id": package_id, "decision": "approve"})
    assert r.status_code == 200, r.text
    return client, ch


def _validate(pm, ph, w):
    _kickoff(pm, ph, w)
    intake = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "project_intake", "title": "Clinic booking intake", "body": INTAKE}).json()
    r = pm.put(f"{w}/items/{intake['id']}", headers=ph, json={
        "expected_version": 1, "provenance": "confirmed", "body": {**INTAKE, "validation": "validated"}})
    assert r.status_code == 200, r.text
    return intake


def _approved_brief(pm, ph, w):
    brief = pm.post(f"{w}/brief/assemble", headers=ph).json()["item"]
    confirmed = pm.put(f"{w}/items/{brief['id']}", headers=ph, json={"expected_version": brief["version"],
                                                                     "provenance": "confirmed"})
    assert confirmed.status_code == 200, confirmed.text
    package = pm.post(f"{w}/project_manager/packages", headers=ph, json={
        "title": "Project brief", "item_ids": [brief["id"]]}).json()
    decided = pm.post(f"{w}/packages/{package['id']}/decision", headers=ph, json={"decision": "approve"})
    assert decided.status_code == 200, decided.text  # confirmed as assembled: the PM approves alone
    return brief, package


def test_the_brief_is_assembled_from_the_validated_intake_and_cites_its_sources(managed, engine):  # noqa: F811
    _, _, pm, ph, w, _, _, _ = _ready(managed, engine)
    assert pm.post(f"{w}/brief/assemble", headers=ph).json()["code"] == "kickoff_required"
    _kickoff(pm, ph, w)
    assert pm.post(f"{w}/brief/assemble", headers=ph).json()["code"] == "intake_not_validated"
    _validate(pm, ph, w)
    out = pm.post(f"{w}/brief/assemble", headers=ph).json()
    brief = out["item"]
    assert brief["key"] == "PB-001" and brief["provenance"] == "system_draft" and not out["kept_pm_edits"]
    sections = {s["heading"]: s["content"] for s in brief["body"]["sections"]}
    assert sections["1. Business problem"] == "Patients can only book by phone (INT-001 v2)"
    assert "- Start with online booking (MTG-001 v1)" in sections["9. Decisions"]  # the meeting's decision, cited
    assert "Which clinics first? (MTG-001 v1)" in sections["12. Open questions"]
    detail = pm.get(f"{w}/items/{brief['id']}").json()
    assert {lk["item"]["key"] for lk in detail["links"]} == {"INT-001", "MTG-001"}
    assert detail["versions"][-1]["author_type"] == "system"  # the platform, not the AI

    again = pm.post(f"{w}/brief/assemble", headers=ph).json()["item"]
    assert again["version"] == brief["version"]  # nothing changed, no new version
    edited = pm.put(f"{w}/items/{brief['id']}", headers=ph, json={
        "expected_version": brief["version"], "body": {"sections": [{"heading": "Mine", "content": "My words"}]}})
    assert edited.status_code == 200
    kept = pm.post(f"{w}/brief/assemble", headers=ph).json()
    assert kept["kept_pm_edits"] and kept["item"]["body"]["sections"][0]["heading"] == "Mine"  # never overwritten
    hand = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "project_brief", "title": "My brief", "body": {"sections": []}})
    assert hand.status_code == 422  # only the platform assembles a brief


def test_only_an_approved_brief_starts_delivery_and_the_ba_works_from_it(managed, engine):  # noqa: F811
    _, _, pm, ph, w, project, people, model = _ready(managed, engine)
    _validate(pm, ph, w)
    brief = pm.post(f"{w}/brief/assemble", headers=ph).json()["item"]
    pm.put(f"{w}/items/{brief['id']}", headers=ph, json={"expected_version": brief["version"],
                                                         "provenance": "confirmed"})
    package = pm.post(f"{w}/project_manager/packages", headers=ph, json={
        "title": "Project brief", "item_ids": [brief["id"]]}).json()
    early = pm.post(f"{w}/brief/start", headers=ph, json={"package_id": package["id"]})
    assert early.status_code == 409 and early.json()["code"] == "brief_not_approved"
    pm.post(f"{w}/packages/{package['id']}/decision", headers=ph, json={"decision": "approve"})
    waiting = pm.post(f"{w}/brief/start", headers=ph, json={"package_id": package["id"]})
    assert waiting.status_code == 409 and waiting.json()["code"] == "client_approval_required"
    _client_approves(managed, people, project, package["id"])

    other, oh = _signed_in(managed, people["other_pm"])
    assert other.post(f"{w}/brief/start", headers=oh, json={
        "package_id": package["id"]}).status_code == 403  # not this project's PM
    status = pm.get(f"{w}/brief").json()
    assert status["approved_packages"][0]["brief"]["key"] == "PB-001" and not status["started"]
    assert status["approved_packages"][0]["client_status"] == "approved"

    r = pm.post(f"{w}/brief/start", headers=ph, json={"package_id": package["id"]})
    assert r.status_code == 202, r.text
    assert r.json()["handoff"]["to"] == "business_analyst"
    assert pm.post(f"{w}/brief/start", headers=ph, json={
        "package_id": package["id"]}).json()["code"] == "already_started"
    assert pm.post(f"{w}/brief/assemble", headers=ph).json()["code"] == "already_started"
    with engine.connect() as conn:
        snapshot, created_by = conn.execute(text(
            "select config_snapshot, created_by from workflow_executions where project_id = :p"), {"p": project}).one()
        events = set(conn.execute(text("select event_type from audit_events")).scalars())
    assert snapshot["facts"]["brief"]["version_id"] == package["items"][0]["version_id"]  # the exact version
    assert snapshot["facts"]["client_approvals"] is True  # D1: the client signs off chosen steps (P5)
    assert "Business problem: Patients can only book by phone (INT-001 v2)" in snapshot["intake"]
    assert snapshot["facts"]["scope"] == "ba-department"  # the project's kind of work, chosen at creation
    assert str(created_by) == people["pm"]["user"]["id"]
    assert {"work.brief_handed_off", "work.delivery_started_from_brief"} <= events
    first = next(b for b in model.sent if "<project_input>" in b["messages"][-1]["content"])
    assert "Patients can only book by phone (INT-001 v2)" in first["messages"][-1]["content"]  # the BA's AI step

    analyst, ah = _signed_in(managed, people["analyst"])
    handoff = analyst.get(f"{w}/business_analyst/handoffs").json()["items"][0]
    asked = analyst.post(f"{w}/handoffs/{handoff['id']}/reply", headers=ah, json={
        "action": "request_clarification", "reply": "Which clinics take part first?"})
    assert asked.status_code == 200
    notes = pm.get("/api/v1/notifications").json()["items"]
    assert any(n["kind"] == "handoff_clarification" for n in notes)  # the PM is asked


def test_a_brief_with_the_pms_own_edits_needs_a_second_pm(managed, engine):  # noqa: F811
    _, _, pm, ph, w, _, _, _ = _ready(managed, engine)
    _validate(pm, ph, w)
    brief = pm.post(f"{w}/brief/assemble", headers=ph).json()["item"]
    pm.put(f"{w}/items/{brief['id']}", headers=ph, json={
        "expected_version": brief["version"], "body": {"sections": [{"heading": "Scope", "content": "Booking"}]}})
    package = pm.post(f"{w}/project_manager/packages", headers=ph, json={
        "title": "Project brief", "item_ids": [brief["id"]]}).json()
    r = pm.post(f"{w}/packages/{package['id']}/decision", headers=ph, json={"decision": "approve"})
    assert r.status_code == 403 and r.json()["code"] == "separation_of_duties"  # RD-19


def test_the_clients_form_goes_to_the_pm_and_never_starts_delivery(managed, engine):  # noqa: F811
    _, _, pm, _, _, project, people, _ = _ready(managed, engine)
    client, ch = _signed_in(managed, people["client"])
    form = client.get(f"/api/v1/portal/projects/{project}/intake").json()
    field = form["questions"][0]["field"]
    client.post(f"/api/v1/portal/projects/{project}/intake/answers", headers=ch,
                json={"field": field, "kind": "answer", "answer": "Online booking for a clinic"})
    form = client.get(f"/api/v1/portal/projects/{project}/intake").json()
    assert form["pm_led"] and form["can_send"]
    refused = client.post(f"/api/v1/portal/projects/{project}/intake/confirm", headers=ch,
                          json={"revision": form["revision"]})
    assert refused.status_code == 409 and refused.json()["code"] == "pm_led"
    sent = client.post(f"/api/v1/portal/projects/{project}/intake/send", headers=ch,
                       json={"revision": form["revision"]}).json()
    assert sent["sent_to_pm"] and not sent["can_send"]
    assert any(n["kind"].startswith("client_form_sent") for n in pm.get("/api/v1/notifications").json()["items"])
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from workflow_executions")).scalar_one() == 0
