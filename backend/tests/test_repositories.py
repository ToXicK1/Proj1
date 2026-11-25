"""Phase 1b: project repositories and change sets. The governance rules, with git results simulated (the real git
path runs in the executor and is demonstrated on the test stack): engineers only; never commit to the default branch;
nobody approves their own change set; approval binds to the reviewed commit; new commits make it stale; only the
approved commit is merged."""

import itertools

import pytest
from sqlalchemy import text

from app.core.errors import AppError
from app.repos import service as repos
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _person, _setup, _signed_in


class FakeGit:
    """Stands in for the executor's git jobs and records what was asked."""

    def __init__(self):
        self.branches, self.calls, self.counter = {}, [], itertools.count(1)

    def sha(self):
        return f"{next(self.counter):040x}"

    def __call__(self, db, factory, project, user, kind, payload):
        self.calls.append((kind, payload))
        if kind == "git.init":
            self.branches["main"] = self.sha()
            return {"commit": self.branches["main"]}
        if kind == "git.commit":
            assert payload["branch"] != "main"
            self.branches[payload["branch"]] = self.sha()
            return {"commit": self.branches[payload["branch"]], "changed": [f["path"] for f in payload["files"]]}
        if kind == "git.diff":
            return {"merge_base": self.branches["main"], "head_commit": self.branches[payload["head"]],
                    "files": [{"path": "calc.py", "added": 2, "removed": 0}]}
        if kind == "git.merge":
            if payload["expected_head"] != self.branches[payload["branch"]]:
                raise AppError(409, "git_failed", "the branch moved after it was approved")
            self.branches["main"] = self.sha()
            return {"merged": self.branches["main"]}
        return {}


@pytest.fixture
def git(monkeypatch):
    fake = FakeGit()
    monkeypatch.setattr(repos, "_run", fake)
    return fake


def _team(managed, engine):  # noqa: F811
    c, h, org, project, people = _setup(managed, engine)
    architect = _person(c, h, org, "sam@example.com", "member", ["solution_architect"])
    dev, dh = _signed_in(managed, people["analyst"])
    reviewer, rh = _signed_in(managed, architect)
    client, ch = _signed_in(managed, people["client"])
    return f"/api/v1/projects/{project}/repository", (dev, dh), (reviewer, rh), (client, ch)


def test_only_engineers_create_the_repository_once(managed, engine, git):  # noqa: F811
    url, (dev, dh), _, (client, ch) = _team(managed, engine)
    assert client.post(url, headers=ch).status_code in (403, 404)
    made = dev.post(url, headers=dh)
    assert made.status_code == 201, made.text
    assert made.json()["exists"] and made.json()["head_sha"] == git.branches["main"]
    assert dev.post(url, headers=dh).json()["code"] == "repository_exists"
    assert git.calls[0][0] == "git.init" and git.calls[0][1]["author"]["email"].endswith("@aidlc.local")


def test_a_change_set_is_approved_at_a_commit_and_merged_only_at_that_commit(managed, engine, git):  # noqa: F811
    url, (dev, dh), (reviewer, rh), _ = _team(managed, engine)
    dev.post(url, headers=dh)
    to_main = dev.post(f"{url}/commits", headers=dh, json={
        "branch": "main", "message": "x", "files": [{"path": "calc.py", "content": "x = 1\n"}]})
    assert to_main.status_code == 422  # the default branch changes only through an approved merge
    first = dev.post(f"{url}/commits", headers=dh, json={
        "branch": "feature/add", "message": "Add calc", "files": [{"path": "calc.py", "content": "x = 1\n"}]}).json()
    cs = dev.post(f"{url}/change-sets", headers=dh, json={"branch": "feature/add", "title": "Add calc"}).json()
    assert cs["status"] == "in_review" and cs["head_sha"] == first["commit"]
    decision = f"{url}/change-sets/{cs['id']}/decision"
    own = dev.post(decision, headers=dh, json={"decision": "approve", "reviewed_sha": cs["head_sha"]})
    assert own.status_code == 403 and own.json()["code"] == "separation_of_duties"
    assert reviewer.post(f"{url}/change-sets/{cs['id']}/merge", headers=rh).json()["code"] == "not_approved"
    approved = reviewer.post(decision, headers=rh, json={"decision": "approve", "reviewed_sha": cs["head_sha"]})
    assert approved.status_code == 200 and approved.json()["approved_sha"] == first["commit"]

    # A new commit after approval makes the approval stale; reviewing an old commit is refused.
    second = dev.post(f"{url}/commits", headers=dh, json={
        "branch": "feature/add", "message": "Tweak", "files": [{"path": "calc.py", "content": "x = 2\n"}]}).json()
    listed = dev.get(f"{url}/change-sets").json()["items"][0]
    assert listed["status"] == "in_review" and listed["head_sha"] == second["commit"]
    stale = reviewer.post(decision, headers=rh, json={"decision": "approve", "reviewed_sha": first["commit"]})
    assert stale.status_code == 409 and stale.json()["code"] == "stale_review"
    reviewer.post(decision, headers=rh, json={"decision": "approve", "reviewed_sha": second["commit"]})
    merged = reviewer.post(f"{url}/change-sets/{cs['id']}/merge", headers=rh)
    assert merged.status_code == 200, merged.text
    assert merged.json()["status"] == "merged" and merged.json()["merged_sha"] == git.branches["main"]
    assert git.calls[-1] == ("git.merge", {"branch": "feature/add", "expected_head": second["commit"],
                                           "author": git.calls[-1][1]["author"],
                                           "message": "Merge change set 1: Add calc"})
    assert dev.get(url).json()["head_sha"] == git.branches["main"]
    with engine.connect() as conn:
        events = [e for e in conn.execute(text("select event_type from audit_events order by id")).scalars()
                  if e.startswith(("repository.", "change_set."))]
    assert events == ["repository.created", "repository.committed", "change_set.opened", "change_set.approved",
                      "repository.committed", "change_set.approved", "change_set.merged"]


def test_asking_for_changes_needs_a_note_and_the_public_api_cannot_run_git(managed, engine, git):  # noqa: F811
    url, (dev, dh), (reviewer, rh), _ = _team(managed, engine)
    dev.post(url, headers=dh)
    dev.post(f"{url}/commits", headers=dh, json={"branch": "fix", "message": "Fix",
                                                 "files": [{"path": "calc.py", "content": "x = 3\n"}]})
    cs = dev.post(f"{url}/change-sets", headers=dh, json={"branch": "fix", "title": "Fix"}).json()
    decision = f"{url}/change-sets/{cs['id']}/decision"
    assert reviewer.post(decision, headers=rh, json={"decision": "request_changes",
                                                     "reviewed_sha": cs["head_sha"]}).status_code == 422
    asked = reviewer.post(decision, headers=rh, json={"decision": "request_changes", "note": "Add a test",
                                                      "reviewed_sha": cs["head_sha"]})
    assert asked.json()["status"] == "changes_requested"
    executions = url.replace("/repository", "/executions")
    sneaky = dev.post(executions, headers=dh, json={"kind": "git.merge", "payload": {"branch": "fix"}})
    assert sneaky.status_code == 422  # git runs only through the repository service and its approvals
