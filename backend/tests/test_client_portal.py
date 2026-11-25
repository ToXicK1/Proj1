"""P5: the client's portal with managed accounts. One conversation with the Project Manager, one client assistant
that answers from client-safe material only (RD-23), change requests to the PM, and a progress view from records."""

import json

import httpx
from sqlalchemy import text

from tests.test_brief import _ready, _validate
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _signed_in

CANARY = "CANARY-INTERNAL-7731"


class ClientModel:
    """Answers the client assistant; records what it was sent."""

    def __init__(self, reply="Your project is in discovery with your Project Manager."):
        self.reply, self.sent = reply, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.sent.append(body)
        system = body["messages"][0]["content"]
        answer = {"reply": self.reply} if "KEYS: reply" in system else {"answer": "ok"}
        return httpx.Response(200, json={"model": body["model"], "usage": {"prompt_tokens": 9, "completion_tokens": 9},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(answer)}}]})


def _client(managed, engine, reply=None):  # noqa: F811
    _, _, pm, ph, w, project, people, _ = _ready(managed, engine)
    model = ClientModel(reply) if reply else ClientModel()
    managed.state.provider_transport = httpx.MockTransport(model.handler)
    # Internal material the assistant must never see: a meeting's raw notes and the PM's intake.
    pm.post(f"{w}/project_manager/items", headers=ph, json={"kind": "meeting", "title": "Internal call",
                                                            "body": {"held_at": "2026-11-25 09:00", "status": "held",
                                                                     "raw_notes": f"Budget is tight {CANARY}"}})
    client, ch = _signed_in(managed, people["client"])
    return client, ch, pm, ph, w, project, model


def test_the_clients_questions_go_to_the_pm_and_the_assistant_answers_from_client_safe_material(managed, engine):  # noqa: F811
    client, ch, pm, ph, _, project, model = _client(managed, engine)
    portal = f"/api/v1/portal/projects/{project}"
    space = client.get(portal).json()
    assert space["pm_led"] and space["conversation_with"][0]["profile"] == "project_manager"
    r = client.post(f"{portal}/messages", headers=ch, json={"body": "Where does my project stand?"})
    assert r.status_code == 201, r.text
    thread = client.get(f"{portal}/messages").json()["items"]
    assert [m["profile"] for m in thread] == ["project_manager"] * len(thread)
    answer = thread[-1]
    assert answer["from"] == "Project assistant (AI)" and answer["author_type"] == "representative"
    assert answer["body"] == "Your project is in discovery with your Project Manager."
    sent = json.dumps(model.sent[-1])
    assert CANARY not in sent and "tools" not in model.sent[-1]  # nothing internal, no tools
    assert "Where does my project stand?" in sent
    with engine.connect() as conn:
        run = conn.execute(text("select stage_execution_id, task, status from agent_runs where task = 'client_answer'"
                                )).one()
    assert run == (None, "client_answer", "succeeded")
    notes = pm.get("/api/v1/notifications").json()["items"]
    assert any(n["kind"].startswith("owner_message:") for n in notes)  # the PM is told about every message

    reply = pm.post(f"{portal}/messages/replies", headers=ph, json={"profile": "project_manager",
                                                                   "body": "We meet on Thursday."})
    assert reply.status_code == 201, reply.text
    assert client.get(f"{portal}/messages").json()["items"][-1]["from"] == "Pam (Project Manager)"
    other = client.post(f"{portal}/messages", headers=ch, json={"body": "Hi", "profile": "business_analyst"})
    assert other.status_code == 422  # one conversation, with the PM


def test_a_reply_that_reveals_the_inside_of_the_platform_is_never_shown(managed, engine):  # noqa: F811
    client, ch, _, _, _, project, _ = _client(managed, engine, reply="The agent and its prompt say yes.")
    portal = f"/api/v1/portal/projects/{project}"
    client.post(f"{portal}/messages", headers=ch, json={"body": "Is it going well?"})
    last = client.get(f"{portal}/messages").json()["items"][-1]
    assert last["body"] == "Thank you. Your Project Manager will get back to you on this."


def test_the_client_requests_a_change_and_the_pm_gets_it(managed, engine):  # noqa: F811
    client, ch, pm, _, w, project, _ = _client(managed, engine)
    portal = f"/api/v1/portal/projects/{project}"
    r = client.post(f"{portal}/change-requests", headers=ch, json={"summary": "Add booking for a child",
                                                                   "details": "Parents book for their children"})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "scope_change"
    todos = pm.get(f"{w}/pm/tasks").json()["todos"]
    assert any(t["kind"] == "client" and "Add booking for a child" in t["text"] for t in todos)
    assert any(n["kind"].startswith("change_request:") for n in pm.get("/api/v1/notifications").json()["items"])
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from workflow_executions")).scalar_one() == 0  # nothing changed


def test_the_client_sees_progress_from_records(managed, engine):  # noqa: F811
    client, _, pm, ph, w, project, _ = _client(managed, engine)
    portal = f"/api/v1/portal/projects/{project}"
    assert client.get(f"{portal}/progress").json()["phase"] == "Discovery"
    _validate(pm, ph, w)
    brief = pm.post(f"{w}/brief/assemble", headers=ph).json()["item"]
    pm.put(f"{w}/items/{brief['id']}", headers=ph, json={"expected_version": brief["version"],
                                                         "provenance": "confirmed"})
    package = pm.post(f"{w}/project_manager/packages", headers=ph, json={
        "title": "Project brief", "item_ids": [brief["id"]]}).json()
    pm.post(f"{w}/packages/{package['id']}/decision", headers=ph, json={"decision": "approve"})
    pm.post(f"{w}/brief/start", headers=ph, json={"package_id": package["id"], "scope": "ba-department"})
    progress = client.get(f"{portal}/progress").json()
    assert progress["phase"] == "Delivery" and progress["steps_total"] == 8 and progress["steps_done"] == 0
    assert progress["approved"] == [] and progress["awaiting_you"] == [] and progress["arrive_in"] == "P6"
