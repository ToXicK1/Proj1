"""Work records: create, edit (new versions), link, comment, package, hand off. Access is checked here.

Who may do what (WORKSPACES_PLAN.md section 5):
- read a department's records: its own professionals, project managers and organization administrators. Other
  departments' professionals read only what an approved package contains, at the approved versions.
- create, edit, link, submit, decide: the professionals assigned to that department on the project.
- comment and reply to handoffs: anyone on the internal team who can read the record.
- project owners and plain members: no access here (owners see summaries in the portal; RD-2).
AI proposals come through `propose`, are marked `ai_suggestion` and authored by the agent; no AI path can submit or
decide a package.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.collab.service import ALL_PROFILES, Scope, holders, scope_for
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.notifications.models import Notification
from app.projects.models import Project
from app.work.kinds import KINDS, InvalidBody, validate
from app.work.models import (
    LINK_TYPES,
    PROVENANCE,
    Handoff,
    WorkComment,
    WorkItem,
    WorkItemLink,
    WorkItemVersion,
    WorkPackage,
)

ELEVATED = ("admin", "manager")


# Access ------------------------------------------------------------------------------------------------------------

def _scope(db: Session, user: User, project_id: uuid.UUID) -> tuple[Project, Scope]:
    project, scope = scope_for(db, user, project_id)
    if not scope.internal:
        raise AppError(403, "not_permitted", "Department workspaces are for the project's professional team")
    return project, scope


def reads_all(scope: Scope, department: str) -> bool:
    return scope.kind in ELEVATED or (scope.kind == "professional" and department in scope.profiles)


def edits(db: Session, user: User, project: Project, department: str) -> bool:
    return user.id in holders(db, project, department)


def _require_editor(db: Session, user: User, project: Project, department: str) -> None:
    if not edits(db, user, project, department):
        raise AppError(403, "not_permitted", "Only the department's assigned professionals can change its work")


def _department(department: str) -> str:
    if department not in ALL_PROFILES:
        raise not_found()
    return department


def _audit(db: Session, project: Project, event: str, actor: User | None, payload: dict, agent: str | None = None
           ) -> None:
    append_event(db, chain_key=org_chain(project.organization_id), event_type=event,
                 actor_type="human" if actor else "ai_agent", actor_id=str(actor.id) if actor else agent,
                 organization_id=project.organization_id, project_id=project.id, payload=payload)


def _sha(title: str, body: dict, provenance: str) -> str:
    return hashlib.sha256(json.dumps({"t": title, "b": body, "p": provenance}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def approved_versions(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    """Item id -> version id, from each department's latest approved package."""
    out: dict[uuid.UUID, uuid.UUID] = {}
    rows = db.execute(select(WorkPackage).where(WorkPackage.project_id == project_id,
                                                WorkPackage.status == "approved")
                      .order_by(WorkPackage.department, WorkPackage.number.desc())).scalars().all()
    seen: set[str] = set()
    for package in rows:
        if package.department in seen:
            continue
        seen.add(package.department)
        for entry in package.snapshot:
            out[uuid.UUID(entry["item_id"])] = uuid.UUID(entry["version_id"])
    return out


# Records -----------------------------------------------------------------------------------------------------------

def _next_key(db: Session, project_id: uuid.UUID, prefix: str) -> str:
    count = db.execute(select(func.count()).select_from(WorkItem).where(
        WorkItem.project_id == project_id, WorkItem.key.like(f"{prefix}-%"))).scalar_one()
    return f"{prefix}-{count + 1:03d}"


def _add_version(db: Session, item: WorkItem, *, title: str, body: dict, provenance: str, author: User | None,
                 agent: str | None, reason: str, sources: list) -> WorkItemVersion:
    version = WorkItemVersion(id=uuid7(), item_id=item.id, number=item.current_version + 1, title=title, body=body,
                              provenance=provenance, sha256=_sha(title, body, provenance),
                              author_type="human" if author else "ai",
                              author_user_id=author.id if author else None, author_agent=agent,
                              reason=reason[:500], sources=sources)
    db.add(version)
    item.current_version_id, item.current_version = version.id, version.number
    item.title, item.provenance, item.updated_at = title, provenance, datetime.now(UTC)
    return version


def _checked(kind_key: str, department: str, title: str, body: dict, provenance: str) -> dict:
    kind = KINDS.get(kind_key)
    if kind is None or kind.department != department:
        raise AppError(422, "invalid_kind", f"'{kind_key}' is not a record kind of this department")
    if provenance not in PROVENANCE:
        raise AppError(422, "invalid_provenance", "Unknown provenance")
    if not title.strip() or len(title) > 300:
        raise AppError(422, "invalid_title", "A title of 1 to 300 characters is required")
    try:
        return validate(kind, body)
    except InvalidBody as exc:
        raise AppError(422, "invalid_body", "The record has problems", problems=exc.problems) from exc


def create(db: Session, user: User, project_id: uuid.UUID, department: str, *, kind: str, title: str, body: dict,
           provenance: str = "confirmed", reason: str = "") -> dict[str, Any]:
    project, _ = _scope(db, user, project_id)
    _require_editor(db, user, project, _department(department))
    clean = _checked(kind, department, title, body, provenance)
    if provenance == "ai_suggestion":
        raise AppError(422, "invalid_provenance", "Only the AI proposes suggestions")
    item = WorkItem(id=uuid7(), organization_id=project.organization_id, project_id=project.id,
                    department=department, kind=kind, key=_next_key(db, project.id, KINDS[kind].prefix),
                    title=title.strip(), status="draft", provenance=provenance, owner_user_id=user.id)
    db.add(item)
    db.flush()
    _add_version(db, item, title=title.strip(), body=clean, provenance=provenance, author=user, agent=None,
                 reason=reason or "created", sources=[])
    _audit(db, project, "work.created", user, {"item": str(item.id), "key": item.key, "kind": kind})
    db.commit()
    return item_out(db, item, full=True)


def propose(db: Session, project: Project, department: str, *, agent: str, kind: str, title: str, body: dict,
            sources: list[dict]) -> WorkItem:
    """An AI proposal. Called by the engine only, never from an HTTP request. The caller commits."""
    clean = _checked(kind, department, title, body, "ai_suggestion")
    item = WorkItem(id=uuid7(), organization_id=project.organization_id, project_id=project.id,
                    department=department, kind=kind, key=_next_key(db, project.id, KINDS[kind].prefix),
                    title=title.strip(), status="draft", provenance="ai_suggestion")
    db.add(item)
    db.flush()
    _add_version(db, item, title=title.strip(), body=clean, provenance="ai_suggestion", author=None, agent=agent,
                 reason="proposed by the AI", sources=sources[:50])
    _audit(db, project, "work.proposed", None, {"item": str(item.id), "key": item.key, "kind": kind}, agent=agent)
    return item


def _item(db: Session, project_id: uuid.UUID, item_id: uuid.UUID) -> WorkItem:
    item = db.get(WorkItem, item_id)
    if item is None or item.project_id != project_id:
        raise not_found()
    return item


def update(db: Session, user: User, project_id: uuid.UUID, item_id: uuid.UUID, *, expected_version: int,
           title: str | None = None, body: dict | None = None, provenance: str | None = None,
           reason: str = "") -> dict[str, Any]:
    """A new version. `expected_version` stops two people silently overwriting each other."""
    project, _ = _scope(db, user, project_id)
    item = db.execute(select(WorkItem).where(WorkItem.id == item_id, WorkItem.project_id == project_id)
                      .with_for_update()).scalar_one_or_none()
    if item is None:
        raise not_found()
    _require_editor(db, user, project, item.department)
    if item.status == "archived":
        raise AppError(409, "archived", "Restore the record before changing it")
    if item.current_version != expected_version:
        raise AppError(409, "version_conflict", f"Someone saved version {item.current_version} first; reload it")
    current = db.get(WorkItemVersion, item.current_version_id)
    new_provenance = provenance or ("confirmed" if current.provenance == "ai_suggestion" else current.provenance)
    if new_provenance == "ai_suggestion":
        raise AppError(422, "invalid_provenance", "Only the AI proposes suggestions")
    new_title = (title if title is not None else current.title).strip()
    clean = _checked(item.kind, item.department, new_title, body if body is not None else current.body,
                     new_provenance)
    if _sha(new_title, clean, new_provenance) == current.sha256:
        raise AppError(409, "unchanged", "Nothing changed")
    _add_version(db, item, title=new_title, body=clean, provenance=new_provenance, author=user, agent=None,
                 reason=reason or "edited", sources=[])
    if item.status in ("approved", "changes_requested", "in_review"):
        item.status = "draft"  # an edited record needs a new package before it counts as approved again
    _audit(db, project, "work.edited", user, {"item": str(item.id), "version": item.current_version})
    db.commit()
    return item_out(db, item, full=True)


def set_archived(db: Session, user: User, project_id: uuid.UUID, item_id: uuid.UUID, archived: bool,
                 reason: str) -> dict[str, Any]:
    """Records are never deleted: archiving hides them and keeps the history."""
    project, _ = _scope(db, user, project_id)
    item = _item(db, project_id, item_id)
    _require_editor(db, user, project, item.department)
    if (item.status == "archived") == archived:
        return item_out(db, item, full=True)
    item.status = "archived" if archived else "draft"
    item.updated_at = datetime.now(UTC)
    _audit(db, project, "work.archived" if archived else "work.restored", user,
           {"item": str(item.id), "reason": reason[:300]})
    db.commit()
    return item_out(db, item, full=True)


def _version_out(v: WorkItemVersion, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {"id": str(v.id), "number": v.number, "title": v.title, "body": v.body, "provenance": v.provenance,
            "sha256": v.sha256, "author_type": v.author_type,
            "author": names.get(v.author_user_id) if v.author_user_id else v.author_agent,
            "reason": v.reason, "sources": v.sources, "created_at": v.created_at.isoformat()}


def _names(db: Session, ids: set) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    return dict(db.execute(select(User.id, User.display_name).where(User.id.in_(ids))).all()) if ids else {}


def item_out(db: Session, item: WorkItem, *, full: bool = False, version: WorkItemVersion | None = None
             ) -> dict[str, Any]:
    version = version or db.get(WorkItemVersion, item.current_version_id)
    out = {"id": str(item.id), "key": item.key, "kind": item.kind, "department": item.department,
           "title": version.title, "status": item.status, "provenance": version.provenance,
           "version": version.number, "latest_version": item.current_version, "body": version.body,
           "updated_at": item.updated_at.isoformat()}
    if full:
        versions = db.execute(select(WorkItemVersion).where(WorkItemVersion.item_id == item.id)
                              .order_by(WorkItemVersion.number)).scalars().all()
        names = _names(db, {v.author_user_id for v in versions})
        out["versions"] = [_version_out(v, names) for v in versions]
        out["links"] = _links_of(db, item)
    return out


def _links_of(db: Session, item: WorkItem) -> list[dict[str, Any]]:
    rows = db.execute(select(WorkItemLink, WorkItem).join(
        WorkItem, or_(WorkItem.id == WorkItemLink.to_item_id, WorkItem.id == WorkItemLink.from_item_id))
        .where(or_(WorkItemLink.from_item_id == item.id, WorkItemLink.to_item_id == item.id),
               WorkItem.id != item.id)).all()
    return [{"id": str(link.id), "type": link.link_type,
             "direction": "out" if link.from_item_id == item.id else "in",
             "item": {"id": str(other.id), "key": other.key, "title": other.title, "kind": other.kind,
                      "department": other.department}} for link, other in rows]


SORTS = {"key": WorkItem.key, "title": WorkItem.title, "updated": WorkItem.updated_at.desc(),
         "status": WorkItem.status}


def list_items(db: Session, user: User, project_id: uuid.UUID, department: str, *, kind: str | None = None,
               status: str | None = None, provenance: str | None = None, q: str | None = None,
               sort: str = "key", include_archived: bool = False) -> dict[str, Any]:
    project, scope = _scope(db, user, project_id)
    department = _department(department)
    query = select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.department == department)
    if kind:
        query = query.where(WorkItem.kind == kind)
    if status:
        query = query.where(WorkItem.status == status)
    elif not include_archived:
        query = query.where(WorkItem.status != "archived")
    if provenance:
        query = query.where(WorkItem.provenance == provenance)
    if q:
        like = f"%{q.strip()[:100]}%"
        query = query.where(or_(WorkItem.title.ilike(like), WorkItem.key.ilike(like)))
    query = query.order_by(SORTS.get(sort, WorkItem.key))
    items = db.execute(query).scalars().all()
    if reads_all(scope, department):
        rows = [item_out(db, i) for i in items]
        return {"items": rows, "can_edit": edits(db, user, project, department), "view": "working"}
    # Another department: only what was approved, at the approved version.
    approved = approved_versions(db, project.id)
    rows = [item_out(db, i, version=db.get(WorkItemVersion, approved[i.id])) for i in items if i.id in approved]
    return {"items": rows, "can_edit": False, "view": "approved"}


def get_item(db: Session, user: User, project_id: uuid.UUID, item_id: uuid.UUID) -> dict[str, Any]:
    project, scope = _scope(db, user, project_id)
    item = _item(db, project_id, item_id)
    if reads_all(scope, item.department):
        out = item_out(db, item, full=True)
        out["can_edit"] = edits(db, user, project, item.department)
        out["comments"] = _comments(db, item)
        return out
    approved = approved_versions(db, project.id).get(item.id)
    if approved is None:
        raise not_found()
    out = item_out(db, item, version=db.get(WorkItemVersion, approved))
    out["can_edit"], out["comments"], out["view"] = False, _comments(db, item, version_id=approved), "approved"
    return out


def compare(db: Session, user: User, project_id: uuid.UUID, item_id: uuid.UUID, a: int, b: int) -> dict[str, Any]:
    """Field by field: what changed from version a to version b."""
    _, scope = _scope(db, user, project_id)
    item = _item(db, project_id, item_id)
    if not reads_all(scope, item.department):
        raise not_found()
    va, vb = (db.execute(select(WorkItemVersion).where(WorkItemVersion.item_id == item.id,
                                                       WorkItemVersion.number == n)).scalar_one_or_none()
              for n in (a, b))
    if va is None or vb is None:
        raise not_found()
    left, right = {"title": va.title, "provenance": va.provenance, **va.body}, \
        {"title": vb.title, "provenance": vb.provenance, **vb.body}
    changes = [{"field": k, "before": left.get(k), "after": right.get(k)}
               for k in sorted(set(left) | set(right)) if left.get(k) != right.get(k)]
    return {"item": str(item.id), "from": a, "to": b, "changes": changes}


# Links -------------------------------------------------------------------------------------------------------------

def link(db: Session, user: User, project_id: uuid.UUID, from_id: uuid.UUID, to_id: uuid.UUID,
         link_type: str) -> dict[str, Any]:
    """A department links its own records to anything it can read (for example a story to a requirement)."""
    project, scope = _scope(db, user, project_id)
    source, target = _item(db, project_id, from_id), _item(db, project_id, to_id)
    _require_editor(db, user, project, source.department)
    if link_type not in LINK_TYPES:
        raise AppError(422, "invalid_link", f"Link type must be one of {', '.join(LINK_TYPES)}")
    if source.id == target.id:
        raise AppError(422, "invalid_link", "A record cannot link to itself")
    if not reads_all(scope, target.department) and target.id not in approved_versions(db, project.id):
        raise not_found()
    exists = db.execute(select(WorkItemLink.id).where(WorkItemLink.from_item_id == source.id,
                                                      WorkItemLink.to_item_id == target.id,
                                                      WorkItemLink.link_type == link_type)).first()
    if not exists:
        db.add(WorkItemLink(id=uuid7(), project_id=project.id, from_item_id=source.id, to_item_id=target.id,
                            link_type=link_type, created_by_user_id=user.id))
        _audit(db, project, "work.linked", user, {"from": str(source.id), "to": str(target.id), "type": link_type})
        db.commit()
    return {"links": _links_of(db, source)}


def unlink(db: Session, user: User, project_id: uuid.UUID, link_id: uuid.UUID) -> None:
    project, _ = _scope(db, user, project_id)
    row = db.get(WorkItemLink, link_id)
    if row is None or row.project_id != project.id:
        raise not_found()
    _require_editor(db, user, project, db.get(WorkItem, row.from_item_id).department)
    _audit(db, project, "work.unlinked", user, {"from": str(row.from_item_id), "to": str(row.to_item_id),
                                                "type": row.link_type})
    db.delete(row)
    db.commit()


def traceability(db: Session, user: User, project_id: uuid.UUID) -> dict[str, Any]:
    """Every record this person may read and the links between them; the UI lays out the matrix and gaps."""
    project, scope = _scope(db, user, project_id)
    approved = approved_versions(db, project.id)
    items = [i for i in db.execute(select(WorkItem).where(WorkItem.project_id == project.id,
                                                          WorkItem.status != "archived")).scalars()
             if reads_all(scope, i.department) or i.id in approved]
    ids = {i.id for i in items}
    links = db.execute(select(WorkItemLink).where(WorkItemLink.project_id == project.id)).scalars().all()
    return {"items": [{"id": str(i.id), "key": i.key, "kind": i.kind, "department": i.department, "title": i.title,
                       "status": i.status} for i in sorted(items, key=lambda i: i.key)],
            "links": [{"from": str(link_row.from_item_id), "to": str(link_row.to_item_id), "type": link_row.link_type}
                      for link_row in links if link_row.from_item_id in ids and link_row.to_item_id in ids]}


# Comments ----------------------------------------------------------------------------------------------------------

def _comments(db: Session, item: WorkItem, version_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    query = select(WorkComment).where(WorkComment.item_id == item.id)
    if version_id is not None:
        query = query.where(WorkComment.item_version_id == version_id)
    rows = db.execute(query.order_by(WorkComment.created_at)).scalars().all()
    numbers = dict(db.execute(select(WorkItemVersion.id, WorkItemVersion.number)
                              .where(WorkItemVersion.item_id == item.id)).all())
    names = _names(db, {c.author_user_id for c in rows})
    return [{"id": str(c.id), "version": numbers.get(c.item_version_id), "anchor": c.anchor, "body": c.body,
             "author_type": c.author_type, "author": names.get(c.author_user_id, "AI"),
             "resolved": c.resolved_at is not None, "created_at": c.created_at.isoformat()} for c in rows]


def comment(db: Session, user: User, project_id: uuid.UUID, item_id: uuid.UUID, *, body: str, version: int | None,
            anchor: dict | None) -> list[dict[str, Any]]:
    project, scope = _scope(db, user, project_id)
    item = _item(db, project_id, item_id)
    approved = approved_versions(db, project.id).get(item.id)
    if not reads_all(scope, item.department) and approved is None:
        raise not_found()
    if not body.strip() or len(body) > 5000:
        raise AppError(422, "invalid_comment", "A comment of 1 to 5,000 characters is required")
    number = version or item.current_version
    target = db.execute(select(WorkItemVersion).where(WorkItemVersion.item_id == item.id,
                                                      WorkItemVersion.number == number)).scalar_one_or_none()
    if target is None or (not reads_all(scope, item.department) and target.id != approved):
        raise not_found()
    if anchor is not None and (not isinstance(anchor, dict) or len(json.dumps(anchor)) > 300):
        raise AppError(422, "invalid_anchor", "An anchor is a small object such as {\"field\": \"description\"}")
    db.add(WorkComment(id=uuid7(), project_id=project.id, item_id=item.id, item_version_id=target.id, anchor=anchor,
                       body=body.strip(), author_type="human", author_user_id=user.id))
    _audit(db, project, "work.commented", user, {"item": str(item.id), "version": number})
    db.commit()
    return _comments(db, item)


def resolve_comment(db: Session, user: User, project_id: uuid.UUID, comment_id: uuid.UUID) -> None:
    project, _ = _scope(db, user, project_id)
    row = db.get(WorkComment, comment_id)
    if row is None or row.project_id != project.id:
        raise not_found()
    item = db.get(WorkItem, row.item_id)
    if row.author_user_id != user.id and not edits(db, user, project, item.department):
        raise AppError(403, "not_permitted", "Only the author or the department can resolve a comment")
    row.resolved_at, row.resolved_by_user_id = datetime.now(UTC), user.id
    db.commit()


# Packages ----------------------------------------------------------------------------------------------------------

def _package_out(db: Session, p: WorkPackage) -> dict[str, Any]:
    names = _names(db, {p.submitted_by_user_id, p.decided_by_user_id})
    return {"id": str(p.id), "department": p.department, "number": p.number, "title": p.title, "status": p.status,
            "items": p.snapshot, "sha256": p.sha256, "note": p.note,
            "submitted_by": names.get(p.submitted_by_user_id), "submitted_at": p.submitted_at.isoformat(),
            "decided_by": names.get(p.decided_by_user_id) if p.decided_by_user_id else None,
            "decided_at": p.decided_at.isoformat() if p.decided_at else None, "decision_note": p.decision_note}


def submit_package(db: Session, user: User, project_id: uuid.UUID, department: str, *, title: str,
                   item_ids: list[uuid.UUID], note: str) -> dict[str, Any]:
    """Freezes the current version of each chosen record. Records still marked as AI suggestions or open questions
    cannot be submitted: a person must confirm them (or mark them as assumptions) first."""
    project, _ = _scope(db, user, project_id)
    department = _department(department)
    _require_editor(db, user, project, department)
    if not item_ids:
        raise AppError(422, "empty_package", "Choose at least one record")
    items = db.execute(select(WorkItem).where(WorkItem.id.in_(item_ids), WorkItem.project_id == project.id)
                       .with_for_update()).scalars().all()
    if len(items) != len(set(item_ids)):
        raise not_found()
    problems = []
    for item in items:
        if item.department != department:
            problems.append(f"{item.key} belongs to another department")
        elif item.status == "archived":
            problems.append(f"{item.key} is archived")
        elif item.provenance in ("ai_suggestion", "open_question"):
            problems.append(f"{item.key} is still {item.provenance.replace('_', ' ')}: confirm it first")
    if problems:
        raise AppError(422, "package_not_ready", "Some records cannot be submitted yet", problems=problems)
    snapshot = []
    for item in sorted(items, key=lambda i: i.key):
        v = db.get(WorkItemVersion, item.current_version_id)
        snapshot.append({"item_id": str(item.id), "key": item.key, "kind": item.kind, "title": v.title,
                         "version_id": str(v.id), "number": v.number, "sha256": v.sha256})
        item.status = "in_review"
    for old in db.execute(select(WorkPackage).where(WorkPackage.project_id == project.id,
                                                    WorkPackage.department == department,
                                                    WorkPackage.status == "submitted")).scalars():
        old.status = "superseded"
    number = 1 + (db.execute(select(func.max(WorkPackage.number)).where(
        WorkPackage.project_id == project.id, WorkPackage.department == department)).scalar_one() or 0)
    package = WorkPackage(id=uuid7(), organization_id=project.organization_id, project_id=project.id,
                          department=department, title=title.strip()[:200] or f"Package {number}", number=number,
                          status="submitted", snapshot=snapshot,
                          sha256=hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
                          note=note[:2000], submitted_by_user_id=user.id)
    db.add(package)
    _audit(db, project, "work.package_submitted", user, {"package": str(package.id), "department": department,
                                                          "items": len(snapshot), "sha256": package.sha256})
    db.commit()
    return _package_out(db, package)


def decide_package(db: Session, user: User, project_id: uuid.UUID, package_id: uuid.UUID, *, decision: str,
                   note: str) -> dict[str, Any]:
    """Human-only, by an assigned professional of the department, on the exact frozen versions. A record edited
    after submission is not approved by this decision: its newer version is not in the package."""
    project, _ = _scope(db, user, project_id)
    package = db.execute(select(WorkPackage).where(WorkPackage.id == package_id, WorkPackage.project_id == project.id)
                         .with_for_update()).scalar_one_or_none()
    if package is None:
        raise not_found()
    _require_editor(db, user, project, package.department)
    if decision not in ("approve", "request_changes"):
        raise AppError(422, "invalid_decision", "Decision must be approve or request_changes")
    if package.status != "submitted":
        raise AppError(409, "already_decided", f"This package is {package.status.replace('_', ' ')}")
    if decision == "request_changes" and not note.strip():
        raise AppError(422, "note_required", "Say what needs to change")
    package.status = "approved" if decision == "approve" else "changes_requested"
    package.decided_by_user_id, package.decided_at, package.decision_note = user.id, datetime.now(UTC), note[:2000]
    for entry in package.snapshot:
        item = db.get(WorkItem, uuid.UUID(entry["item_id"]))
        if item.current_version_id == uuid.UUID(entry["version_id"]) and item.status == "in_review":
            item.status = "approved" if decision == "approve" else "changes_requested"
    _audit(db, project, f"work.package_{package.status}", user, {"package": str(package.id), "sha256": package.sha256})
    db.commit()
    return _package_out(db, package)


def list_packages(db: Session, user: User, project_id: uuid.UUID, department: str) -> list[dict[str, Any]]:
    project, scope = _scope(db, user, project_id)
    department = _department(department)
    query = select(WorkPackage).where(WorkPackage.project_id == project.id, WorkPackage.department == department)
    if not reads_all(scope, department):
        query = query.where(WorkPackage.status == "approved")
    return [_package_out(db, p) for p in db.execute(query.order_by(WorkPackage.number.desc())).scalars()]


# Handoffs ----------------------------------------------------------------------------------------------------------

def _handoff_out(db: Session, h: Handoff) -> dict[str, Any]:
    names = _names(db, {h.sender_user_id, h.replied_by_user_id})
    package = db.get(WorkPackage, h.package_id)
    return {"id": str(h.id), "from": h.from_department, "to": h.to_department, "status": h.status, "note": h.note,
            "package": {"id": str(package.id), "number": package.number, "title": package.title,
                        "items": package.snapshot, "sha256": package.sha256},
            "sender": names.get(h.sender_user_id), "sent_at": h.created_at.isoformat(), "reply": h.reply,
            "replied_by": names.get(h.replied_by_user_id) if h.replied_by_user_id else None,
            "replied_at": h.replied_at.isoformat() if h.replied_at else None}


def hand_off(db: Session, user: User, project_id: uuid.UUID, package_id: uuid.UUID, *, to_department: str,
             note: str) -> dict[str, Any]:
    project, _ = _scope(db, user, project_id)
    package = db.get(WorkPackage, package_id)
    if package is None or package.project_id != project.id:
        raise not_found()
    _require_editor(db, user, project, package.department)
    to_department = _department(to_department)
    if package.status != "approved":
        raise AppError(409, "not_approved", "Only an approved package can be handed off")
    if to_department == package.department:
        raise AppError(422, "same_department", "Hand off to another department")
    handoff = Handoff(id=uuid7(), project_id=project.id, package_id=package.id, from_department=package.department,
                      to_department=to_department, note=note[:2000], sender_user_id=user.id)
    db.add(handoff)
    for person in holders(db, project, to_department):
        db.add(Notification(id=uuid7(), organization_id=project.organization_id, project_id=project.id,
                            user_id=person, kind="handoff",
                            message=f"{package.title} was handed to your department"[:300]))
    _audit(db, project, "work.handoff_sent", user, {"handoff": str(handoff.id), "package": str(package.id),
                                                     "to": to_department})
    db.commit()
    return _handoff_out(db, handoff)


def reply_handoff(db: Session, user: User, project_id: uuid.UUID, handoff_id: uuid.UUID, *, action: str,
                  reply: str) -> dict[str, Any]:
    """The receiving department acknowledges, or asks for clarification. Neither changes workflow state."""
    project, _ = _scope(db, user, project_id)
    handoff = db.get(Handoff, handoff_id)
    if handoff is None or handoff.project_id != project.id:
        raise not_found()
    _require_editor(db, user, project, handoff.to_department)
    if action not in ("acknowledge", "request_clarification"):
        raise AppError(422, "invalid_action", "Action must be acknowledge or request_clarification")
    if action == "request_clarification" and not reply.strip():
        raise AppError(422, "reply_required", "Say what needs clarifying")
    handoff.status = "acknowledged" if action == "acknowledge" else "clarification_requested"
    handoff.reply, handoff.replied_by_user_id, handoff.replied_at = reply[:2000], user.id, datetime.now(UTC)
    if action == "request_clarification":
        for person in holders(db, project, handoff.from_department):
            db.add(Notification(id=uuid7(), organization_id=project.organization_id, project_id=project.id,
                                user_id=person, kind="handoff_clarification",
                                message="A department asked for clarification on your handoff"))
    _audit(db, project, f"work.handoff_{handoff.status}", user, {"handoff": str(handoff.id)})
    db.commit()
    return _handoff_out(db, handoff)


def list_handoffs(db: Session, user: User, project_id: uuid.UUID, department: str) -> list[dict[str, Any]]:
    project, scope = _scope(db, user, project_id)
    department = _department(department)
    if not reads_all(scope, department):
        raise AppError(403, "not_permitted", "Not your department")
    rows = db.execute(select(Handoff).where(Handoff.project_id == project.id, or_(
        Handoff.from_department == department, Handoff.to_department == department))
        .order_by(Handoff.created_at.desc())).scalars()
    return [_handoff_out(db, h) for h in rows]


# Summary for the Professional Team page ---------------------------------------------------------------------------

def counts(db: Session, project_id: uuid.UUID, department: str) -> dict[str, int]:
    rows = dict(db.execute(select(WorkItem.status, func.count()).where(
        WorkItem.project_id == project_id, WorkItem.department == department,
        WorkItem.status != "archived").group_by(WorkItem.status)).all())
    suggestions = db.execute(select(func.count()).select_from(WorkItem).where(
        WorkItem.project_id == project_id, WorkItem.department == department, WorkItem.status != "archived",
        WorkItem.provenance.in_(("ai_suggestion", "open_question")))).scalar_one()
    open_handoffs = db.execute(select(func.count()).select_from(Handoff).where(
        Handoff.project_id == project_id, Handoff.to_department == department, Handoff.status == "sent")).scalar_one()
    pending_packages = db.execute(select(func.count()).select_from(WorkPackage).where(
        WorkPackage.project_id == project_id, WorkPackage.department == department,
        WorkPackage.status == "submitted")).scalar_one()
    return {"records": sum(rows.values()), "approved": rows.get("approved", 0), "draft": rows.get("draft", 0),
            "in_review": rows.get("in_review", 0), "to_confirm": suggestions, "incoming_handoffs": open_handoffs,
            "packages_awaiting_decision": pending_packages}
