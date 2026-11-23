"""Step 7.1a: lifecycle steps propose records, and the step is approved through a package (RD-17, RD-19)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.artifacts.models import ArtifactVersion
from app.notifications.models import Notification
from app.portal import lifecycle
from app.work.models import WorkItem
from tests.test_portal import Portal, _email, box  # noqa: F401  (fixture)

BA = "business_analyst"
QUESTIONS = [{"question": "Which clinics take part first?"}, {"question": "Do patients pay online?"},
             "not an object", {"answer": "no question given"}]


@pytest.fixture
def env(client, engine, settings, box, monkeypatch):  # noqa: F811
    original = lifecycle.workflow_spec

    def with_records(scope):
        spec = original(scope)
        for stage in spec["stages"]:
            if stage["id"] == "intent_capture":
                stage["records"] = {"open_questions": "discovery_question"}
        return spec

    monkeypatch.setattr(lifecycle, "workflow_spec", with_records)
    portal = Portal(client, engine, settings, _email())
    portal.box = box
    portal.model.extra["open_questions"] = QUESTIONS
    portal.setup_team()
    portal.analyst, portal.ah = portal.holder(BA)
    return portal


def _status(env, key="intent_capture"):
    with env.engine.connect() as conn:
        return conn.execute(text("select status from stage_executions where stage_key = :k"), {"k": key}).scalar_one()


def _w(env, path=""):
    return f"/api/v1/projects/{env.project}/work{path}"


def _questions(env, client=None):
    return (client or env.analyst).get(_w(env, f"/{BA}/items?kind=discovery_question")).json()["items"]


def _confirm(env, item, client=None, h=None):
    r = (client or env.analyst).put(_w(env, f"/items/{item['id']}"), headers=h or env.ah,
                                    json={"expected_version": item["latest_version"], "provenance": "confirmed"})
    assert r.status_code == 200, r.text
    return r.json()


def _submit(env, items, client=None, h=None):
    return (client or env.analyst).post(_w(env, f"/{BA}/packages"), headers=h or env.ah, json={
        "title": "Intent capture", "item_ids": [i["id"] for i in items], "stage_key": "intent_capture"})


def test_the_ai_output_becomes_suggestions_linked_to_the_step(env):
    env.start()
    assert _status(env) == "AWAITING_HUMAN_REVIEW"
    found = _questions(env)
    assert sorted(i["title"] for i in found) == ["Do patients pay online?", "Which clinics take part first?"]
    assert {i["provenance"] for i in found} == {"ai_suggestion"}  # the two unusable entries were skipped
    detail = env.analyst.get(_w(env, f"/items/{found[0]['id']}")).json()
    assert detail["versions"][0]["sources"][0]["stage"] == "intent_capture"
    with env.engine.connect() as conn:
        kinds = conn.execute(text("select title from ai_activity where stage_key = 'intent_capture'")).scalars().all()
    assert any("Proposed 2 record(s)" in k and "2 entries could not be used" in k for k in kinds)


def test_a_record_step_cannot_be_approved_around_its_package(env):
    env.start()
    r = env.decide("intent_capture", client=env.analyst, headers=env.ah)
    assert r.status_code == 409 and r.json()["code"] == "package_required"


def test_approving_the_package_approves_the_step_on_the_exact_assembled_version(env):
    env.start()
    found = _questions(env)
    assert _submit(env, found).status_code == 422  # still AI suggestions
    confirmed = [_confirm(env, i) for i in found]
    partial = _submit(env, confirmed[:1])
    assert partial.status_code == 422 and partial.json()["code"] == "package_incomplete"
    package = _submit(env, confirmed).json()
    assert package["step"] == "intent_capture" and package["edited_by_submitter"] is False
    with Session(env.engine) as db:
        version = db.execute(select(ArtifactVersion).order_by(ArtifactVersion.created_at.desc())).scalars().first()
        assert version.author_type == "system"
        assert [q["key"] for q in version.content_json["open_questions"]] == sorted(i["key"] for i in confirmed)
    done = env.analyst.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.ah,
                            json={"decision": "approve", "note": "Questions agreed"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "approved"
    assert _status(env) in ("APPROVED", "COMPLETED")
    with env.engine.connect() as conn:
        approval = conn.execute(text("select artifact_version_id from approval_decisions")).scalar_one()
        bound = conn.execute(text("select artifact_version_id from work_packages")).scalar_one()
    assert approval == bound == version.id  # recorded against the step's assembled version


def test_own_edits_need_a_second_professional_and_admins_are_told(env):
    env.start()
    found = _questions(env)
    first = _confirm(env, found[0])
    second = _confirm(env, found[1])
    edited = env.analyst.put(_w(env, f"/items/{second['id']}"), headers=env.ah, json={
        "expected_version": second["latest_version"], "title": "Do patients pay online or at the clinic?"}).json()
    package = _submit(env, [first, edited]).json()
    assert package["edited_by_submitter"] is True
    refused = env.analyst.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.ah,
                               json={"decision": "approve"})
    assert refused.status_code == 403 and refused.json()["code"] == "separation_of_duties"
    assert _status(env) == "AWAITING_HUMAN_REVIEW"
    with Session(env.engine) as db:
        kinds = db.execute(select(Notification.kind)).scalars().all()
    assert "package_needs_reviewer" in kinds

    colleague, ch = env.holder(BA)
    ok = colleague.post(_w(env, f"/packages/{package['id']}/decision"), headers=ch, json={"decision": "approve"})
    assert ok.status_code == 200, ok.text
    assert _status(env) in ("APPROVED", "COMPLETED")


def test_requested_changes_rework_the_step_and_keep_what_people_confirmed(env):
    env.start()
    found = _questions(env)
    kept = _confirm(env, found[0])
    _confirm(env, found[1])
    package = _submit(env, [kept, *[i for i in _questions(env) if i["id"] != kept["id"]]]).json()
    r = env.analyst.post(_w(env, f"/packages/{package['id']}/decision"), headers=env.ah,
                         json={"decision": "request_changes", "note": "Ask about opening hours too"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "changes_requested"
    assert _status(env) == "AWAITING_HUMAN_REVIEW"  # the rework ran inline (tests run jobs at once)
    with Session(env.engine) as db:
        rows = db.execute(select(WorkItem).where(WorkItem.kind == "discovery_question")).scalars().all()
    live = [i for i in rows if i.status != "archived"]
    assert {str(i.id) for i in live if i.provenance == "confirmed"} == {i["id"] for i in found}  # both kept
    assert len([i for i in live if i.provenance == "ai_suggestion"]) == 2  # the rework's new suggestions
