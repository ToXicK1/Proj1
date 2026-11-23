"""Step 7.1c: the department AI assistant answers and proposes; only a person adds a proposal, as a suggestion."""

import json

import httpx
import pytest
from sqlalchemy import text

from tests.test_portal import Portal, _email, box  # noqa: F401  (fixture)

BA = "business_analyst"
PROPOSALS = [{"kind": "requirement", "title": "Cancel a visit", "description": "A patient cancels a booked visit",
              "type": "functional"},
             {"kind": "requirement", "title": "Missing type", "description": "No type given"},  # unusable
             {"kind": "test_case", "title": "Not a BA kind"}]  # unusable


def _assistant_answers(model):
    inner = model.handler

    def handler(request):
        body = json.loads(request.content)
        if "AI assistant of the" not in body["messages"][0]["content"]:
            return inner(request)
        self_seen = body["messages"][1]["content"]
        model.assistant_prompts.append(self_seen)
        answer = {"answer": "Cancelling a visit is not covered yet.", "proposals": PROPOSALS}
        return httpx.Response(200, json={"model": body["model"], "usage": {"prompt_tokens": 9, "completion_tokens": 9},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(answer)}}]})

    model.assistant_prompts = []
    model.handler = handler


@pytest.fixture
def env(client, engine, settings, box):  # noqa: F811
    portal = Portal(client, engine, settings, _email())
    portal.box = box
    _assistant_answers(portal.model)
    client.app.state.provider_transport = portal.model.transport()
    portal.setup_team()
    portal.analyst, portal.ah = portal.holder(BA)
    return portal


def _w(env, path=""):
    return f"/api/v1/projects/{env.project}/work{path}"


def test_the_assistant_answers_and_a_person_adds_its_proposal_as_a_suggestion(env):
    env.start(scope="ba-department")
    r = env.analyst.post(_w(env, f"/{BA}/assistant"), headers=env.ah,
                         json={"question": "Which requirements are we missing?"})
    assert r.status_code == 202, r.text
    exchange = env.analyst.get(_w(env, f"/{BA}/assistant")).json()["items"][0]
    assert exchange["status"] == "answered" and exchange["answer"] == "Cancelling a visit is not covered yet."
    assert [p["title"] for p in exchange["proposals"]] == ["Cancel a visit"]  # unusable ones dropped
    assert "Which requirements are we missing?" in env.model.assistant_prompts[0]
    before = env.analyst.get(_w(env, f"/{BA}/items?kind=requirement")).json()["items"]
    assert not any(i["title"] == "Cancel a visit" for i in before)  # nothing is added without a person

    added = env.analyst.post(_w(env, f"/assistant/{exchange['id']}/proposals/0"), headers=env.ah)
    assert added.status_code == 200, added.text
    key = added.json()["proposals"][0]["added"]
    item = next(i for i in env.analyst.get(_w(env, f"/{BA}/items?kind=requirement")).json()["items"] if i["key"] == key)
    assert item["provenance"] == "ai_suggestion"  # still to be confirmed before it can be submitted
    detail = env.analyst.get(_w(env, f"/items/{item['id']}")).json()
    assert detail["versions"][0]["sources"][0]["assistant_exchange"] == exchange["id"]
    again = env.analyst.post(_w(env, f"/assistant/{exchange['id']}/proposals/0"), headers=env.ah)
    assert again.status_code == 409
    with env.engine.connect() as conn:
        task = conn.execute(text("select task from agent_runs where task = 'assistant'")).scalars().first()
    assert task == "assistant"  # a recorded model call like any other


def test_only_the_department_uses_its_assistant(env):
    env.start(scope="ba-department")
    other, oh = env.holder("solution_architect")
    assert other.post(_w(env, f"/{BA}/assistant"), headers=oh, json={"question": "hi"}).status_code == 403
    assert other.get(_w(env, f"/{BA}/assistant")).status_code == 403
    env.analyst.post(_w(env, f"/{BA}/assistant"), headers=env.ah, json={"question": "hi"})
    exchange = env.analyst.get(_w(env, f"/{BA}/assistant")).json()["items"][0]
    assert other.post(_w(env, f"/assistant/{exchange['id']}/proposals/0"), headers=oh).status_code == 403


def test_before_the_lifecycle_starts_the_assistant_says_so(env):
    env.analyst.post(_w(env, f"/{BA}/assistant"), headers=env.ah, json={"question": "hi"})
    exchange = env.analyst.get(_w(env, f"/{BA}/assistant")).json()["items"][0]
    assert exchange["status"] == "failed" and "started" in exchange["failure"]
