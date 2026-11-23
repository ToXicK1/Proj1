"""Work records (step 7.0): versions, provenance, links, comments, packages, handoffs and who may do what."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.projects.models import Project
from app.work import service as work
from tests.test_portal import Portal, _email, box  # noqa: F401  (fixture)

BA, SA = "business_analyst", "solution_architect"
REQ = {"description": "Recruiters post a job in under two minutes", "type": "functional", "priority": "must",
       "acceptance_criteria": ["A job can be posted with title and location"]}


@pytest.fixture
def env(client, engine, settings, box):  # noqa: F811
    portal = Portal(client, engine, settings, _email())
    portal.box = box
    portal.setup_team()
    portal.analyst, portal.ah = portal.holder(BA)
    portal.architect, portal.sh = portal.holder(SA)
    portal.colleague, portal.ch = portal.holder(BA)  # a second analyst: approves what the first one wrote (RD-19)
    return portal


def _w(env, path=""):
    return f"/api/v1/projects/{env.project}/work{path}"


def _create(env, title="Post a job", body=None, kind="requirement", provenance="confirmed", client=None, h=None):
    r = (client or env.analyst).post(_w(env, f"/{BA}/items"), headers=h or env.ah,
                                     json={"kind": kind, "title": title, "body": body or REQ,
                                           "provenance": provenance})
    return r


def test_a_professional_creates_and_edits_a_requirement_with_full_history(env):
    r = _create(env)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["key"] == "REQ-001" and item["version"] == 1 and item["status"] == "draft"
    second = _create(env, "Search jobs").json()
    assert second["key"] == "REQ-002"

    edited = env.analyst.put(_w(env, f"/items/{item['id']}"), headers=env.ah, json={
        "expected_version": 1, "body": {**REQ, "priority": "should"}, "reason": "Agreed with the owner"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2 and [v["reason"] for v in edited.json()["versions"]] == [
        "created", "Agreed with the owner"]
    stale = env.analyst.put(_w(env, f"/items/{item['id']}"), headers=env.ah, json={
        "expected_version": 1, "title": "Another title"})
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    diff = env.analyst.get(_w(env, f"/items/{item['id']}/compare?a=1&b=2")).json()
    assert diff["changes"] == [{"field": "priority", "before": "must", "after": "should"}]

    listed = env.analyst.get(_w(env, f"/{BA}/items?q=search")).json()
    assert [i["key"] for i in listed["items"]] == ["REQ-002"] and listed["can_edit"] is True
    env.analyst.post(_w(env, f"/items/{second['id']}/archive"), headers=env.ah, json={"archived": True})
    assert [i["key"] for i in env.analyst.get(_w(env, f"/{BA}/items")).json()["items"]] == ["REQ-001"]


def test_versions_cannot_be_changed_in_the_database(env):
    item = _create(env).json()
    with pytest.raises(DBAPIError), env.engine.begin() as conn:
        conn.execute(text("update work_item_versions set title = 'tampered' where item_id = :i"),
                     {"i": uuid.UUID(item["id"])})


def test_bodies_are_checked_against_the_kind(env):
    bad = _create(env, body={"description": "x", "type": "wishful", "colour": "red"})
    assert bad.status_code == 422
    assert set(bad.json()["problems"]) == {"unknown field 'colour'",
                                           "'type' must be one of business, functional, non_functional, constraint"}
    wrong_department = env.analyst.post(_w(env, f"/{SA}/items"), headers=env.ah,
                                        json={"kind": "requirement", "title": "x", "body": REQ})
    assert wrong_department.status_code == 403
    assert _create(env, provenance="ai_suggestion").status_code == 422  # only the AI proposes suggestions


def test_other_departments_owners_and_members_cannot_change_the_work(env):
    item = _create(env).json()
    assert _create(env, client=env.architect, h=env.sh).status_code == 403
    r = env.architect.put(_w(env, f"/items/{item['id']}"), headers=env.sh, json={"expected_version": 1,
                                                                               "title": "Mine now"})
    assert r.status_code == 403
    # Before approval, the architect cannot even read the analyst's drafts.
    assert env.architect.get(_w(env, f"/items/{item['id']}")).status_code == 404
    assert env.architect.get(_w(env, f"/{BA}/items")).json()["items"] == []
    member, _, _ = env.person()
    assert member.get(_w(env, f"/{BA}/items")).status_code in (403, 404)


def _ai_proposal(env, title="Shortlist candidates"):
    with Session(env.engine) as db:
        project = db.get(Project, uuid.UUID(env.project))
        item = work.propose(db, project, BA, agent="ba-lead", kind="requirement", title=title,
                            body={"description": "Rank applicants", "type": "functional"},
                            sources=[{"artifact_version": "brief"}])
        db.commit()
        return str(item.id)


def test_ai_suggestions_must_be_confirmed_by_a_person_before_submission(env):
    suggestion = _ai_proposal(env)
    got = env.analyst.get(_w(env, f"/items/{suggestion}")).json()
    assert got["provenance"] == "ai_suggestion" and got["versions"][0]["author_type"] == "ai"
    assert got["versions"][0]["sources"] == [{"artifact_version": "brief"}]
    r = env.analyst.post(_w(env, f"/{BA}/packages"), headers=env.ah, json={"item_ids": [suggestion]})
    assert r.status_code == 422 and "confirm it first" in r.json()["problems"][0]
    confirmed = env.analyst.put(_w(env, f"/items/{suggestion}"), headers=env.ah,
                                json={"expected_version": 1, "provenance": "confirmed", "reason": "Owner agreed"})
    assert confirmed.json()["provenance"] == "confirmed" and confirmed.json()["versions"][1]["author_type"] == "human"
    assert env.analyst.post(_w(env, f"/{BA}/packages"), headers=env.ah,
                            json={"item_ids": [suggestion]}).status_code == 201


def test_a_package_freezes_exact_versions_and_only_the_department_decides(env):
    a, b = _create(env).json(), _create(env, "Search jobs").json()
    package = env.analyst.post(_w(env, f"/{BA}/packages"), headers=env.ah, json={
        "title": "Requirements v1", "item_ids": [a["id"], b["id"]]}).json()
    assert [(i["key"], i["number"]) for i in package["items"]] == [("REQ-001", 1), ("REQ-002", 1)]
    # Edited after submission: the newer version is not part of what gets approved.
    env.analyst.put(_w(env, f"/items/{b['id']}"), headers=env.ah, json={"expected_version": 1, "title": "Find jobs"})
    r = env.architect.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.sh,
                           json={"decision": "approve"})
    assert r.status_code == 403
    assert env.analyst.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.ah,
                            json={"decision": "request_changes"}).status_code == 422  # needs a reason
    own = env.analyst.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.ah, json={"decision": "approve"})
    assert own.status_code == 403 and own.json()["code"] == "separation_of_duties"
    done = env.colleague.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.ch,
                            json={"decision": "approve", "note": "Ready for architecture"}).json()
    assert done["status"] == "approved"
    statuses = {i["key"]: i["status"] for i in env.analyst.get(_w(env, f"/{BA}/items")).json()["items"]}
    assert statuses == {"REQ-001": "approved", "REQ-002": "draft"}
    again = env.colleague.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.ch,
                             json={"decision": "approve"})
    assert again.status_code == 409

    # The architect now reads the approved versions only.
    seen = env.architect.get(_w(env, f"/{BA}/items")).json()
    assert seen["view"] == "approved" and {(i["key"], i["title"]) for i in seen["items"]} == {
        ("REQ-001", "Post a job"), ("REQ-002", "Search jobs")}
    with env.engine.connect() as conn:
        events = conn.execute(text("select event_type from audit_events where event_type like 'work.%'")).scalars()
        assert {"work.created", "work.edited", "work.package_submitted", "work.package_approved"} <= set(events)


def test_handoffs_record_exact_versions_and_never_move_workflow_state(env):
    a = _create(env).json()
    package = env.analyst.post(_w(env, f"/{BA}/packages"), headers=env.ah, json={"item_ids": [a["id"]]}).json()
    early = env.analyst.post(_w(env, f"/packages/{package['id']}/handoffs"), headers=env.ah,
                             json={"to_department": SA})
    assert early.status_code == 409  # not approved yet
    env.colleague.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.ch, json={"decision": "approve"})
    with env.engine.connect() as conn:
        before = conn.execute(text("select count(*) from stage_transitions")).scalar_one()
    sent = env.analyst.post(_w(env, f"/packages/{package['id']}/handoffs"), headers=env.ah,
                            json={"to_department": SA, "note": "Integration with the HR system is open"}).json()
    assert sent["status"] == "sent" and sent["package"]["items"][0]["number"] == 1
    inbox = env.architect.get(_w(env, f"/{SA}/handoffs")).json()["items"]
    assert [h["id"] for h in inbox] == [sent["id"]]
    assert env.analyst.post(_w(env, f"/handoffs/{sent['id']}/reply"), headers=env.ah,
                            json={"action": "acknowledge"}).status_code == 403  # only the receiver replies
    asked = env.architect.post(_w(env, f"/handoffs/{sent['id']}/reply"), headers=env.sh, json={
        "action": "request_clarification", "reply": "Which HR system?"}).json()
    assert asked["status"] == "clarification_requested"
    with env.engine.connect() as conn:
        assert conn.execute(text("select count(*) from stage_transitions")).scalar_one() == before


def test_links_comments_and_traceability(env):
    req = _create(env).json()
    story = env.analyst.post(_w(env, f"/{BA}/items"), headers=env.ah, json={
        "kind": "user_story", "title": "Post a job", "body": {"role": "recruiter", "want": "to post a job"}}).json()
    assert story["key"] == "US-001"
    linked = env.analyst.post(_w(env, f"/items/{story['id']}/links"), headers=env.ah,
                              json={"to_item_id": req["id"], "link_type": "derives_from"}).json()
    assert linked["links"][0]["item"]["key"] == "REQ-001"
    assert env.analyst.post(_w(env, f"/items/{story['id']}/links"), headers=env.ah,
                            json={"to_item_id": req["id"], "link_type": "loves"}).status_code == 422
    trace = env.analyst.get(_w(env, "/traceability")).json()
    assert trace["links"] == [{"from": story["id"], "to": req["id"], "type": "derives_from"}]

    comments = env.analyst.post(_w(env, f"/items/{req['id']}/comments"), headers=env.ah, json={
        "body": "Is two minutes measured from login?", "anchor": {"field": "description"}}).json()["items"]
    assert comments[0]["version"] == 1 and comments[0]["anchor"] == {"field": "description"}
    # Another department may not comment on drafts it cannot see.
    assert env.architect.post(_w(env, f"/items/{req['id']}/comments"), headers=env.sh,
                              json={"body": "hi"}).status_code == 404


def test_team_overview_counts_come_from_records(env):
    _create(env)
    _ai_proposal(env)
    cards = {c["profile"]: c for c in env.analyst.get(_w(env, "/team")).json()["departments"]}
    assert len(cards) == 6
    ba = cards[BA]
    assert ba["visible"] and ba["can_edit"] and ba["work"]["records"] == 2 and ba["work"]["to_confirm"] == 1
    assert cards[SA]["visible"] is False and "current" not in cards[SA]
    assert len(ba["people"]) == 2
