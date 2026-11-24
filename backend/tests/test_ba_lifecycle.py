"""Step 7.1b: the Business Analyst department lifecycle from intake to the owner's input and final approval.

The fake model returns the record lists below; everything else (records, packages, gates, the owner step,
sending a step back) runs through the real platform.
"""

import pytest
from sqlalchemy import text

from tests.test_portal import Portal, _email, box  # noqa: F401  (fixture)

BA = "business_analyst"
STEPS = ["ba_intake_review", "ba_discovery", "ba_requirements", "ba_user_stories", "ba_scope",
         "ba_requirements_review", "ba_professional_review", "ba_user_review"]
LISTS = {
    "open_questions": [{"question": "Which clinics take part first?"}],
    "assumptions": [{"title": "Patients have smartphones", "description": "Most patients book on a phone"}],
    "stakeholders": [{"title": "Reception staff", "role": "Manage the day's bookings", "influence": "High"}],
    "requirements": [{"title": "Book a visit", "description": "A patient books a visit online",
                      "type": "Functional", "priority": "MUST", "acceptance_criteria": "Booking confirmed\nEmail sent"}],
    "user_stories": [{"title": "Book online", "role": "patient", "want": "to book a visit without phoning"}],
    "risks": [{"title": "Double bookings", "description": "Two patients get the same slot", "impact": "high"}],
}
FINDINGS = [{"title": "No cancellation story", "finding": "Cancelling a visit has no story", "severity": "Major",
             "affects": "REQ-001"}]


def _with_review_findings(model):
    """The Requirements Review step returns findings as records; independent reviewers keep their own answer."""
    import json

    import httpx

    inner = model.handler

    def handler(request):
        response = inner(request)
        body = json.loads(request.content)
        if "Requirements Review step" not in body["messages"][0]["content"]:
            return response
        data = json.loads(response.content)
        answer = json.loads(data["choices"][0]["message"]["content"])
        answer["findings"] = FINDINGS
        data["choices"][0]["message"]["content"] = json.dumps(answer)
        return httpx.Response(200, json=data)

    model.handler = handler


@pytest.fixture
def env(client, engine, settings, box):  # noqa: F811
    portal = Portal(client, engine, settings, _email())
    portal.box = box
    portal.model.extra.update(LISTS)
    _with_review_findings(portal.model)
    client.app.state.provider_transport = portal.model.transport()
    portal.setup_team()
    portal.analyst, portal.ah = portal.holder(BA)
    return portal


def _w(env, path=""):
    return f"/api/v1/projects/{env.project}/work{path}"


def _status(env, key):
    with env.engine.connect() as conn:
        status, reason = conn.execute(text("select status, failure_reason from stage_executions where stage_key = :k"),
                                      {"k": key}).one()
    return status if status != "FAILED" else f"FAILED: {reason}"


def _approve_step(env, step):
    """Confirm the step's suggestions, submit its package and approve it, as the professional would."""
    items = [i for i in env.analyst.get(_w(env, f"/{BA}/items")).json()["items"]]
    with env.engine.connect() as conn:
        ids = {str(r) for r in conn.execute(text(
            "select w.id from work_items w join stage_executions s on s.id = w.stage_execution_id "
            "where s.stage_key = :k and w.status <> 'archived'"), {"k": step}).scalars()}
    mine = [i for i in items if i["id"] in ids]
    for item in mine:
        if item["provenance"] == "ai_suggestion":
            r = env.analyst.put(_w(env, f"/items/{item['id']}"), headers=env.ah,
                                json={"expected_version": item["latest_version"], "provenance": "confirmed"})
            assert r.status_code == 200, r.text
    package = env.analyst.post(_w(env, f"/{BA}/packages"), headers=env.ah,
                               json={"title": step, "item_ids": [i["id"] for i in mine], "stage_key": step})
    assert package.status_code == 201, package.text
    done = env.analyst.post(_w(env, f"/packages/{package.json()['id']}/decision"), headers=env.ah,
                            json={"decision": "approve"})
    assert done.status_code == 200, done.text
    return mine


def test_the_ba_department_runs_from_intake_to_the_owners_input_and_final_approval(env):
    scopes = {s["key"]: s for s in env.get("/intake")["scopes"]}
    assert scopes["ba-department"]["stages"] == 8 and "Preview" in scopes["ba-department"]["label"]
    env.start(scope="ba-department")

    for step in STEPS[:6]:
        assert _status(env, step) == "AWAITING_HUMAN_REVIEW", step
        made = _approve_step(env, step)
        assert made, f"{step} proposed no records"
        assert _status(env, step) == "APPROVED"
    kinds = {i["kind"] for i in env.analyst.get(_w(env, f"/{BA}/items")).json()["items"]}
    assert kinds == {"discovery_question", "assumption", "stakeholder", "requirement", "user_story", "risk",
                     "review_finding", "document"}  # document: the BRD and SRS drafts of the review step
    req = next(i for i in env.analyst.get(_w(env, f"/{BA}/items?kind=requirement")).json()["items"])
    assert req["body"]["type"] == "functional" and req["body"]["priority"] == "must"  # normalized
    assert req["body"]["acceptance_criteria"] == ["Booking confirmed", "Email sent"]

    # Human Professional Review: the department's approved work as one package.
    assert _status(env, "ba_professional_review") == "AWAITING_HUMAN_REVIEW"
    review = env.item("ba_professional_review", env.analyst)
    assert review["current_version_id"]

    # Send Requirements Analysis back from the review: it is reworked, later steps wait for re-approval.
    r = env.analyst.post(_w(env, "/steps/ba_professional_review/send-back"), headers=env.ah,
                         json={"step": "ba_requirements", "note": "Add cancelling a visit"})
    assert r.status_code == 200, r.text
    assert _status(env, "ba_requirements") == "AWAITING_HUMAN_REVIEW"  # reworked at once (jobs run inline)
    assert _status(env, "ba_user_stories") == "AWAITING_HUMAN_REVIEW"  # invalidated, waits for its decision
    assert _status(env, "ba_professional_review") == "CHANGES_REQUESTED"  # waits until the steps are approved
    with env.engine.connect() as conn:
        feedback = conn.execute(text("select comment from change_requests order by created_at desc")).scalars().first()
    assert feedback == "Add cancelling a visit"
    for step in ["ba_requirements", "ba_user_stories", "ba_scope", "ba_requirements_review"]:
        _approve_step(env, step)
    assert _status(env, "ba_professional_review") == "AWAITING_HUMAN_REVIEW"  # gathered afresh
    version = env.item("ba_professional_review", env.analyst)["current_version_id"]
    assert env.decide("ba_professional_review", version=version, client=env.analyst, headers=env.ah).status_code == 200
    assert "ba_professional_review" not in {d["stage"] for d in env.get("/deliverables")["items"]}  # internal step

    # User Review and Approval: the professional asks the owner; the owner gives input; only the professional approves.
    assert _status(env, "ba_user_review") == "AWAITING_HUMAN_REVIEW"
    version = env.item("ba_user_review", env.analyst)["current_version_id"]
    early = env.decide("ba_user_review", version=version, client=env.analyst, headers=env.ah)
    assert early.status_code == 409 and early.json()["code"] == "owner_input_required"
    asked = env.post("/deliverables/ba_user_review/questions", {"question": "Please review the analysis and tell us "
                     "anything to change, or that you have no further input."}, env.analyst, env.ah)
    assert asked.status_code == 201, asked.text
    assert _status(env, "ba_user_review") == "AWAITING_USER_INPUT"
    question = next(a for a in env.get()["pending_actions"] if a["kind"] == "question" and a["stage"] == "ba_user_review")
    assert env.decide("ba_user_review", version=version).status_code in (403, 409)  # the owner never approves
    r = env.post(f"/questions/{question['question_id']}/answer", {"answer": "Please also allow booking for a child"})
    assert r.status_code in (200, 202), r.text
    assert _status(env, "ba_user_review") == "AWAITING_HUMAN_REVIEW"  # back to the professional, not to the AI
    with env.engine.connect() as conn:
        assert conn.execute(text("select count(*) from notifications where kind like 'owner_input:%'")).scalar_one() >= 1
    version = env.item("ba_user_review", env.analyst)["current_version_id"]
    assert env.decide("ba_user_review", version=version, client=env.analyst, headers=env.ah).status_code == 200
    assert _status(env, "ba_user_review") == "APPROVED"
    with env.engine.connect() as conn:
        assert conn.execute(text("select status from workflow_executions")).scalar_one() == "COMPLETED"


def test_send_back_is_only_for_the_department_and_its_earlier_ai_steps(env):
    env.start(scope="ba-department")
    for step in STEPS[:6]:
        _approve_step(env, step)
    other, oh = env.holder("solution_architect")
    assert other.post(_w(env, "/steps/ba_professional_review/send-back"), headers=oh,
                      json={"step": "ba_requirements", "note": "x"}).status_code == 403
    assert env.analyst.post(_w(env, "/steps/ba_requirements/send-back"), headers=env.ah,
                            json={"step": "ba_intake_review", "note": "x"}).status_code == 422  # not a review step
    assert env.analyst.post(_w(env, "/steps/ba_professional_review/send-back"), headers=env.ah,
                            json={"step": "ba_user_review", "note": "x"}).status_code == 422  # not upstream


def test_the_steps_view_says_what_each_step_waits_for(env):
    env.start(scope="ba-department")
    steps = env.analyst.get(_w(env, f"/{BA}/steps")).json()
    assert steps["can_edit"] is True
    kinds = {s["key"]: s["kind"] for s in steps["items"]}
    assert [s["key"] for s in steps["items"]] == STEPS
    assert kinds["ba_intake_review"] == "records" and kinds["ba_professional_review"] == "review"
    assert kinds["ba_user_review"] == "owner_input"
    first = steps["items"][0]
    assert first["status"] == "AWAITING_HUMAN_REVIEW" and {r["provenance"] for r in first["records"]} == {"ai_suggestion"}
    other, _ = env.holder("solution_architect")
    assert other.get(_w(env, f"/{BA}/steps")).status_code == 403
    assert env.client.get(_w(env, f"/{BA}/steps")).status_code == 403  # the project owner works in the portal (RD-2)


def test_an_empty_requirements_list_is_never_accepted(env):
    env.model.extra["requirements"] = []  # a lazy model: valid JSON, nothing in it
    env.start(scope="ba-department")
    for step in STEPS[:2]:
        _approve_step(env, step)
    assert _status(env, "ba_requirements").startswith("FAILED")  # asked again, still empty: it stops, never approved
    with env.engine.connect() as conn:
        notes = conn.execute(text("select title from ai_activity where stage_key = 'ba_requirements' "
                                  "and kind = 'retry'")).scalars().all()
    assert any("requirements needs at least 1 usable item" in n for n in notes)


def test_copied_placeholders_never_become_records():
    from app.work.bridge import usable_entries

    assert usable_entries("requirement", [{"title": "<short title>", "description": "<description>",
                                           "type": "functional"}]) == 0
    assert usable_entries("requirement", [{"title": "Book a visit", "description": "A patient books online",
                                           "type": "Functional"}]) == 1
