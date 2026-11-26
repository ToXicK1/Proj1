"""Project repositories and change sets (Phase 1b). Every git operation is an executor job; this module checks who
may do what, records outcomes and audits them. It never runs git itself.

Rules: work happens on branches (the default branch is never committed to directly); a change set is approved by an
engineering professional who is not its author, at the exact commit they reviewed; new commits after approval make
it stale; the default branch changes only by merging the approved commit.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.execution import service as execution
from app.repos.models import ChangeSet, Repository

BRANCH = re.compile(r"^(?!.*\.\.)(?!.*//)(?!/)(?!.*\.lock$)[A-Za-z0-9][A-Za-z0-9._/\-]{0,99}$")
WAIT_SECONDS = 90


def _audit(db: Session, project: Any, event: str, user: User, payload: dict) -> None:
    """Audited, and shown live in the workspaces (identifiers and commits only)."""
    from app.events.service import publish

    append_event(db, chain_key=org_chain(project.organization_id), event_type=event, actor_type="human",
                 actor_id=str(user.id), organization_id=project.organization_id, project_id=project.id,
                 payload=payload)
    publish(db, organization_id=project.organization_id, project_id=project.id, kind=event,
            subject=str(payload.get("change_set") or payload.get("branch") or ""), actor=f"user:{user.id}",
            data={k: v for k, v in payload.items() if k in ("branch", "commit", "head", "approved", "merged", "files")})


def _run(db: Session, factory: sessionmaker[Session], project: Any, user: User, kind: str,
         payload: dict[str, Any]) -> dict[str, Any]:
    """Queues one git job, waits for the executor, and returns its result or raises a plain error."""
    job = execution.submit(db, organization_id=project.organization_id, project_id=project.id, kind=kind,
                           payload=payload, user_id=user.id)
    db.commit()
    done = execution.wait(factory, job.id, WAIT_SECONDS)
    if done is None:
        raise AppError(503, "execution_unavailable", "The execution service did not answer; try again shortly")
    if done.status == "succeeded":
        return {**done.result, "job_id": str(done.id)}
    reason = (done.result or {}).get("error") or done.failure or done.status
    status = 409 if done.status == "failed" else 502
    raise AppError(status, "git_failed", str(reason)[:300], job_id=str(done.id))


def _repo(db: Session, project_id: uuid.UUID) -> Repository:
    repo = db.execute(select(Repository).where(Repository.project_id == project_id)).scalar_one_or_none()
    if repo is None or repo.status != "ready":
        raise AppError(404, "no_repository", "This project has no repository yet")
    return repo


def _author(user: User) -> dict[str, str]:
    return {"name": user.display_name, "email": f"user-{user.id}@aidlc.local"}  # never the person's real email


def repo_out(repo: Repository | None) -> dict[str, Any]:
    if repo is None:
        return {"exists": False}
    return {"exists": repo.status == "ready", "status": repo.status, "default_branch": repo.default_branch,
            "head_sha": repo.head_sha, "created_at": repo.created_at.isoformat() if repo.created_at else None}


def status(db: Session, user: User, project_id: uuid.UUID) -> dict[str, Any]:
    execution._allowed(db, user, project_id)
    return repo_out(db.execute(select(Repository).where(Repository.project_id == project_id)).scalar_one_or_none())


def create(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID) -> dict[str, Any]:
    project = execution._allowed(db, user, project_id)
    existing = db.execute(select(Repository).where(Repository.project_id == project.id)).scalar_one_or_none()
    if existing is not None and existing.status != "failed":
        raise AppError(409, "repository_exists", "This project already has a repository")
    repo = existing or Repository(id=uuid7(), organization_id=project.organization_id, project_id=project.id,
                                  created_by_user_id=user.id)
    repo.status = "creating"
    db.add(repo)
    db.commit()
    try:
        result = _run(db, factory, project, user, "git.init",
                      {"readme": f"# {project.name}\n\nThe AI-DLC repository for this project.\n",
                       "author": _author(user)})
    except AppError:
        repo.status = "failed"
        db.commit()
        raise
    repo.status, repo.head_sha, repo.updated_at = "ready", result["commit"], datetime.now(UTC)
    _audit(db, project, "repository.created", user, {"commit": result["commit"]})
    db.commit()
    return repo_out(repo)


def read(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID, ref: str,
         paths: list[str] | None) -> dict[str, Any]:
    project = execution._allowed(db, user, project_id)
    _repo(db, project.id)
    return _run(db, factory, project, user, "git.read", {"ref": ref, **({"paths": paths[:50]} if paths else {})})


def log(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID, ref: str) -> dict[str, Any]:
    project = execution._allowed(db, user, project_id)
    _repo(db, project.id)
    return _run(db, factory, project, user, "git.log", {"ref": ref, "limit": 100})


def diff(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID, base: str,
         head: str) -> dict[str, Any]:
    project = execution._allowed(db, user, project_id)
    _repo(db, project.id)
    return _run(db, factory, project, user, "git.diff", {"base": base, "head": head})


def commit(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID, *, branch: str,
           files: list[dict[str, Any]], message: str) -> dict[str, Any]:
    """A person commits files to a work branch (never to the default branch)."""
    project = execution._allowed(db, user, project_id)
    repo = _repo(db, project.id)
    if not BRANCH.match(branch) or branch == repo.default_branch:
        raise AppError(422, "invalid_branch", "Commit to a work branch, not the default branch")
    result = _run(db, factory, project, user, "git.commit", {"branch": branch, "files": files, "message": message,
                                                              "author": _author(user)})
    _audit(db, project, "repository.committed", user, {"branch": branch, "commit": result["commit"],
                                                       "files": len(result.get("changed", []))})
    db.commit()
    _refresh_branch(db, factory, project, user, branch)
    return result


# Change sets ------------------------------------------------------------------------------------------------------

def _ai_run(db: Session, change_set_id: uuid.UUID) -> Any:
    from app.devai.models import DeveloperAiRun

    return db.execute(select(DeveloperAiRun).where(DeveloperAiRun.change_set_id == change_set_id)).scalar_one_or_none()


def change_set_out(cs: ChangeSet, ai_run: Any = None) -> dict[str, Any]:
    return {"developer_ai_run": {"id": str(ai_run.id), "number": ai_run.number,
                                 "requested_by_user_id": str(ai_run.requested_by_user_id)} if ai_run else None,
            "id": str(cs.id), "number": cs.number, "title": cs.title, "description": cs.description,
            "branch": cs.branch, "base_sha": cs.base_sha, "head_sha": cs.head_sha, "status": cs.status,
            "files": cs.files, "approved_sha": cs.approved_sha, "decision_note": cs.decision_note,
            "author_user_id": str(cs.author_user_id) if cs.author_user_id else None,
            "decided_by_user_id": str(cs.decided_by_user_id) if cs.decided_by_user_id else None,
            "decided_at": cs.decided_at.isoformat() if cs.decided_at else None, "merged_sha": cs.merged_sha,
            "created_at": cs.created_at.isoformat() if cs.created_at else None}


def _apply_diff(cs: ChangeSet, result: dict[str, Any]) -> None:
    moved = result["head_commit"] != cs.head_sha
    cs.base_sha, cs.head_sha, cs.files = result["merge_base"], result["head_commit"], result["files"][:500]
    if moved and cs.status == "approved":
        cs.status = "in_review"  # new commits after approval: the approval no longer covers the branch
        cs.decision_note = "New commits after approval; review again."
    cs.updated_at = datetime.now(UTC)


def _refresh_branch(db: Session, factory: sessionmaker[Session], project: Any, user: User, branch: str) -> None:
    open_sets = db.execute(select(ChangeSet).where(ChangeSet.project_id == project.id, ChangeSet.branch == branch,
                                                   ChangeSet.status.in_(("open", "in_review", "approved",
                                                                         "changes_requested")))).scalars().all()
    for cs in open_sets:
        _apply_diff(cs, _run(db, factory, project, user, "git.diff", {"base": "main", "head": branch}))
        if cs.status == "changes_requested":
            cs.status = "in_review"
    db.commit()


def open_change_set(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID, *, branch: str,
                    title: str, description: str) -> dict[str, Any]:
    project = execution._allowed(db, user, project_id)
    cs = _open(db, factory, project, user, branch=branch, title=title, description=description, author=user)
    _audit(db, project, "change_set.opened", user, {"change_set": str(cs.id), "branch": branch, "head": cs.head_sha})
    db.commit()
    return change_set_out(cs)


def open_for_ai(db: Session, factory: sessionmaker[Session], project: Any, requester: User, *, branch: str,
                title: str, description: str, actor: str) -> ChangeSet:
    """The Developer AI's change set (Phase 2e): authored by the AI, so no person is its author; the person who asked
    for the work is recorded on the run and cannot approve it (decide)."""
    from app.events.service import publish

    cs = _open(db, factory, project, requester, branch=branch, title=title, description=description, author=None)
    append_event(db, chain_key=org_chain(project.organization_id), event_type="change_set.opened",
                 actor_type="ai_agent", actor_id=actor, organization_id=project.organization_id,
                 project_id=project.id, payload={"change_set": str(cs.id), "branch": branch, "head": cs.head_sha,
                                                 "requested_by": str(requester.id)})
    publish(db, organization_id=project.organization_id, project_id=project.id, kind="change_set.opened",
            subject=str(cs.id), actor=f"agent:{actor}", data={"branch": branch, "head": cs.head_sha})
    db.commit()
    return cs


def _open(db: Session, factory: sessionmaker[Session], project: Any, user: User, *, branch: str, title: str,
          description: str, author: User | None) -> ChangeSet:
    repo = _repo(db, project.id)
    if not BRANCH.match(branch) or branch == repo.default_branch:
        raise AppError(422, "invalid_branch", "A change set is a work branch, not the default branch")
    if not title.strip():
        raise AppError(422, "title_required", "Give the change set a title")
    if db.execute(select(ChangeSet.id).where(ChangeSet.project_id == project.id, ChangeSet.branch == branch,
                                             ChangeSet.status.not_in(("merged", "closed")))).first():
        raise AppError(409, "change_set_exists", "This branch already has an open change set")
    result = _run(db, factory, project, user, "git.diff", {"base": repo.default_branch, "head": branch})
    if not result["files"]:
        raise AppError(422, "nothing_to_review", "The branch has no changes from the default branch")
    number = 1 + (db.execute(select(func.max(ChangeSet.number)).where(ChangeSet.project_id == project.id))
                  .scalar_one() or 0)
    cs = ChangeSet(id=uuid7(), organization_id=project.organization_id, project_id=project.id, number=number,
                   title=title.strip()[:200], description=description[:20000], branch=branch, status="in_review",
                   author_user_id=author.id if author else None)
    _apply_diff(cs, result)
    db.add(cs)
    db.flush()
    return cs


def list_change_sets(db: Session, user: User, project_id: uuid.UUID) -> list[dict[str, Any]]:
    project = execution._allowed(db, user, project_id)
    from app.devai.models import DeveloperAiRun

    rows = list(db.execute(select(ChangeSet).where(ChangeSet.project_id == project.id)
                           .order_by(ChangeSet.number.desc())).scalars())
    runs = {r.change_set_id: r for r in db.execute(select(DeveloperAiRun).where(
        DeveloperAiRun.project_id == project.id, DeveloperAiRun.change_set_id.is_not(None))).scalars()}
    return [change_set_out(cs, runs.get(cs.id)) for cs in rows]


def _change_set(db: Session, project_id: uuid.UUID, change_set_id: uuid.UUID) -> ChangeSet:
    cs = db.execute(select(ChangeSet).where(ChangeSet.id == change_set_id, ChangeSet.project_id == project_id)
                    .with_for_update()).scalar_one_or_none()
    if cs is None:
        raise not_found()
    return cs


def decide(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID,
           change_set_id: uuid.UUID, *, decision: str, note: str, reviewed_sha: str) -> dict[str, Any]:
    """A person approves the exact commit they reviewed, or asks for changes. Never the author; never the AI."""
    project = execution._allowed(db, user, project_id)
    cs = _change_set(db, project.id, change_set_id)
    if decision not in ("approve", "request_changes"):
        raise AppError(422, "invalid_decision", "Decision must be approve or request_changes")
    if cs.status not in ("in_review", "changes_requested", "open"):
        raise AppError(409, "not_in_review", f"This change set is {cs.status.replace('_', ' ')}")
    if cs.author_user_id == user.id:
        raise AppError(403, "separation_of_duties", "You cannot approve your own change set")
    ai_run = _ai_run(db, cs.id)
    if ai_run is not None and ai_run.requested_by_user_id == user.id:
        raise AppError(403, "separation_of_duties", "You asked the Developer AI for this change; another engineer "
                                                    "must review it")
    if decision == "request_changes" and not note.strip():
        raise AppError(422, "note_required", "Say what needs to change")
    _apply_diff(cs, _run(db, factory, project, user, "git.diff", {"base": "main", "head": cs.branch}))
    if reviewed_sha != cs.head_sha:
        db.commit()
        raise AppError(409, "stale_review", "The branch changed after you reviewed it; review the latest commit")
    cs.status = "approved" if decision == "approve" else "changes_requested"
    cs.approved_sha = cs.head_sha if decision == "approve" else ""
    cs.decided_by_user_id, cs.decided_at, cs.decision_note = user.id, datetime.now(UTC), note.strip()[:2000]
    _audit(db, project, f"change_set.{cs.status}", user, {"change_set": str(cs.id), "commit": cs.head_sha})
    db.commit()
    return change_set_out(cs, ai_run)


def merge(db: Session, factory: sessionmaker[Session], user: User, project_id: uuid.UUID,
          change_set_id: uuid.UUID) -> dict[str, Any]:
    """Merges the approved commit into the default branch, and only that commit."""
    project = execution._allowed(db, user, project_id)
    repo = _repo(db, project.id)
    cs = _change_set(db, project.id, change_set_id)
    if cs.status != "approved" or not cs.approved_sha:
        raise AppError(409, "not_approved", "Only an approved change set can be merged")
    result = _run(db, factory, project, user, "git.merge", {
        "branch": cs.branch, "expected_head": cs.approved_sha, "author": _author(user),
        "message": f"Merge change set {cs.number}: {cs.title}"})
    cs.status, cs.merged_sha, cs.merged_by_user_id = "merged", result["merged"], user.id
    cs.updated_at = repo.updated_at = datetime.now(UTC)
    repo.head_sha = result["merged"]
    _audit(db, project, "change_set.merged", user, {"change_set": str(cs.id), "approved": cs.approved_sha,
                                                    "merged": result["merged"]})
    db.commit()
    return change_set_out(cs)


def code_summary(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    """The Developer's overview for a project (Workspace): the repository, change sets waiting for review, the latest
    Developer AI run and the last build. Read from records only; nothing runs."""
    from app.devai.models import DeveloperAiRun
    from app.execution.models import ExecutionJob

    repo = db.execute(select(Repository).where(Repository.project_id == project_id)).scalar_one_or_none()
    in_review = db.execute(select(func.count()).select_from(ChangeSet).where(
        ChangeSet.project_id == project_id, ChangeSet.status.in_(("open", "in_review")))).scalar_one()
    approved = db.execute(select(func.count()).select_from(ChangeSet).where(
        ChangeSet.project_id == project_id, ChangeSet.status == "approved")).scalar_one()
    run = db.execute(select(DeveloperAiRun).where(DeveloperAiRun.project_id == project_id)
                     .order_by(DeveloperAiRun.number.desc()).limit(1)).scalar_one_or_none()
    build = db.execute(select(ExecutionJob).where(ExecutionJob.project_id == project_id, ExecutionJob.kind == "checks")
                       .order_by(ExecutionJob.created_at.desc()).limit(1)).scalar_one_or_none()
    checks = ((build.result or {}).get("checks") or {}) if build else {}
    passed = bool(checks) and all(bool(c.get("passed")) for c in checks.values())
    return {"repository": repo is not None and repo.status == "ready",
            "change_sets_in_review": in_review, "change_sets_approved": approved,
            "ai_run": {"number": run.number, "status": run.status, "branch": run.branch} if run else None,
            "last_build": {"status": build.status, "passed": passed if build.status == "succeeded" else False,
                           "summary": str((checks.get("unit_tests") or {}).get("summary") or build.failure or "")[:120],
                           "at": build.created_at.isoformat() if build.created_at else None} if build else None}
