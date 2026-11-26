"""Phase 2e: the Developer AI. A developer gives it a story; it reads the repository, plans, commits to its own branch,
builds and tests, repairs real failures at most twice, and opens a change set that neither it nor the person who asked
can approve. Unsafe or credential-bearing output is never committed; grants and the tool registry are checked before
every tool use; cancellation and a lost worker end a run plainly. Git and the executor are simulated (the real path is
demonstrated on the test stack); the model is the offline mock provider unless a test scripts the replies."""

import hashlib
import itertools
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core.db import make_session_factory
from app.core.errors import AppError
from app.devai import service as devai
from app.devai.models import DeveloperAiRun
from app.portal import lifecycle
from app.providers import service as providers
from app.repos import service as repos
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _person, _setup, _signed_in


class FakeRepo:
    """The executor's git jobs over an in-memory repository, recording every call."""

    def __init__(self):
        self.branches: dict[str, dict[str, str]] = {}
        self.heads: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []
        self.counter = itertools.count(1)

    def _sha(self):
        return hashlib.sha1(str(next(self.counter)).encode()).hexdigest()

    def __call__(self, db, factory, project, user, kind, payload):
        self.calls.append((kind, payload))
        if kind == "git.init":
            self.branches["main"], self.heads["main"] = {"README.md": "# Project\n"}, self._sha()
            return {"commit": self.heads["main"]}
        if kind == "git.read":
            ref = payload.get("ref") or "main"
            files = self.branches[ref]
            out = {"ref": ref, "commit": self.heads[ref],
                   "tree": [{"path": p, "sha": "x", "size": len(c)} for p, c in sorted(files.items())], "files": []}
            for path in payload.get("paths") or []:
                out["files"].append({"path": path, "content": files[path]} if path in files
                                    else {"path": path, "missing": True})
            return out
        if kind == "git.commit":
            assert payload["branch"] != "main", "never the default branch"
            branch = payload["branch"]
            before = dict(self.branches.get(branch) or self.branches[payload.get("base") or "main"])
            after = {**before, **{f["path"]: f["content"] for f in payload["files"]}}
            if branch in self.branches and after == self.branches[branch]:
                raise AppError(409, "git_failed", "nothing changed")
            self.branches[branch], self.heads[branch] = after, self._sha()
            return {"branch": branch, "commit": self.heads[branch], "changed": [f["path"] for f in payload["files"]]}
        if kind == "git.diff":
            base, head = self.branches["main"], self.branches[payload["head"]]
            changed = [p for p in head if base.get(p) != head[p]]
            return {"merge_base": self.heads["main"], "head_commit": self.heads[payload["head"]],
                    "files": [{"path": p, "added": 1, "removed": 0} for p in changed], "patch": ""}
        if kind == "git.merge":
            assert payload["expected_head"] == self.heads[payload["branch"]]
            self.branches["main"], self.heads["main"] = dict(self.branches[payload["branch"]]), self._sha()
            return {"merged": self.heads["main"]}
        raise AssertionError(kind)


@pytest.fixture
def git(monkeypatch):
    fake = FakeRepo()
    monkeypatch.setattr(repos, "_run", fake)
    return fake


class FakeChecks:
    def __init__(self, results=("pass",)):
        self.results, self.calls = list(results), []

    def __call__(self, db, factory, project, requester, files):
        self.calls.append([f["path"] for f in files])
        outcome = self.results.pop(0) if self.results else "pass"
        ok = outcome == "pass"
        return {"checks": {"build": {"passed": True, "summary": "built"},
                           "unit_tests": {"passed": ok, "summary": "Tests: 1 passed" if ok else "Tests: 1 failed",
                                          "output": "" if ok else "AssertionError: add(2, 3) returned 6"}},
                "job_id": str(uuid.uuid4())}


@pytest.fixture
def checks(monkeypatch):
    fake = FakeChecks()
    monkeypatch.setattr(devai, "_checks", fake)
    return fake


def _team(managed, engine):  # noqa: F811
    c, h, org, project, people = _setup(managed, engine)
    dev = _person(c, h, org, "dee@example.com", "member", ["software_developer"])
    other = _person(c, h, org, "rio@example.com", "member", ["software_developer"])
    with Session(engine) as db:
        admin = db.execute(select(User).where(User.email == "root@example.com")).scalar_one()
        provider = providers.create_provider(db, managed.state.settings, admin, organization_id=uuid.UUID(org),
                                             name="offline", adapter_type="mock", base_url=None, api_key=None)
        providers.create_route(db, admin, organization_id=uuid.UUID(org), key="default",
                               primary_provider_id=provider.id, primary_model="mock-model", fallbacks=[])
        lifecycle.provision(db, admin, uuid.UUID(org), "default")
        db.commit()
    d, dh = _signed_in(managed, dev)
    o, oh = _signed_in(managed, other)
    analyst, ah = _signed_in(managed, people["analyst"])
    client, ch = _signed_in(managed, people["client"])
    base = f"/api/v1/projects/{project}"
    assert d.post(f"{base}/repository", headers=dh).status_code == 201
    story = analyst.post(f"{base}/work/business_analyst/items", headers=ah, json={
        "kind": "user_story", "title": "Add two numbers",
        "body": {"role": "clinic clerk", "want": "to add two numbers", "acceptance_criteria": ["2 + 3 is 5"]}})
    assert story.status_code == 201, story.text
    return {"base": base, "dev": (d, dh), "other": (o, oh), "analyst": (analyst, ah), "client": (client, ch),
            "admin": (c, h), "org": org, "project": project, "story": story.json()["id"]}


def _scripted(monkeypatch, replies):
    replies = list(replies)

    def ask(db, settings, transport, row, project, version, repository, story, failures):
        reply = replies.pop(0)
        return reply(repository, story, failures) if callable(reply) else reply

    monkeypatch.setattr(devai, "_ask_model", ask)


GOOD = [{"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
        {"path": "test_calc.py", "content": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"}]


def test_the_developer_ai_implements_a_story_and_someone_else_reviews_it(managed, engine, git, checks):  # noqa: F811
    t = _team(managed, engine)
    (d, dh), (o, oh) = t["dev"], t["other"]
    ai = f"{t['base']}/developer-ai"
    assert [s["key"] for s in d.get(f"{ai}/stories").json()["items"]] == ["US-001"]
    started = d.post(ai, headers=dh, json={"story_item_id": t["story"]})
    assert started.status_code == 202, started.text
    run = d.get(f"{ai}/{started.json()['id']}").json()  # the job ran inline after the response
    assert run["status"] == "in_review", run
    assert run["branch"] == "ai/dev-1" and run["attempts"] == 1 and run["checks_passed"] is True
    assert [s["step"] for s in run["steps"]] == ["started", "read", "plan", "commit", "checks", "change_set"]
    assert run["plan"] and run["story"]["key"] == "US-001"

    commits = [p for k, p in git.calls if k == "git.commit"]
    assert len(commits) == 1 and commits[0]["branch"] == "ai/dev-1" and commits[0]["base"] == "main"
    assert commits[0]["author"] == devai.AUTHOR  # the AI's own identity, never a person's
    assert {f["path"] for f in commits[0]["files"]} == {"calc.py", "test_calc.py"}  # the mock's project
    assert sorted(checks.calls[0]) == ["README.md", "calc.py", "test_calc.py"]  # the whole branch is tested

    sets = d.get(f"{t['base']}/repository/change-sets").json()["items"]
    assert len(sets) == 1 and sets[0]["author_user_id"] is None and sets[0]["developer_ai_run"]["number"] == 1
    cs = sets[0]
    assert "Developer AI" in cs["description"] and cs["id"] == run["change_set"]["id"]
    decision = f"{t['base']}/repository/change-sets/{cs['id']}/decision"
    mine = d.post(decision, headers=dh, json={"decision": "approve", "reviewed_sha": cs["head_sha"], "note": ""})
    assert mine.status_code == 403 and "asked the Developer AI" in mine.text  # the requester is not independent
    theirs = o.post(decision, headers=oh, json={"decision": "approve", "reviewed_sha": cs["head_sha"], "note": ""})
    assert theirs.status_code == 200, theirs.text
    merged = o.post(f"{t['base']}/repository/change-sets/{cs['id']}/merge", headers=oh)
    assert merged.status_code == 200 and merged.json()["status"] == "merged"
    assert git.branches["main"]["calc.py"] == GOOD[0]["content"]

    with engine.connect() as conn:
        events = conn.execute(text("select event_type, actor_type, actor_id from audit_events where event_type like "
                                   "'developer_ai.%' or event_type like 'change_set.%' order by seq")).all()
        runs = conn.execute(text("select count(*) from agent_runs where task = 'developer_ai'")).scalar_one()
    kinds = [(e, a) for e, a, _ in events]
    assert kinds[:4] == [("developer_ai.requested", "human"), ("developer_ai.committed", "ai_agent"),
                         ("developer_ai.checked", "ai_agent"), ("change_set.opened", "ai_agent")]
    assert ("change_set.approved", "human") in kinds and ("change_set.merged", "human") in kinds
    assert all(actor.startswith("developer-ai@v") for e, a, actor in events if a == "ai_agent")
    assert runs == 1  # the model call is on record like every other AI call


def test_real_failures_are_repaired_at_most_twice_and_then_reported(managed, engine, git, monkeypatch):  # noqa: F811
    t = _team(managed, engine)
    (d, dh) = t["dev"]
    ai = f"{t['base']}/developer-ai"
    seen = []

    def round_(n):
        def reply(repository, story, failures):
            seen.append(failures)
            return {"plan": f"round {n}", "commit_message": f"Round {n}", "notes": "",
                    "source_files": [{"path": "calc.py", "content": f"def add(a, b):\n    return a + b + {n}\n"},
                                     GOOD[1]]}
        return reply

    _scripted(monkeypatch, [round_(1), round_(2), round_(0)])
    monkeypatch.setattr(devai, "_checks", FakeChecks(("fail", "fail", "pass")))
    run = d.get(f"{ai}/{d.post(ai, headers=dh, json={'task': 'Add numbers'}).json()['id']}").json()
    assert run["status"] == "in_review" and run["attempts"] == 3
    assert seen[0] is None and "add(2, 3) returned 6" in seen[1]  # the real failure output, given back as data
    assert [s["step"] for s in run["steps"]].count("repair") == 2

    _scripted(monkeypatch, [round_(4), round_(5), round_(6)])
    monkeypatch.setattr(devai, "_checks", FakeChecks(("fail", "fail", "fail")))
    failing = d.get(f"{ai}/{d.post(ai, headers=dh, json={'task': 'Again'}).json()['id']}").json()
    assert failing["status"] == "checks_failed" and failing["change_set"] is None
    assert failing["branch"] == "ai/dev-2" and "ai/dev-2" in git.branches  # kept for a person to look at
    assert "still failed after 3 rounds" in failing["failure"]
    assert failing["checks_passed"] is False  # never reported as passing


@pytest.mark.parametrize("files, reason", [
    ([{"path": "../outside.py", "content": "x = 1\n"}], "unsafe path"),
    ([{"path": ".git/hooks/pre-commit", "content": "x"}], "unsafe path"),
    ([{"path": "config.py", "content": "API_KEY = 'sk-abcdefghijklmnopqrstuvwx'\n"}], "api key"),
    ([{"path": "a.py", "content": "x"}] * 2, "twice"),
    ([], "no files"),
])
def test_unsafe_or_credential_output_is_never_committed(managed, engine, git, checks, monkeypatch, files,  # noqa: F811
                                                        reason):
    t = _team(managed, engine)
    (d, dh) = t["dev"]
    _scripted(monkeypatch, [{"plan": "p", "commit_message": "m", "notes": "", "source_files": files}])
    ai = f"{t['base']}/developer-ai"
    run = d.get(f"{ai}/{d.post(ai, headers=dh, json={'task': 'Do it'}).json()['id']}").json()
    assert run["status"] == "failed" and reason in run["failure"].lower()
    assert not [k for k, _ in git.calls if k == "git.commit"] and checks.calls == []


def test_who_may_ask_and_the_registry_decides_what_runs(managed, engine, git, checks):  # noqa: F811
    t = _team(managed, engine)
    (d, dh), (analyst, ah), (client, ch), (admin, h) = t["dev"], t["analyst"], t["client"], t["admin"]
    ai = f"{t['base']}/developer-ai"
    assert analyst.post(ai, headers=ah, json={"task": "x"}).status_code == 403  # the BA is not a developer
    assert client.post(ai, headers=ch, json={"task": "x"}).status_code in (403, 404)
    assert d.post(ai, json={"task": "x"}).status_code == 403  # no CSRF token
    assert d.post(ai, headers=dh, json={"task": ""}).status_code == 422
    assert d.post(ai, headers=dh, json={"task": "x", "base_branch": "../main"}).status_code == 422

    off = admin.put(f"/api/v1/orgs/{t['org']}/tool-registry/run_checks", headers=h, json={"enabled": False})
    assert off.status_code == 200
    run = d.get(f"{ai}/{d.post(ai, headers=dh, json={'task': 'x'}).json()['id']}").json()
    assert run["status"] == "failed" and "disabled" in run["failure"]
    assert not [k for k, _ in git.calls if k == "git.commit"] and checks.calls == []  # stopped before any effect


def test_one_run_at_a_time_cancelling_and_a_lost_worker(managed, engine, git, checks):  # noqa: F811
    t = _team(managed, engine)
    (d, dh), (o, oh) = t["dev"], t["other"]
    ai = f"{t['base']}/developer-ai"
    factory = make_session_factory(engine)
    with factory() as db:
        dev = db.execute(select(User).where(User.email == "dee@example.com")).scalar_one()
        queued = devai.start(db, dev, uuid.UUID(t["project"]), task="Queued work", story_item_id=None,
                             base_branch="main")
        run_id = queued.id
    again = d.post(ai, headers=dh, json={"task": "More"})
    assert again.status_code == 409 and again.json()["code"] == "run_in_progress"
    assert o.post(f"{ai}/{run_id}/cancel", headers=oh).status_code == 403  # only the requester or an admin
    assert d.post(f"{ai}/{run_id}/cancel", headers=dh).json()["status"] == "cancelled"
    devai.run(factory, managed.state.settings, None, run_id)  # the queued job arrives after cancelling
    assert git.calls == [("git.init", git.calls[0][1])]  # nothing ran

    with factory() as db:
        lost = devai.start(db, dev, uuid.UUID(t["project"]), task="Lost", story_item_id=None, base_branch="main")
        lost.status = "working"  # a worker took it and then died
        db.commit()
        lost_id = lost.id
    devai.run(factory, managed.state.settings, None, lost_id)  # the job is delivered again
    with factory() as db:
        row = db.get(DeveloperAiRun, lost_id)
        assert row.status == "failed" and "start it again" in row.failure


def test_the_agent_is_provisioned_with_exactly_the_executor_grants(managed, engine, git):  # noqa: F811
    t = _team(managed, engine)
    from app.agents import service as agents

    with Session(engine) as db:
        version = agents.latest(db, uuid.UUID(t["org"]), devai.AGENT_KEY).version
        assert sorted(version.tools) == sorted(devai.TOOLS)
        assert "merge_change_set" not in version.tools
