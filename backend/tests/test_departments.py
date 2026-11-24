"""Step 7.2a: the department lifecycle so far. BA first; then the Solution Architect and UI/UX Designer in parallel
from the approved BA package (RD-13), each through its own steps, packages, review and owner input."""

import pytest
from sqlalchemy import text

from app.portal.lifecycle import BA_STAGES, SA_STAGES, UX_STAGES
from tests.test_portal import Portal, _email, box  # noqa: F401  (fixture)

BA, SA, UX = "business_analyst", "solution_architect", "ui_ux_designer"
# Every list a step may return; each entry carries the fields of every kind that shares its key.
LISTS = {
    "open_questions": [{"question": "Which clinics take part first?"}],
    "assumptions": [{"title": "Phones", "description": "Most patients book on a phone"}],
    "stakeholders": [{"title": "Reception", "role": "Manage bookings"}],
    "requirements": [{"title": "Book a visit", "description": "Book online", "type": "functional"}],
    "user_stories": [{"title": "Book online", "role": "patient", "want": "to book without phoning"}],
    "risks": [{"title": "Double bookings", "description": "Two patients get one slot", "impact": "high"}],
    "drivers": [{"title": "Availability", "description": "Booking works at all hours", "type": "quality_attribute"}],
    "components": [{"title": "Booking service", "responsibility": "Owns bookings", "type": "service",
                    "purpose": "A booking card"}],
    "decisions": [{"title": "PostgreSQL", "context": "Relational data", "decision": "Use PostgreSQL"}],
    "entities": [{"title": "Booking", "description": "A visit booking",
                  "attributes": [{"name": "id", "type": "text", "key": "pk"}]}],
    "endpoints": [{"title": "Create booking", "method": "post", "path": "/bookings", "purpose": "Book a visit"}],
    "controls": [{"title": "Sign-in", "area": "authentication", "description": "Patients sign in"}],
    "resources": [{"title": "App server", "type": "compute", "purpose": "Runs the API"}],
    "documents": [{"title": "Architecture", "sections": [{"heading": "Overview", "content": "Three parts"}]}],
    "personas": [{"title": "Busy parent", "description": "Books for the family"}],
    "research": [{"title": "Phone queues", "finding": "Calls wait 10 minutes"}],
    "site_map": [{"title": "Home", "purpose": "Start a booking"}],
    "journeys": [{"title": "Book a visit", "persona": "Busy parent", "steps": ["Open", "Pick a slot", "Confirm"]}],
    "screens": [{"title": "Pick a slot", "purpose": "Choose a time", "sections": ["Calendar", "Slots"]}],
    "tokens": [{"title": "Primary", "category": "color", "value": "#174B38"}],
    "flows": [{"title": "Confirm", "from_screen": "Pick a slot", "to_screen": "Confirmation", "trigger": "Tap Book"}],
}


@pytest.fixture
def env(client, engine, settings, box):  # noqa: F811
    portal = Portal(client, engine, settings, _email())
    portal.box = box
    portal.model.extra.update(LISTS)
    portal.setup_team()
    portal.people = {d: portal.holder(d) for d in (BA, SA, UX)}
    return portal


def _w(env, path=""):
    return f"/api/v1/projects/{env.project}/work{path}"


def _status(env, key):
    with env.engine.connect() as conn:
        status, reason = conn.execute(text("select status, failure_reason from stage_executions where stage_key = :k"),
                                      {"k": key}).one()
    return status if status != "FAILED" else f"FAILED: {reason}"


def _decide_step(env, department, step):
    """What the department's professional does in Lifecycle steps, through the same endpoints."""
    client, h = env.people[department]
    steps = {s["key"]: s for s in client.get(_w(env, f"/{department}/steps")).json()["items"]}
    item = steps[step]
    assert item["status"] == "AWAITING_HUMAN_REVIEW", (step, item["status"], item["failure_reason"])
    if item["kind"] == "records":
        for r in item["records"]:
            if r["provenance"] == "ai_suggestion":
                assert client.put(_w(env, f"/items/{r['id']}"), headers=h, json={
                    "expected_version": r["version"], "provenance": "confirmed"}).status_code == 200
        package = client.post(_w(env, f"/{department}/packages"), headers=h,
                              json={"title": step, "item_ids": [r["id"] for r in item["records"]], "stage_key": step})
        assert package.status_code == 201, package.text
        done = client.post(_w(env, f"/packages/{package.json()['id']}/decision"), headers=h, json={"decision": "approve"})
        assert done.status_code == 200, done.text
        return len(item["records"])
    version = env.item(step, client)["current_version_id"]
    if item["kind"] == "owner_input":
        assert env.post(f"/deliverables/{step}/questions", {"question": "Anything to change?"}, client, h).status_code == 201
        question = next(a for a in env.get()["pending_actions"] if a["kind"] == "question" and a["stage"] == step)
        assert env.post(f"/questions/{question['question_id']}/answer", {"answer": "No further input"}).status_code in (200, 202)
    assert env.decide(step, version=version, client=client, headers=h).status_code == 200
    return 0


def test_architect_and_designer_run_in_parallel_from_the_approved_ba_package(env):
    scopes = {s["key"]: s for s in env.get("/intake")["scopes"]}
    assert scopes["departments"]["stages"] == 27
    env.start(scope="departments")
    for stage in BA_STAGES:
        _decide_step(env, BA, stage.id)
    assert _status(env, "ba_user_review") == "APPROVED"
    # Both departments start from the same approved package and wait for their professionals at the same time.
    assert _status(env, "sa_requirements_analysis") == "AWAITING_HUMAN_REVIEW"
    assert _status(env, "ux_discovery") == "AWAITING_HUMAN_REVIEW"

    made = {}
    for sa, ux in zip(SA_STAGES, UX_STAGES + (None,), strict=True):  # interleaved, as two people would work
        made[sa.id] = _decide_step(env, SA, sa.id)
        if ux is not None:
            made[ux.id] = _decide_step(env, UX, ux.id)
    for stage in (*SA_STAGES, *UX_STAGES):
        assert _status(env, stage.id) == "APPROVED", stage.id
    with env.engine.connect() as conn:
        assert conn.execute(text("select status from workflow_executions")).scalar_one() == "COMPLETED"
        kinds = set(conn.execute(text("select distinct kind from work_items where status <> 'archived'")).scalars())
    assert {"architecture_driver", "component", "adr", "data_entity", "api_endpoint", "security_control",
            "infra_resource", "tech_risk", "architecture_document", "persona", "research_note", "ia_node",
            "user_journey", "screen", "design_token", "ui_component", "prototype_flow"} <= kinds
    endpoint = env.people[SA][0].get(_w(env, f"/{SA}/items?kind=api_endpoint")).json()["items"][0]
    assert endpoint["body"]["method"] == "POST"  # normalized
    # The designer reads the BA's approved work, not the architect's (they run side by side).
    with env.engine.connect() as conn:
        reads = conn.execute(text("select spec_json from workflow_versions v join workflow_executions e "
                                  "on e.workflow_version_id = v.id")).scalar_one()
    spec = {s["id"]: s for s in reads["stages"]}
    assert "ba_requirements" in spec["ux_discovery"]["reads"] and not any(r.startswith("sa_") for r in
                                                                          spec["ux_wireframes"]["reads"])


def test_each_department_decides_only_its_own_steps(env):
    env.start(scope="departments")
    for stage in BA_STAGES:
        _decide_step(env, BA, stage.id)
    architect, ah = env.people[SA]
    steps = {s["key"]: s for s in env.people[UX][0].get(_w(env, f"/{UX}/steps")).json()["items"]}
    first = steps["ux_discovery"]
    assert architect.get(_w(env, f"/{UX}/steps")).status_code == 403
    r = architect.post(_w(env, f"/{UX}/packages"), headers=ah, json={
        "item_ids": [x["id"] for x in first["records"]], "stage_key": "ux_discovery"})
    assert r.status_code == 403
