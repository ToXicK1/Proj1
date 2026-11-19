"""Profile-scoped spaces, team chat with mentions, tickets with AI triage, and department status."""

import uuid

import pytest
from sqlalchemy import text

from app.collab.service import explain
from tests.test_portal import FIRST, Portal, _email, box  # noqa: F401  (fixture)


@pytest.fixture
def env(client, engine, settings, box):  # noqa: F811
    portal = Portal(client, engine, settings, _email())
    portal.box = box
    portal.setup_team()
    return portal


def _owner_only(env):
    """After setting up the team, make the owner a plain project owner rather than also an administrator."""
    with env.engine.begin() as conn:
        conn.execute(text("update memberships set role = 'project_owner' where user_id = :u and organization_id = :o"),
                     {"u": env.owner, "o": uuid.UUID(env.org)})


def _notices(client):
    return [n["message"] for n in client.get("/api/v1/notifications").json()["items"]]


def test_each_professional_sees_only_their_own_department(env):
    analyst, _ = env.holder("business_analyst")
    architect, _ = env.holder("solution_architect")
    _owner_only(env)
    env.start()
    mine = env.get("", analyst)
    assert mine["scope"] == "professional" and mine["my_profiles"] == ["business_analyst"]
    assert [c["profile"] for c in mine["team"]] == ["business_analyst"]
    assert {s["profile"] for p in mine["phases"] for s in p["stages"]} == {"Business Analyst"}
    assert {d["profile"] for d in env.get("/deliverables", analyst)["items"]} == {"business_analyst"}
    assert env.get("/deliverables", architect)["items"] == []  # nothing of the analyst's leaks across
    assert analyst.get(env.base + "/departments/solution_architect/status").status_code == 404
    owner = env.get()
    assert owner["scope"] == "owner" and len(owner["team"]) == 6


def _overseer(env, role):
    other, h, user_id = env.person()
    r = env.client.put(f"/api/v1/orgs/{env.org}/members/{user_id}/access", headers=env.h,
                       json={"role": role, "profiles": []})
    assert r.status_code == 200, r.text
    return other, h, user_id


def _id_of(client, kind=None, profile=None):
    people = client.get("/api/v1/team-chat/people").json()["items"]
    return next(p["user_id"] for p in people if not p["is_you"] and (kind is None or p["kind"] == kind)
                and (profile is None or p["profiles"] == [profile]))


def test_admins_and_project_managers_see_every_project_but_only_managers_chat(env):
    analyst, _ = env.holder("business_analyst")
    admin, _, _ = _overseer(env, "org_admin")
    manager, _, _ = _overseer(env, "project_manager")
    _owner_only(env)
    later = env.new_project()  # created after they joined: they see it too
    for person, kind in ((admin, "admin"), (manager, "manager")):
        listed = {p["id"] for p in person.get("/api/v1/projects").json()["items"]}
        assert {env.project, later} <= listed
        assert person.get(env.base + "/scope").json()["kind"] == kind
    assert admin.get(env.base + "/scope").json()["channels"] == []  # administrators are not in team chats
    assert admin.get("/api/v1/team-chat/channels").json()["items"] == []
    assert admin.get("/api/v1/team-chat/messages/general").status_code == 404
    assert admin.get(env.base + "/team-chat/business_analyst").status_code == 404
    assert len(manager.get(env.base + "/scope").json()["channels"]) == 6
    assert manager.get("/api/v1/team-chat/channels").json()["items"][0]["key"] == "general"
    assert manager.get(env.base + "/team-chat/business_analyst").status_code == 200
    # Oversight shows every project and what waits on whom, to overseers only.
    env.start()
    view = manager.get("/api/v1/oversight").json()
    assert view["role"] == "Project Manager" and {p["id"] for p in view["projects"]} >= {env.project, later}
    mine = next(p for p in view["projects"] if p["id"] == env.project)
    assert mine["started"] and len(mine["departments"]) == 6
    assert admin.get("/api/v1/oversight").json()["role"] == "Administrator"
    assert env.project not in {p["id"] for p in analyst.get("/api/v1/oversight").json()["projects"]}  # own workspace only
    assert env.client.get("/api/v1/oversight").status_code == 403


def test_direct_messages_reach_only_the_two_people(env):
    analyst, ah = env.holder("business_analyst")
    architect, _ = env.holder("solution_architect")
    designer, _ = env.holder("ui_ux_designer")
    admin, adh, admin_id = _overseer(env, "org_admin")
    manager, _, manager_id = _overseer(env, "project_manager")
    _owner_only(env)
    target = _id_of(analyst, profile="solution_architect")
    r = analyst.post("/api/v1/team-chat/messages", headers=ah,
                     json={"channel": "general", "body": "Can we use a queue?", "to": target})
    assert r.status_code == 201 and r.json()["direct"] and r.json()["to"] == "Colleague"
    seen = architect.get("/api/v1/team-chat/messages/general").json()["items"][-1]
    assert seen["direct"] and seen["mentions_me"] and seen["body"] == "Can we use a queue?"
    assert all(not m["direct"] for m in designer.get("/api/v1/team-chat/messages/general").json()["items"])
    assert any("sent you a direct message" in n for n in _notices(architect))
    assert analyst.post("/api/v1/team-chat/messages", headers=ah,
                        json={"channel": "general", "body": "Hello everyone"}).status_code == 201
    assert designer.get("/api/v1/team-chat/messages/general").json()["items"][-1]["body"] == "Hello everyone"
    # The owner talks only with project managers and administrators, directly.
    owner_people = {p["kind"] for p in env.client.get("/api/v1/team-chat/people").json()["items"] if not p["is_you"]}
    assert owner_people == {"admin", "manager"}
    assert env.client.get("/api/v1/team-chat/messages/general").status_code == 404
    assert env.client.post("/api/v1/team-chat/messages", headers=env.h,
                           json={"channel": "general", "body": "hi"}).status_code == 403
    assert env.client.post("/api/v1/team-chat/messages", headers=env.h,
                           json={"channel": "general", "body": "hi", "to": target}).status_code == 422
    assert env.client.post("/api/v1/team-chat/messages", headers=env.h,
                           json={"channel": "general", "body": "Any update?", "to": str(manager_id)}).status_code == 201
    assert manager.get("/api/v1/team-chat/messages/general").json()["items"][-1]["body"] == "Any update?"
    assert admin.post("/api/v1/team-chat/messages", headers=adh,
                      json={"channel": "direct", "body": "Thanks", "to": str(env.owner)}).status_code == 201
    assert [m["body"] for m in env.client.get("/api/v1/team-chat/messages/direct").json()["items"]] == \
        ["Any update?", "Thanks"]
    assert admin.post("/api/v1/team-chat/messages", headers=adh,
                      json={"channel": "direct", "body": "hi", "to": target}).status_code == 422  # not in team chats
    assert analyst.post("/api/v1/team-chat/messages", headers=ah,
                        json={"channel": "general", "body": "hi", "to": str(admin_id)}).status_code == 422


def test_project_discussions_stay_in_department_workspaces(env):
    analyst, ah = env.holder("business_analyst")
    architect, _ = env.holder("solution_architect")
    _owner_only(env)
    assert [c["key"] for c in analyst.get(env.base + "/scope").json()["channels"]] == ["business_analyst"]
    assert env.client.get(env.base + "/team-chat/business_analyst").status_code == 404
    assert analyst.get(env.base + "/team-chat/solution_architect").status_code == 404
    people = {p["name"]: p for p in analyst.get(env.base + "/people").json()["items"]}
    target = next(p for p in people.values() if p["profiles"] == ["solution_architect"])
    assert analyst.post(env.base + "/team-chat", headers=ah, json={
        "channel": "business_analyst", "body": "Please check the data rules", "mentions": [target["user_id"]]
    }).status_code == 201
    assert any("mentioned you in Business Analyst on Hiring hub" in n for n in _notices(architect))


def test_an_owner_who_also_administers_gets_the_owner_view_of_their_project(env):
    scope = env.client.get(env.base + "/scope").json()
    assert scope["kind"] == "owner" and scope["channels"] == []


def test_a_question_the_ai_can_answer_is_resolved_and_can_be_reopened(env):
    analyst, _ = env.holder("business_analyst")
    _owner_only(env)
    env.start()
    env.model.extra = {"decision": "answer", "reply": "Recruiters review candidates first."}
    r = env.post("/tickets", {"title": "Who reviews first?", "body": "Who looks at applications first?",
                              "kind": "question", "profile": "business_analyst"})
    assert r.status_code == 201
    ticket = env.get(f"/tickets/{r.json()['id']}")
    assert ticket["status"] == "ai_resolved" and ticket["comments"][-1]["author_type"] == "ai"
    assert ticket["comments"][-1]["body"] == "Recruiters review candidates first."
    assert any("was answered" in n for n in _notices(env.client))
    reopened = env.post(f"/tickets/{ticket['id']}/actions", {"action": "reopen", "note": "Not quite."}).json()
    assert reopened["status"] == "awaiting_professional"
    assert any("was reopened" in n for n in _notices(analyst))


def test_a_change_waits_for_the_professional_who_sends_it_to_the_ai(env):
    analyst, ah = env.holder("business_analyst")
    _owner_only(env)
    env.start()
    first = env.item(FIRST)["current_version_id"]
    env.model.extra = {"decision": "answer", "reply": "Done", "proposal": "Add a reporting section."}
    r = env.post("/tickets", {"title": "Add reporting", "body": "We need reports.", "kind": "change",
                              "profile": "business_analyst"}).json()
    owner_view = env.get(f"/tickets/{r['id']}")
    assert owner_view["status"] == "awaiting_professional" and owner_view["ai_proposal"] is None
    assert any("needs your decision" in n for n in _notices(analyst))
    pro_view = env.get(f"/tickets/{r['id']}", analyst)
    assert pro_view["ai_proposal"] == "Add a reporting section." and pro_view["can_act"]
    assert env.post(f"/tickets/{r['id']}/actions", {"action": "approve_proposal"}).status_code == 403
    done = env.post(f"/tickets/{r['id']}/actions", {"action": "approve_proposal"}, analyst, ah).json()
    assert done["status"] == "resolved" and "Sent to the AI" in done["comments"][-1]["body"]
    item = env.item(FIRST, analyst)
    assert item["current_version_id"] != first  # the AI produced a new version from the approved change
    assert "Add a reporting section." in env.model.lead_requests()[-1]["user"]


def test_tickets_wait_safely_when_the_ai_cannot_help(env):
    analyst, _ = env.holder("business_analyst")
    architect, _ = env.holder("solution_architect")
    _owner_only(env)
    env.start()
    env.model.extra = {"decision": "answer", "reply": "The gpt-4 agent handled it."}
    unsafe = env.post("/tickets", {"title": "Status?", "body": "Where are we?", "kind": "question",
                                   "profile": "business_analyst"}).json()
    assert env.get(f"/tickets/{unsafe['id']}")["status"] == "awaiting_professional"
    env.model.down = True
    down = env.post("/tickets", {"title": "Another", "body": "Help", "kind": "question",
                                 "profile": "business_analyst"}).json()
    assert "could not review" in env.get(f"/tickets/{down['id']}")["comments"][-1]["body"]
    assert architect.get(f"{env.base}/tickets/{down['id']}").status_code == 404  # other departments cannot see it
    assert [t["number"] for t in env.get("/tickets", analyst)["items"]] == [2, 1]
    assert env.get("/tickets", architect)["items"] == []


def test_department_status_explains_blockers_plainly(env):
    analyst, _ = env.holder("business_analyst")
    _owner_only(env)
    env.model.down = True
    env.start()
    pro = analyst.get(env.base + "/departments/business_analyst/status").json()
    step = pro["steps"][0]
    assert step["status"] == "FAILED" and step["note"] == "The AI service could not be reached."
    assert pro["issues"][0]["kind"] == "blocked"
    owner = env.get("/departments/business_analyst/status")
    assert owner["steps"][0]["note"] == "The AI could not finish this step."
    channel = analyst.get(env.base + "/team-chat/business_analyst").json()["items"]
    assert channel[-1]["author_type"] == "system" and "could not be reached" in channel[-1]["body"]
    env.model.down = False
    env.post(f"/stages/{FIRST}/retry")
    waiting = analyst.get(env.base + "/departments/business_analyst/status").json()["steps"][0]
    assert waiting["note"].startswith("Waiting for approval from Colleague")


def test_unassigned_departments_are_flagged(env):
    _owner_only(env)
    env.start()
    status = env.get("/departments/business_analyst/status")
    assert status["issues"][0]["kind"] == "unassigned"


def test_owner_messages_ping_the_department_and_professionals_can_reply(env):
    analyst, ah = env.holder("business_analyst")
    architect, xh = env.holder("solution_architect")
    _owner_only(env)
    env.start()
    env.post("/messages", {"body": "Please keep it simple", "profile": "business_analyst"})
    assert any("The project owner wrote to Business Analyst" in n for n in _notices(analyst))
    assert analyst.post(env.base + "/messages/replies", headers=ah, json={
        "profile": "business_analyst", "body": "Noted, we will."}).status_code == 201
    assert architect.post(env.base + "/messages/replies", headers=xh, json={
        "profile": "business_analyst", "body": "Me too"}).status_code == 403
    last = env.get("/messages")["items"][-1]
    assert last["author_type"] == "professional" and last["from"] == "Colleague (Business Analyst)"
    assert env.get("/messages", architect)["items"] == []


def test_failure_reasons_are_translated():
    assert explain("provider failed: timeout", True) == "The AI service did not answer in time."
    assert explain("mandatory sensors not satisfied: secret_detection", True).endswith("secret_detection.")
    assert "secret" not in explain("mandatory sensors not satisfied: secret_detection", False)
