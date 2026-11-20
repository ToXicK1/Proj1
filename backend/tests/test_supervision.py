"""Escalations pause a stage; questions to the owner wait for an answer that goes back to the AI."""

import uuid

import pytest
from sqlalchemy import text

from app.portal.lifecycle import BY_STAGE, STAGES
from tests.test_collab import _overseer, _owner_only
from tests.test_portal import FIRST, Portal, _email, box  # noqa: F401  (fixture)

NEXT = [s.id for s in STAGES if s.in_scope("poc") and s.gated][1]  # the AI step after the first


@pytest.fixture
def team(client, engine, settings, box):  # noqa: F811
    env = Portal(client, engine, settings, _email())
    env.box = box
    env.setup_team()
    env.analyst = env.holder(BY_STAGE[FIRST].profile)
    env.next_holder = env.holder(BY_STAGE[NEXT].profile)
    env.manager = _overseer(env, "project_manager")
    env.devops = env.holder("devops_release")
    _owner_only(env)
    env.start()
    assert env.step_status(FIRST) == "Awaiting Review"
    return env


def _post(env, who, path, body):
    client, headers = who[:2]
    return client.post(env.base + path, headers=headers, json=body)


def _audit(env, event):
    with env.engine.connect() as conn:
        return conn.execute(text("select count(*) from audit_events where project_id = :p and event_type = :e"),
                            {"p": uuid.UUID(env.project), "e": event}).scalar()


# Escalations --------------------------------------------------------------------------------------------------------

def test_an_escalation_pauses_approval_until_it_is_resolved(team):
    r = _post(team, team.analyst, f"/stages/{FIRST}/escalations", {"reason": "The scope contradicts the brief"})
    assert r.status_code == 201, r.text
    escalation = r.json()
    assert escalation["status"] == "open" and escalation["raised_by"] == "Colleague"
    blocked = team.decide(FIRST, client=team.analyst[0], headers=team.analyst[1])
    assert blocked.status_code == 409 and blocked.json()["code"] == "escalated"
    assert _post(team, team.analyst, f"/stages/{FIRST}/escalations", {"reason": "again"}).status_code == 409
    notices = [n["message"] for n in team.manager[0].get("/api/v1/notifications").json()["items"]]
    assert any("was escalated and is paused" in n for n in notices)
    listed = team.manager[0].get(team.base + "/escalations").json()["items"]
    assert [e["stage"] for e in listed] == [FIRST]
    resolved = _post(team, team.manager, f"/escalations/{escalation['id']}/resolve", {"resolution": "Agreed scope"})
    assert resolved.status_code == 200 and resolved.json()["status"] == "resolved"
    assert team.decide(FIRST, client=team.analyst[0], headers=team.analyst[1]).status_code == 200
    assert _audit(team, "stage.escalated") == 1 and _audit(team, "stage.escalation_resolved") == 1


def test_owners_outsiders_and_other_departments_cannot_escalate(team):
    assert _post(team, (team.client, team.h), f"/stages/{FIRST}/escalations", {"reason": "Not convinced"}).status_code == 403
    outsider = team.person()
    assert _post(team, outsider, f"/stages/{FIRST}/escalations", {"reason": "Not convinced"}).status_code == 404
    assert _post(team, team.devops, f"/stages/{FIRST}/escalations", {"reason": "Not convinced"}).status_code == 404  # not their step
    assert team.client.get(team.base + "/escalations").status_code == 403  # owners use tickets


def test_an_escalated_step_is_not_run_until_resolved(team):
    r = _post(team, team.next_holder, f"/stages/{NEXT}/escalations", {"reason": "Wait for the architecture call"})
    assert r.status_code == 201
    assert team.decide(FIRST, client=team.analyst[0], headers=team.analyst[1]).status_code == 200
    assert team.step_status(NEXT) == "In Progress"  # READY, but held back: nothing ran
    with team.engine.connect() as conn:
        assert conn.execute(text("select status from stage_executions where stage_key = :k"),
                            {"k": NEXT}).scalar() == "READY"
    _post(team, team.next_holder, f"/escalations/{r.json()['id']}/resolve", {"resolution": "Decided"})
    assert team.step_status(NEXT) == "Awaiting Review"  # resolving let the work continue


# Questions to the owner --------------------------------------------------------------------------------------------

def test_the_owners_answer_goes_back_to_the_ai_and_the_professional_still_decides(team):
    r = _post(team, team.analyst, f"/deliverables/{FIRST}/questions",
              {"question": "Should candidates be able to apply without an account?"})
    assert r.status_code == 201, r.text
    assert team.step_status(FIRST) == "Waiting for Owner"
    approve = team.decide(FIRST, client=team.analyst[0], headers=team.analyst[1])
    assert approve.json()["code"] == "not_awaiting_review"  # nothing is approved while the owner is asked
    waiting = [a for a in team.get()["pending_actions"] if a["kind"] == "question"]
    assert waiting and waiting[0]["why"] == "Should candidates be able to apply without an account?"
    question = waiting[0]["question_id"]
    assert _post(team, team.analyst, f"/questions/{question}/answer", {"answer": "x"}).status_code == 403
    r = team.post(f"/questions/{question}/answer", {"answer": "Yes, guests can apply with just an email."})
    assert r.status_code == 200, r.text
    assert team.step_status(FIRST) == "Awaiting Review"  # the AI reworked it with the answer...
    item = team.item(FIRST, team.analyst[0])
    assert len(item["versions"]) == 2
    assert any("guests can apply" in c["comment"] and c["status"] == "resolved" for c in item["change_requests"])
    assert team.post(f"/questions/{question}/answer", {"answer": "again"}).status_code == 409
    assert team.decide(FIRST, client=team.analyst[0], headers=team.analyst[1]).status_code == 200  # ...and they decide


def test_a_question_can_be_withdrawn_and_only_the_department_asks(team):
    assert _post(team, team.manager, f"/deliverables/{FIRST}/questions", {"question": "Why?"}).status_code == 403
    assert _post(team, team.next_holder, f"/deliverables/{FIRST}/questions", {"question": "Why?"}).status_code == 404
    r = _post(team, team.analyst, f"/deliverables/{FIRST}/questions", {"question": "Is mobile needed?"})
    question = r.json()["id"]
    assert _post(team, team.analyst, f"/questions/{question}/withdraw", {}).status_code == 200
    assert team.step_status(FIRST) == "Awaiting Review"
    assert not [a for a in team.get()["pending_actions"] if a["kind"] == "question"]
    assert team.post(f"/questions/{question}/answer", {"answer": "late"}).status_code == 409
