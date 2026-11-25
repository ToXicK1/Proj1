"""The executor service (Phase 1, RD-30): the only process that talks to Docker.

It claims queued execution jobs from the database and runs each one in a fresh container started from an allowlisted
image, with the template's fixed command, no network, a read-only root, all capabilities dropped except the three the
runner needs to switch to an unprivileged user, and CPU, memory, process and time limits. The job's input goes in on
standard input; the result comes back after a marker on standard output. The container is always removed.

What runs is decided here, from the job's kind: the caller can never choose an image, a command or a mount. The
executor gets only the database URL: no signing key, no encryption key, no provider keys.

Run with: python -m app.execution.executor
"""

import io
import json
import logging
import os
import pathlib
import shutil
import signal
import socket
import tarfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 - every table, so the job's foreign keys resolve
from app.core.db import make_engine, make_session_factory
from app.execution.models import ExecutionJob

log = logging.getLogger("aidlc.executor")
MARKER = "@@AIDLC-RESULT@@"
OUTPUT_LIMIT = 16_000


@dataclass(frozen=True)
class Template:
    image: str
    command: tuple[str, ...]
    timeout_seconds: int
    memory: str = "768m"
    cpus: float = 1.0
    pids: int = 128
    work_mb: int = 128
    caps: tuple[str, ...] = ("CHOWN", "SETUID", "SETGID")
    env: dict[str, str] = field(default_factory=dict)
    user: str = ""  # empty: the image's default (root, which then drops to the unprivileged user itself)
    repo: str = "none"  # none, read (the project repository is copied in) or write (and copied back afterwards)


RUNNER_IMAGE = os.environ.get("AIDLC_RUNNER_IMAGE", "aidlc-runner:latest")
REPOS = pathlib.Path(os.environ.get("AIDLC_REPOS_DIR", "/repos"))  # only the executor mounts this
_GIT = ("python", "/opt/runner/gitjob.py")
TEMPLATES: dict[str, Template] = {
    # Build and unit tests of generated files: the sandbox's vetted checks, one container per job.
    "checks": Template(image=RUNNER_IMAGE, command=("python", "/opt/runner/job.py"), timeout_seconds=180),
    # Git operations on the project's repository (Phase 1b): the job hands /repo to the unprivileged user and drops
    # to it before any git command; hooks are disabled.
    "git.init": Template(RUNNER_IMAGE, _GIT, 60, repo="write"),
    "git.commit": Template(RUNNER_IMAGE, _GIT, 60, repo="write"),
    "git.merge": Template(RUNNER_IMAGE, _GIT, 60, repo="write"),
    "git.read": Template(RUNNER_IMAGE, _GIT, 60, repo="read"),
    "git.diff": Template(RUNNER_IMAGE, _GIT, 60, repo="read"),
    "git.log": Template(RUNNER_IMAGE, _GIT, 60, repo="read"),
}


def validate(kind: str, payload: dict[str, Any]) -> str | None:
    """The executor checks every job again; the API's checks are not trusted here."""
    if kind not in TEMPLATES:
        return "unknown job kind"
    if kind == "checks":
        files = payload.get("files")
        if not isinstance(files, list) or not files or len(files) > 100:
            return "checks need 1 to 100 files"
        if any(not isinstance(f, dict) or not isinstance(f.get("path"), str) or not isinstance(f.get("content"), str)
               for f in files):
            return "each file needs a path and text content"
        if len(json.dumps(payload)) > 3_000_000:
            return "the job is too large"
    if kind.startswith("git."):
        if "repo" in payload or "path" in payload:
            return "a git job cannot name a repository or a path on the host"
        if len(json.dumps(payload)) > 3_000_000:
            return "the job is too large"
    return None


def claim(factory: sessionmaker[Session], worker: str) -> uuid.UUID | None:
    with factory() as db:
        job = db.execute(select(ExecutionJob).where(ExecutionJob.status == "queued")
                         .order_by(ExecutionJob.created_at).with_for_update(skip_locked=True).limit(1)
                         ).scalar_one_or_none()
        if job is None:
            return None
        job.status, job.started_at, job.claimed_by = "running", datetime.now(UTC), worker
        from app.events.service import publish

        publish(db, organization_id=job.organization_id, project_id=job.project_id, kind="execution.started",
                subject=str(job.id), actor="executor", data={"kind": job.kind})
        db.commit()
        return job.id


def _finish(factory: sessionmaker[Session], job_id: uuid.UUID, **values: Any) -> None:
    with factory() as db:
        job = db.get(ExecutionJob, job_id)
        for key, value in values.items():
            setattr(job, key, value)
        job.finished_at = datetime.now(UTC)
        from app.events.service import publish

        summary = (job.result or {}).get("checks", {}).get("unit_tests", {}).get("summary") or job.failure
        publish(db, organization_id=job.organization_id, project_id=job.project_id, kind="execution.finished",
                subject=str(job.id), actor="executor",
                data={"kind": job.kind, "status": job.status, "summary": str(summary or "")[:200]})
        db.commit()


def _completed(output: str) -> bool:
    try:
        return MARKER in output and json.loads(
            output.rsplit(MARKER, 1)[1].strip().splitlines()[0]).get("status") == "completed"
    except (ValueError, IndexError):
        return False


def _job_archive(job_input: dict[str, Any]) -> bytes:
    data = json.dumps(job_input).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("job.json")
        info.size, info.mode = len(data), 0o444
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _repo_archive(project_dir: pathlib.Path) -> bytes:
    """The project's bare repository as a tar owned by the unprivileged user (an empty folder before git.init)."""
    buffer = io.BytesIO()

    def owned(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 2000
        info.uname = info.gname = ""
        return info

    with tarfile.open(fileobj=buffer, mode="w") as archive:
        source = project_dir / "project.git"
        if source.exists():
            archive.add(source, arcname="project.git", filter=owned)
        else:
            folder = tarfile.TarInfo("project.git")
            folder.type, folder.mode = tarfile.DIRTYPE, 0o700
            archive.addfile(owned(folder))
    return buffer.getvalue()


def _store_repo(project_dir: pathlib.Path, stream: Any) -> None:
    """Replaces the stored repository with the one the job wrote. The archive comes from an untrusted container:
    Python's 'data' filter refuses absolute paths, '..', links outside the folder and device files."""
    incoming = project_dir / f".incoming-{uuid.uuid4().hex}"
    incoming.mkdir(parents=True)
    try:
        raw = b"".join(stream)
        if len(raw) > 500_000_000:
            raise ValueError("the repository is too large")
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(incoming, filter="data")
        if not (incoming / "project.git" / "HEAD").exists():
            raise ValueError("the job did not leave a repository")
        old = project_dir / "project.git"
        retired = project_dir / f".retired-{uuid.uuid4().hex}"
        if old.exists():
            old.rename(retired)
        (incoming / "project.git").rename(old)
        shutil.rmtree(retired, ignore_errors=True)
    finally:
        shutil.rmtree(incoming, ignore_errors=True)


def run_container(client: Any, template: Template, job_input: dict[str, Any], label: str,
                  project_dir: pathlib.Path | None = None) -> tuple[int | None, str, dict[str, Any] | None, bool]:
    """Returns (exit code, output, parsed result, timed out). Always removes the container and its job volume.

    The job goes in as /job/job.json on a throwaway volume created with the container (the root stays read-only);
    the result comes back after a marker on standard output."""
    from docker.types import Mount

    container = client.containers.create(
        template.image, list(template.command), detach=True, network_disabled=True, network_mode="none",
        read_only=True, mem_limit=template.memory, memswap_limit=template.memory,
        nano_cpus=int(template.cpus * 1e9), pids_limit=template.pids, cap_drop=["ALL"], cap_add=list(template.caps),
        security_opt=["no-new-privileges:true"], init=True, environment=dict(template.env),
        mounts=[Mount(target="/job", source=None, type="volume"),
                *([Mount(target="/repo", source=None, type="volume")] if template.repo != "none" else [])],
        user=template.user or None,
        tmpfs={"/work": f"size={template.work_mb}m,mode=0711,nosuid,nodev,noexec",
               "/tmp": "size=32m,mode=1777,nosuid,nodev,noexec"},
        labels={"aidlc.execution-job": label})
    timed_out = False
    try:
        container.put_archive("/job", _job_archive(job_input))
        if template.repo != "none" and project_dir is not None:
            container.put_archive("/repo", _repo_archive(project_dir))
        container.start()
        try:
            status = container.wait(timeout=template.timeout_seconds)
            code: int | None = int(status.get("StatusCode", -1))
        except Exception:  # noqa: BLE001 - the docker client raises a requests timeout here
            timed_out, code = True, None
            container.kill()
        output = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
        if template.repo == "write" and project_dir is not None and not timed_out and code == 0 \
                and _completed(output):
            stream, _ = container.get_archive("/repo/project.git")
            _store_repo(project_dir, stream)
    finally:
        try:
            container.remove(force=True, v=True)  # v: the job volume goes too
        except Exception:  # noqa: BLE001
            log.warning("could not remove container for job %s", label)
    result = None
    if MARKER in output:
        try:
            result = json.loads(output.rsplit(MARKER, 1)[1].strip().splitlines()[0])
        except (ValueError, IndexError):
            result = None
        output = output.rsplit(MARKER, 1)[0]
    return code, output[-OUTPUT_LIMIT:], result, timed_out


class ProjectLock:
    """One write at a time per repository, across executors (a Postgres advisory lock held for the job)."""

    def __init__(self, factory: sessionmaker[Session], project_id: uuid.UUID, needed: bool) -> None:
        self.factory, self.key, self.needed, self.db = factory, project_id.int & 0x7FFFFFFFFFFFFFFF, needed, None

    def __enter__(self) -> None:
        if self.needed:
            self.db = self.factory()
            self.db.execute(text("select pg_advisory_lock(:k)"), {"k": self.key})

    def __exit__(self, *_: object) -> None:
        if self.db is not None:
            self.db.execute(text("select pg_advisory_unlock(:k)"), {"k": self.key})
            self.db.close()


def process(factory: sessionmaker[Session], client: Any, job_id: uuid.UUID) -> None:
    with factory() as db:
        job = db.get(ExecutionJob, job_id)
        kind, payload, project_id = job.kind, dict(job.payload), job.project_id
    problem = validate(kind, payload)
    if problem:
        _finish(factory, job_id, status="rejected", failure=problem)
        return
    template = TEMPLATES[kind]
    limits = {"memory": template.memory, "cpus": template.cpus, "pids": template.pids, "network": "none",
              "timeout_seconds": template.timeout_seconds, "read_only_root": True}
    project_dir = REPOS / str(project_id) if template.repo != "none" else None  # from the job's row, never its input
    try:
        with ProjectLock(factory, project_id, template.repo == "write"):
            code, output, result, timed_out = run_container(client, template, {"kind": kind, **payload}, str(job_id),
                                                            project_dir)
    except Exception as exc:  # noqa: BLE001 - Docker unavailable, image missing: an error, never a pass
        _finish(factory, job_id, status="error", image=template.image, limits=limits,
                failure=f"{type(exc).__name__}: {str(exc)[:300]}")
        return
    if timed_out:
        status, result = "timed_out", None  # whatever it printed before it was stopped is not a result
    elif result is None:
        status = "error"
    else:
        status = "succeeded" if result.get("status") == "completed" else "failed"
    _finish(factory, job_id, status=status, image=template.image, limits=limits, exit_code=code, output=output,
            result=result or {}, failure="" if result else ("timed out" if timed_out else "no result was produced"))


def main() -> None:  # pragma: no cover - the service loop; process() is what the tests cover
    import docker

    logging.basicConfig(level=logging.INFO)
    factory = make_session_factory(make_engine(os.environ["AIDLC_DATABASE_URL"]))
    client = docker.from_env(timeout=300)
    worker = f"executor-{socket.gethostname()}-{os.getpid()}"
    stopping = False

    def stop(*_: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    log.info("executor %s ready", worker)
    last_beat = 0.0
    while not stopping:
        if time.monotonic() - last_beat > 15:  # the registry shows executor tools as reachable while this beats
            try:
                from app.tools.registry import report_executor_alive

                with factory() as db:
                    report_executor_alive(db)
                    db.commit()
                last_beat = time.monotonic()
            except Exception:  # noqa: BLE001 - the registry may not exist yet (migrations)
                log.warning("could not report health")
        try:
            job_id = claim(factory, worker)
        except Exception:
            log.exception("could not claim a job; retrying")
            time.sleep(5)
            continue
        if job_id is None:
            time.sleep(0.5)
            continue
        log.info("running job %s", job_id)
        process(factory, client, job_id)


if __name__ == "__main__":
    main()
