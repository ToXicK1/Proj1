"""The PM's Tasks page: to-dos follow the PM's path to delivery, and department work lists every step."""

from tests.test_brief import _client_approves, _ready, _validate
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _signed_in


def test_the_pms_to_dos_follow_the_path_to_delivery_then_show_every_departments_work(managed, engine):  # noqa: F811
    _, _, pm, ph, w, project, people, _ = _ready(managed, engine)
    tasks = pm.get(f"{w}/pm/tasks").json()
    assert [t["module"] for t in tasks["todos"]] == ["kickoff", "intake"]  # the kickoff comes first
    assert tasks["departments"]["started"] is False and tasks["assigned"]["arrives_in"] == "P6"

    _validate(pm, ph, w)
    assert pm.get(f"{w}/pm/tasks").json()["todos"][0]["text"].startswith("Assemble the project brief")
    brief = pm.post(f"{w}/brief/assemble", headers=ph).json()["item"]
    pm.put(f"{w}/items/{brief['id']}", headers=ph, json={"expected_version": brief["version"],
                                                         "provenance": "confirmed"})
    package = pm.post(f"{w}/project_manager/packages", headers=ph, json={
        "title": "Project brief", "item_ids": [brief["id"]]}).json()
    assert any(t["kind"] == "approval" for t in pm.get(f"{w}/pm/tasks").json()["todos"])
    pm.post(f"{w}/packages/{package['id']}/decision", headers=ph, json={"decision": "approve"})
    assert pm.get(f"{w}/pm/tasks").json()["todos"][0]["kind"] == "waiting"  # the brief is with the client
    _client_approves(managed, people, project, package["id"])
    todo = pm.get(f"{w}/pm/tasks").json()["todos"][0]
    assert todo["module"] == "ba_handoff" and todo["urgent"]

    pm.post(f"{w}/brief/start", headers=ph, json={"package_id": package["id"]})
    tasks = pm.get(f"{w}/pm/tasks").json()
    steps = tasks["departments"]["steps"]
    assert tasks["departments"]["started"] and steps[0]["department"] == "business_analyst"
    assert steps[0]["people"] == ["Bea"]  # the department's own approver, not the PM

    analyst, ah = _signed_in(managed, people["analyst"])
    handoff = analyst.get(f"{w}/business_analyst/handoffs").json()["items"][0]
    analyst.post(f"{w}/handoffs/{handoff['id']}/reply", headers=ah, json={
        "action": "request_clarification", "reply": "Which clinics take part first?"})
    clarification = next(t for t in pm.get(f"{w}/pm/tasks").json()["todos"] if t["kind"] == "clarification")
    assert "Which clinics" in clarification["text"] and clarification["urgent"]


def test_only_the_pm_department_reads_the_tasks_page(managed, engine):  # noqa: F811
    _, _, _, _, w, _, people, _ = _ready(managed, engine)
    client, _ = _signed_in(managed, people["client"])
    assert client.get(f"{w}/pm/tasks").status_code in (403, 404)
