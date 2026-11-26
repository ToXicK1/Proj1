"""Phase 1 (RD-30): the executor runs each job in a fresh, locked-down container, re-validates every job, decides the
image and command itself, and never reports a pass it did not see. A fake Docker client records what was asked."""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import make_session_factory
from app.execution import executor
from app.execution import service as execution
from app.execution.models import ExecutionJob
from tests.helpers import signup_verify_login
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)

MARKER = executor.MARKER


class FakeContainer:
    def __init__(self, behaviour):
        self.behaviour, self.stdin, self.removed, self.killed = behaviour, b"", False, False

    def put_archive(self, path, data):
        import io
        import tarfile

        assert path == "/job"
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            self.stdin = archive.extractfile("job.json").read()

    def start(self):
        pass

    def wait(self, timeout):
        if self.behaviour == "hang":
            raise TimeoutError("read timed out")
        return {"StatusCode": 0}

    def kill(self):
        self.killed = True

    def logs(self, stdout, stderr):
        if self.behaviour == "silent":
            return b"Segmentation fault\n"
        job = json.loads(self.stdin)
        result = {"status": "completed", "language": "python",
                  "checks": {"build": {"passed": True}, "unit_tests": {"passed": True, "summary": "Tests: 1 passed"}},
                  "files_seen": len(job["files"])}
        return f"collected 1 item\n{MARKER}{json.dumps(result)}\n".encode()

    def remove(self, force, v):
        self.removed = force and v  # the container and its throwaway job volume


class FakeDocker:
    def __init__(self, behaviour="ok"):
        self.behaviour, self.created, self.containers = behaviour, [], self

    def create(self, image, command, **options):
        self.created.append({"image": image, "command": command, **options})
        self.last = FakeContainer(self.behaviour)
        return self.last


def _project(client, engine):
    csrf = signup_verify_login(client, engine, f"exec-{uuid.uuid4().hex[:8]}@example.com")
    org = client.get("/api/v1/orgs").json()["items"][0]["id"]
    project = client.post(f"/api/v1/orgs/{org}/projects", headers={"X-CSRF-Token": csrf}, json={
        "name": "Executor test", "description": "", "project_type": "Web Application"}).json()["id"]
    return uuid.UUID(org), uuid.UUID(project)


def _queue(client, engine, kind="checks", payload=None):
    org, project = _project(client, engine)
    factory = make_session_factory(engine)
    with factory() as db:
        job = execution.submit(db, organization_id=org, project_id=project, kind="checks",
                               payload=payload or {"files": [{"path": "app.py", "content": "x = 1\n"},
                                                             {"path": "test_app.py", "content": "def test(): pass\n"}]})
        if kind != "checks":
            job.kind = kind  # what a tampered row would look like: the executor must refuse it
        db.commit()
        return factory, job.id


def test_a_job_runs_in_a_locked_down_container_chosen_by_the_executor(client, engine):
    factory, job_id = _queue(client, engine)
    assert executor.claim(factory, "test-executor") == job_id
    docker = FakeDocker()
    executor.process(factory, docker, job_id)
    made = docker.created[0]
    assert made["image"] == executor.RUNNER_IMAGE and made["command"] == ["python", "/opt/runner/job.py"]
    assert made["network_disabled"] and made["network_mode"] == "none" and made["read_only"]
    assert made["cap_drop"] == ["ALL"] and set(made["cap_add"]) == {"CHOWN", "SETUID", "SETGID"}
    assert made["security_opt"] == ["no-new-privileges:true"] and made["pids_limit"] == 128
    assert made["mem_limit"] == "768m" and made["environment"] == {}  # no secrets, nothing inherited
    assert "volumes" not in made  # nothing from the host
    assert [(m["Target"], m["Type"], m.get("Source")) for m in made["mounts"]] == [("/job", "volume", None)]
    assert docker.last.removed  # always removed
    sent = json.loads(docker.last.stdin)
    assert sent["kind"] == "checks" and len(sent["files"]) == 2
    with Session(engine) as db:
        job = db.get(ExecutionJob, job_id)
        assert job.status == "succeeded" and job.result["files_seen"] == 2 and job.limits["network"] == "none"
        assert MARKER not in job.output and "collected 1 item" in job.output


def test_the_executor_refuses_what_it_does_not_know(client, engine):
    factory, job_id = _queue(client, engine, kind="shell")
    executor.claim(factory, "test-executor")
    docker = FakeDocker()
    executor.process(factory, docker, job_id)
    assert docker.created == []  # nothing started
    with Session(engine) as db:
        job = db.get(ExecutionJob, job_id)
        assert job.status == "rejected" and job.failure == "unknown job kind"


def test_no_result_is_never_a_pass(client, engine):
    for behaviour, expected in (("silent", "error"), ("hang", "timed_out")):
        factory, job_id = _queue(client, engine)
        executor.claim(factory, "test-executor")
        docker = FakeDocker(behaviour)
        executor.process(factory, docker, job_id)
        with Session(engine) as db:
            job = db.get(ExecutionJob, job_id)
            assert job.status == expected and job.result == {} and job.failure
        assert docker.last.removed and (behaviour != "hang" or docker.last.killed)


def test_only_known_kinds_can_be_queued(client, engine):
    org, project = _project(client, engine)
    factory = make_session_factory(engine)
    with factory() as db:
        try:
            execution.submit(db, organization_id=org, project_id=project, kind="shell", payload={})
            raise AssertionError("a shell job was accepted")
        except execution.AppError as exc:
            assert exc.code == "unknown_job_kind"


def test_only_engineers_queue_executions_not_even_administrators(managed, engine):  # noqa: F811
    from tests.test_pm import _setup, _signed_in

    c, h, _, project, people = _setup(managed, engine)
    c.put(f"/api/v1/projects/{project}/manager", headers=h, json={"user_id": people["pm"]["user"]["id"]})
    job = {"kind": "checks", "payload": {"files": [{"path": "a.py", "content": "x = 1\n"}]}}
    url = f"/api/v1/projects/{project}/executions"
    analyst, ah = _signed_in(managed, people["analyst"])
    queued = analyst.post(url, headers=ah, json=job)
    assert queued.status_code == 202, queued.text
    assert queued.json()["status"] == "queued"
    assert analyst.get(f"{url}/{queued.json()['id']}").json()["kind"] == "checks"
    for who in ("client", "pm"):
        person, ph = _signed_in(managed, people[who])
        assert person.post(url, headers=ph, json=job).status_code in (403, 404)
    assert c.post(url, headers=h, json=job).status_code == 403  # administrators oversee; code is the engineers'
    assert c.get(f"{url}/{queued.json()['id']}").status_code == 403
    assert analyst.post(url, headers=ah, json={"kind": "shell", "payload": {}}).status_code == 422
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from audit_events where event_type = 'execution.requested'")
                            ).scalar_one() == 1
