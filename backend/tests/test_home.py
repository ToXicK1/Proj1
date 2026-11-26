"""Home (the Home + Workspace split): one read of what waits on a person across their projects. Change sets they may
review (never their own, never work they asked the Developer AI for), tickets for them or their unassigned department
work, messages that name them, unread notifications, what the AI finished, and which workspaces they can open. Clients
see none of the team's material."""

from tests.test_devai import _team, checks, git  # noqa: F401  (fixtures)
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)


def test_home_shows_each_person_what_waits_on_them(managed, engine, git, checks, monkeypatch):  # noqa: F811
    from app.collab import service as collab

    monkeypatch.setattr(collab, "triage", lambda *a, **k: None)  # keep the tickets open: no AI triage here
    t = _team(managed, engine)
    (d, dh), (o, _), (client, _) = t["dev"], t["other"], t["client"]
    portal = f"/api/v1/portal/projects/{t['project']}"
    other = next(p["user_id"] for p in d.get(f"{portal}/people").json()["items"]
                 if "software_developer" in p["profiles"] and not p["is_you"])

    ai = f"{t['base']}/developer-ai"
    assert d.post(ai, headers=dh, json={"task": "Add numbers"}).status_code == 202  # runs inline: change set #1
    ticket = d.post(f"{portal}/tickets", headers=dh, json={
        "title": "Which rounding rule?", "body": "Please confirm.", "kind": "question",
        "profile": "software_developer", "assignee": other})
    assert ticket.status_code == 201, ticket.text
    mention = d.post(f"{portal}/team-chat", headers=dh, json={
        "channel": "software_developer", "body": "Can you review the AI's change?",
        "mentions": [other]})
    assert mention.status_code == 201, mention.text

    mine = d.get("/api/v1/me/day").json()
    assert mine["change_sets"] == []  # the requester is not a reviewer of the AI's change set
    assert mine["messages"] == []  # not their own message
    assert {"project_id": t["project"], "project": "Clinic booking"} == \
        {k: mine["workspaces"][0][k] for k in ("project_id", "project")}
    assert mine["workspaces"][0]["profiles"] == ["software_developer"]
    assert [u["kind"] for u in mine["ai_updates"]] == ["developer_ai.finished"]

    theirs = o.get("/api/v1/me/day").json()
    assert [(c["number"], c["by_ai"]) for c in theirs["change_sets"]] == [(1, True)]
    assert [x["title"] for x in theirs["tickets"]] == ["Which rounding rule?"]
    assert [m["body"] for m in theirs["messages"]] == ["Can you review the AI's change?"]
    assert theirs["notifications"]["unread"] >= 2  # the ticket and the mention

    outside = client.get("/api/v1/me/day").json()
    assert outside["change_sets"] == outside["tickets"] == outside["messages"] == outside["ai_updates"] == []
    assert outside["workspaces"] == []  # clients have the portal, not a workspace
