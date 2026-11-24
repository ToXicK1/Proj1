"""P3: the PM's AI persona analyses a client meeting into a provisional record, and answers the PM's questions,
at project level (no lifecycle step, no read tools), through the normal routing, budgets and recorded runs."""

import json
import uuid

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents import service as agents
from app.auth.models import User
from app.portal.lifecycle import PM_ASSISTANT, PM_PERSONA
from tests.test_meetings import MEETING, managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _setup, _signed_in

ANALYSIS = {"summary": "The clinic wants online booking because phone lines are busy.",
            "objectives": ["Let patients book online"], "features": ["Book a visit", "Cancel a visit"],
            "stakeholders": ["Patients", "Reception staff"], "decisions": ["Start with online booking"],
            "assumptions": ["Most patients have smartphones"], "risks": [],
            "missing_information": ["Which clinics take part first"],
            "contradictions": ["Notes say 'mornings only' but also 'all day'"],
            "follow_up_questions": ["Do patients pay online?"]}


class Model:
    """Answers the PM persona; records what it was sent."""

    def __init__(self, reply):
        self.reply = reply
        self.sent: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.sent.append(body)
        system = body["messages"][0]["content"]
        answer = self.reply if "KEYS: summary" in system else {"answer": "Ask which clinics take part first."}
        return httpx.Response(200, json={"model": body["model"], "usage": {"prompt_tokens": 50, "completion_tokens": 40},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(answer)}}]})


def _ready(managed, engine, reply=ANALYSIS):  # noqa: F811
    c, h, org, project, people = _setup(managed, engine)
    model = Model(reply)
    managed.state.provider_transport = httpx.MockTransport(model.handler)
    provider = c.post(f"/api/v1/orgs/{org}/providers", headers=h, json={
        "name": "local", "adapter_type": "openai_compatible", "base_url": "http://localhost:11434/v1"}).json()
    c.post(f"/api/v1/orgs/{org}/model-routes", headers=h, json={
        "key": "default", "primary_provider_id": provider["id"], "primary_model": "qwen-test", "fallbacks": []})
    with Session(engine) as db:
        admin = db.execute(text("select id from users where email = 'root@example.com'")).scalar_one()
        agents.create_agent(db, db.get(User, admin), organization_id=uuid.UUID(org), profile_key="project_manager",
                            key=PM_ASSISTANT, kind="lead", instructions=PM_PERSONA, required_keys=["answer"],
                            model_route="default", context_sources=["project_input"], tools=[])
    c.put(f"/api/v1/projects/{project}/manager", headers=h, json={"user_id": people["pm"]["user"]["id"]})
    pm, ph = _signed_in(managed, people["pm"])
    w = f"/api/v1/projects/{project}/work"
    meeting = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "meeting", "title": "Discovery with Olu", "body": MEETING}).json()
    return pm, ph, w, meeting, people, model


def test_a_meeting_analysis_is_a_provisional_record_linked_to_the_meeting(managed, engine):  # noqa: F811
    pm, ph, w, meeting, _, model = _ready(managed, engine)
    r = pm.post(f"{w}/items/{meeting['id']}/analysis", headers=ph)
    assert r.status_code == 202, r.text
    done = pm.get(f"{w}/items/{meeting['id']}/analysis").json()["items"][0]
    assert done["status"] == "answered", done
    key = done["proposals"][0]["added"]
    analysis = next(i for i in pm.get(f"{w}/project_manager/items?kind=meeting_analysis").json()["items"]
                    if i["key"] == key)
    assert analysis["provenance"] == "ai_suggestion"  # nothing counts until the PM confirms it
    assert analysis["body"]["contradictions"] == ANALYSIS["contradictions"]
    detail = pm.get(f"{w}/items/{analysis['id']}").json()
    assert detail["links"][0]["item"]["key"] == meeting["key"] and detail["links"][0]["type"] == "derives_from"
    assert detail["versions"][0]["sources"][0]["meeting"] == meeting["key"]
    # The meeting itself is untouched; the model was given the notes as data.
    assert pm.get(f"{w}/items/{meeting['id']}").json()["version"] == 1
    sent = model.sent[-1]["messages"]
    assert "never make business decisions" in sent[0]["content"] and "Phones are busy" in sent[1]["content"]
    assert "tools" not in model.sent[-1]  # no read tools outside the lifecycle
    with engine.connect() as conn:
        run = conn.execute(text("select stage_execution_id, task, status from agent_runs "
                                "where task = 'meeting_analysis'")).one()
    assert run == (None, "meeting_analysis", "succeeded")  # a recorded run at project level


def test_only_the_projects_pm_asks_and_the_client_sees_nothing(managed, engine):  # noqa: F811
    pm, ph, w, meeting, people, _ = _ready(managed, engine)
    other, oh = _signed_in(managed, people["other_pm"])
    assert other.post(f"{w}/items/{meeting['id']}/analysis", headers=oh).status_code == 403
    client, _ = _signed_in(managed, people["client"])
    assert client.get(f"{w}/items/{meeting['id']}/analysis").status_code in (403, 404)
    req = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "project_intake", "title": "Intake", "body": {"business_problem": "x", "validation": "draft"}}).json()
    assert pm.post(f"{w}/items/{req['id']}/analysis", headers=ph).status_code == 422  # meetings only


def test_a_reply_in_the_wrong_shape_is_repaired_or_reported_never_stored(managed, engine):  # noqa: F811
    pm, ph, w, meeting, _, _ = _ready(managed, engine, reply={**ANALYSIS, "features": "Book a visit"})
    pm.post(f"{w}/items/{meeting['id']}/analysis", headers=ph)
    done = pm.get(f"{w}/items/{meeting['id']}/analysis").json()["items"][0]
    assert done["status"] == "failed" and done["failure"] == "bad_response"
    assert pm.get(f"{w}/project_manager/items?kind=meeting_analysis").json()["items"] == []


def test_the_pm_assistant_answers_without_any_lifecycle(managed, engine):  # noqa: F811
    pm, ph, w, _, _, _ = _ready(managed, engine)
    r = pm.post(f"{w}/project_manager/assistant", headers=ph, json={"question": "What should I ask next?"})
    assert r.status_code == 202
    answered = pm.get(f"{w}/project_manager/assistant").json()["items"][0]
    assert answered["status"] == "answered" and "clinics" in answered["answer"]
