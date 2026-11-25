"""The new start flow: the kind of work chosen at creation, the kickoff and its checklist, the client's approval of
the brief after the PM, and an administrator starting delivery when the PM is not available."""

from sqlalchemy import text

from tests.test_brief import _client_approves, _kickoff, _ready, _validate
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _signed_in


def _pm_approved_brief(pm, ph, w):
    _validate(pm, ph, w)
    brief = pm.post(f"{w}/brief/assemble", headers=ph).json()["item"]
    pm.put(f"{w}/items/{brief['id']}", headers=ph, json={"expected_version": brief["version"],
                                                         "provenance": "confirmed"})
    package = pm.post(f"{w}/project_manager/packages", headers=ph, json={
        "title": "Project brief", "item_ids": [brief["id"]]}).json()
    assert pm.post(f"{w}/packages/{package['id']}/decision", headers=ph,
                   json={"decision": "approve"}).status_code == 200
    return brief, package


def test_the_kickoff_needs_the_team_the_kind_of_work_needs(managed, engine):  # noqa: F811
    _, _, pm, ph, w, _, _, _ = _ready(managed, engine)
    status = pm.get(f"{w}/kickoff").json()
    assert status["scope"] == "ba-department" and status["ready"] and status["kickoff"] is None
    # Changing to the three-department preview needs an Architect and a Designer, who are not assigned.
    changed = pm.put(f"{w}/kickoff/scope", headers=ph, json={"scope": "departments", "reason": "Client wants design"})
    assert changed.status_code == 200 and not changed.json()["ready"]
    refused = pm.post(f"{w}/kickoff", headers=ph, json={"held_at": "2026-11-25 10:00"})
    assert refused.status_code == 409 and refused.json()["code"] == "kickoff_not_ready"
    assert any("Solution Architect" in p for p in refused.json()["problems"])
    sneaky = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "kickoff", "title": "Kickoff", "body": {"held_at": "now"}})
    assert sneaky.status_code == 422  # only the kickoff route records one
    pm.put(f"{w}/kickoff/scope", headers=ph, json={"scope": "ba-department", "reason": "Back to the BA first"})
    held = pm.post(f"{w}/kickoff", headers=ph, json={"held_at": "2026-11-25 10:00", "attendees": ["Olu", "Pam"],
                                                    "communication": "Weekly call on Mondays"})
    assert held.status_code == 201, held.text
    assert held.json()["key"] == "KO-001" and held.json()["provenance"] == "confirmed"
    assert pm.post(f"{w}/kickoff", headers=ph, json={"held_at": "again"}).json()["code"] == "kickoff_held"
    with engine.connect() as conn:
        events = list(conn.execute(text("select payload from audit_events where event_type = 'project.scope_changed'"
                                        )).scalars())
    assert [e["to"] for e in events] == ["departments", "ba-department"]  # every change is audited


def test_the_client_approves_the_brief_after_the_pm_and_the_kind_of_work_locks(managed, engine):  # noqa: F811
    _, _, pm, ph, w, project, people, _ = _ready(managed, engine)
    brief, package = _pm_approved_brief(pm, ph, w)
    assert brief["body"]["sections"][0] == {"heading": "Kind of work", "content": (
        "Preview: the Business Analyst department lifecycle only (the other departments follow)")}
    client, ch = _signed_in(managed, people["client"])
    portal = f"/api/v1/portal/projects/{project}/project-brief"
    seen = client.get(portal).json()["brief"]
    assert seen["client_status"] == "awaiting" and seen["can_decide"] and seen["key"] == "PB-001"
    assert any(n["kind"].startswith("brief_for_client:") for n in client.get("/api/v1/notifications").json()["items"])
    assert pm.post(f"{portal}/decision", headers=ph, json={"package_id": package["id"],
                                                          "decision": "approve"}).status_code == 403  # not the PM
    note = client.post(f"{portal}/decision", headers=ch, json={"package_id": package["id"],
                                                              "decision": "request_changes"})
    assert note.status_code == 422  # say what should change
    asked = client.post(f"{portal}/decision", headers=ch, json={
        "package_id": package["id"], "decision": "request_changes", "note": "Add the second clinic"})
    assert asked.status_code == 200 and asked.json()["brief"]["client_status"] == "changes_requested"
    assert pm.post(f"{w}/brief/start", headers=ph, json={
        "package_id": package["id"]}).json()["code"] == "client_approval_required"
    todo = pm.get(f"{w}/pm/tasks").json()["todos"][0]
    assert "Add the second clinic" in todo["text"] and todo["urgent"]

    # The PM revises (re-assembles from the intake), approves again, and the client approves.
    _, again = _brief_again(pm, ph, w)
    assert client.post(f"{portal}/decision", headers=ch, json={"package_id": again["id"],
                                                              "decision": "approve"}).status_code == 200
    locked = pm.put(f"{w}/kickoff/scope", headers=ph, json={"scope": "mvp", "reason": "Too late"})
    assert locked.status_code == 409 and locked.json()["code"] == "scope_locked"
    assert pm.post(f"{w}/brief/start", headers=ph, json={"package_id": again["id"]}).status_code == 202


def _brief_again(pm, ph, w):
    intake = next(i for i in pm.get(f"{w}/project_manager/items?kind=project_intake").json()["items"])
    body = {**intake["body"], "open_questions": ["Which clinics take part first?"]}
    pm.put(f"{w}/items/{intake['id']}", headers=ph, json={"expected_version": intake["version"], "body": body})
    brief = pm.post(f"{w}/brief/assemble", headers=ph).json()["item"]
    pm.put(f"{w}/items/{brief['id']}", headers=ph, json={"expected_version": brief["version"],
                                                         "provenance": "confirmed"})
    package = pm.post(f"{w}/project_manager/packages", headers=ph, json={
        "title": "Project brief", "item_ids": [brief["id"]]}).json()
    decided = pm.post(f"{w}/packages/{package['id']}/decision", headers=ph, json={"decision": "approve"})
    assert decided.status_code == 200, decided.text  # re-assembled by the platform: no PM edits, approves alone
    return brief, package


def test_changing_the_kind_of_work_withdraws_a_brief_waiting_for_the_client(managed, engine):  # noqa: F811
    _, _, pm, ph, w, project, people, _ = _ready(managed, engine)
    _, package = _pm_approved_brief(pm, ph, w)
    pm.put(f"{w}/kickoff/scope", headers=ph, json={"scope": "departments", "reason": "Design is in scope"})
    client, ch = _signed_in(managed, people["client"])
    seen = client.get(f"/api/v1/portal/projects/{project}/project-brief").json()["brief"]
    assert seen["client_status"] == "withdrawn" and not seen["can_decide"]
    r = client.post(f"/api/v1/portal/projects/{project}/project-brief/decision", headers=ch,
                    json={"package_id": package["id"], "decision": "approve"})
    assert r.status_code == 409  # the old brief names the old kind of work


def test_an_administrator_starts_delivery_with_a_reason_when_the_pm_is_not_available(managed, engine):  # noqa: F811
    c, h, pm, ph, w, project, people, _ = _ready(managed, engine)
    _, package = _pm_approved_brief(pm, ph, w)
    _client_approves(managed, people, project, package["id"])
    silent = c.post(f"{w}/brief/start", headers=h, json={"package_id": package["id"]})
    assert silent.status_code == 422 and silent.json()["code"] == "reason_required"
    analyst, ah = _signed_in(managed, people["analyst"])
    assert analyst.post(f"{w}/brief/start", headers=ah, json={
        "package_id": package["id"], "reason": "x"}).status_code == 403  # neither the PM nor an administrator
    r = c.post(f"{w}/brief/start", headers=h, json={"package_id": package["id"], "reason": "Pam is on leave"})
    assert r.status_code == 202, r.text
    with engine.connect() as conn:
        payload = conn.execute(text("select payload from audit_events where event_type = 'work.brief_handed_off'"
                                    )).scalar_one()
    assert payload["started_by_administrator"] and payload["reason"] == "Pam is on leave"
    notes = pm.get("/api/v1/notifications").json()["items"]
    assert any(n["kind"].startswith("started_for_you:") for n in notes)  # the PM is told


def test_the_brief_needs_the_kickoff(managed, engine):  # noqa: F811
    _, _, pm, ph, w, _, _, _ = _ready(managed, engine)
    assert pm.post(f"{w}/brief/assemble", headers=ph).json()["code"] == "kickoff_required"
    _kickoff(pm, ph, w)
    assert pm.post(f"{w}/brief/assemble", headers=ph).json()["code"] == "intake_not_validated"
