"""The Project Brief and the BA handoff (P4, RD-21).

The platform assembles the brief from the PM's validated intake and the confirmed client meetings; no AI writes it.
Every line names its record and version (INT-001 v3), so the brief stays traceable. It is a `system_draft`: the PM
confirms or edits it, submits it as a package and approves it like any other package (RD-19 applies: a brief with
the PM's own edits needs a second Project Manager). A brief the PM has edited is never overwritten.

Only an approved brief starts delivery. The PM chooses the kind of work and hands the exact approved version to the
Business Analyst department: that records the handoff and starts the lifecycle with the brief as the project input,
so the BA's AI steps work from the brief. The BA asks for clarification on the handoff; the PM is notified.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.errors import AppError, not_found
from app.projects.models import Project
from app.work import service as work
from app.work.models import Handoff, WorkItem, WorkItemLink, WorkItemVersion, WorkPackage

PM = "project_manager"
BA = "business_analyst"
TITLE = "Project Brief"


def _current(db: Session, item: WorkItem) -> WorkItemVersion:
    return db.get(WorkItemVersion, item.current_version_id)


def _ref(item: WorkItem, version: WorkItemVersion) -> str:
    return f"{item.key} v{version.number}"


def _intake(db: Session, project: Project) -> tuple[WorkItem, WorkItemVersion]:
    item = db.execute(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.kind == "project_intake",
                                             WorkItem.status != "archived")).scalars().first()
    version = _current(db, item) if item else None
    if version is None or version.body.get("validation") != "validated" or version.provenance in work.NEEDS_CONFIRMING:
        raise AppError(409, "intake_not_validated", "Validate the project intake first; the brief is assembled from it")
    return item, version


def _meetings(db: Session, project: Project) -> list[tuple[WorkItem, WorkItemVersion]]:
    rows = db.execute(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.kind == "meeting",
                                             WorkItem.status != "archived").order_by(WorkItem.key)).scalars()
    return [(m, _current(db, m)) for m in rows if m.provenance not in work.NEEDS_CONFIRMING]


def build(intake: tuple[WorkItem, WorkItemVersion], meetings: list[tuple[WorkItem, WorkItemVersion]],
          kind_of_work: str | None = None) -> list[dict[str, str]]:
    """The brief's sections. Intake lines cite the intake; meeting lines cite their meeting. The kind of work comes
    first: it is part of what the client approves."""
    _, version = intake
    body, ref = version.body, _ref(*intake)

    def lines(*fields: str, meeting_fields: tuple[str, ...] = ()) -> str:
        out = [f"- {value} ({ref})" for f in fields for value in body.get(f) or []]
        out += [f"- {value} ({_ref(m, v)})" for f in meeting_fields for m, v in meetings for value in v.body.get(f) or []]
        return "\n".join(out) or "None recorded."

    def text(field: str) -> str:
        return f"{body[field]} ({ref})" if body.get(field) else "Not recorded."

    return [
        *([{"heading": "Kind of work", "content": kind_of_work}] if kind_of_work else []),
        {"heading": "1. Business problem", "content": text("business_problem")},
        {"heading": "2. Objectives", "content": lines("objectives", meeting_fields=("objectives",))},
        {"heading": "3. Proposed solution", "content": text("proposed_solution")},
        {"heading": "4. Stakeholders and target users", "content": "\n".join(
            [*(f"- Stakeholder: {s} ({ref})" for s in body.get("stakeholders") or []),
             *(f"- Target user: {u} ({ref})" for u in body.get("target_users") or [])]) or "None recorded."},
        {"heading": "5. Scope: features and functional expectations",
         "content": lines("features_discussed", "functional_expectations")},
        {"heading": "6. Non-functional expectations and constraints",
         "content": lines("non_functional_expectations", "technical_constraints", meeting_fields=("constraints",))},
        {"heading": "7. Budget and timeline", "content": text("budget_timeline")},
        {"heading": "8. Integrations and dependencies", "content": lines("integrations", "dependencies")},
        {"heading": "9. Decisions", "content": lines("decisions", meeting_fields=("decisions",))},
        {"heading": "10. Assumptions", "content": lines("assumptions", meeting_fields=("assumptions",))},
        {"heading": "11. Risks", "content": lines("risks", meeting_fields=("risks",))},
        {"heading": "12. Open questions", "content": lines("open_questions", meeting_fields=("open_questions",))},
        {"heading": "13. Sources", "content": "\n".join(
            [f"- {ref}: {version.title}", *(f"- {_ref(m, v)}: {v.title}" for m, v in meetings)])},
    ]


def _started(db: Session, project: Project) -> bool:
    from app.workflows.models import WorkflowExecution

    return db.execute(select(WorkflowExecution.id).where(WorkflowExecution.project_id == project.id)).first() is not None


def assemble(db: Session, user: User, project_id: uuid.UUID) -> dict[str, Any]:
    """The PM asks the platform to (re)assemble the brief from what is validated and confirmed now."""
    project, _ = work._scope(db, user, project_id)
    work._require_editor(db, user, project, PM)
    if _started(db, project):
        raise AppError(409, "already_started", "Delivery has started from the approved brief")
    from app.work import kickoff

    if kickoff.held(db, project.id) is None:
        raise AppError(409, "kickoff_required", "Hold the project kickoff first; the brief comes after it")
    intake = _intake(db, project)
    meetings = _meetings(db, project)
    from app.portal.lifecycle import SCOPE_LABELS

    body = {"sections": build(intake, meetings, SCOPE_LABELS.get(project.delivery_scope or ""))}
    sources = [{"record": i.key, "version_id": str(v.id)} for i, v in (intake, *meetings)][:50]
    existing = db.execute(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.kind == "project_brief",
                                                 WorkItem.status != "archived").with_for_update()).scalars().first()
    kept = False
    if existing is None:
        item = WorkItem(id=work.uuid7(), organization_id=project.organization_id, project_id=project.id,
                        department=PM, kind="project_brief", key=work._next_key(db, project.id, "PB"), title=TITLE,
                        status="draft", provenance="system_draft")
        db.add(item)
        db.flush()
        work._add_version(db, item, title=TITLE, body=body, provenance="system_draft", author=None,
                          agent=work.PLATFORM, reason="assembled from the validated intake and the meetings",
                          sources=sources)
    elif work.content_author(db, existing) is not None:
        item, kept = existing, True  # the PM's own wording wins; it is never overwritten
    else:
        item = existing
        current = _current(db, item)
        if current.body != body or current.provenance != "system_draft":
            work._add_version(db, item, title=TITLE, body=body, provenance="system_draft", author=None,
                              agent=work.PLATFORM, reason="re-assembled from the validated intake and the meetings",
                              sources=sources)
            item.status = "draft"
    db.flush()
    linked = set(db.execute(select(WorkItemLink.to_item_id).where(WorkItemLink.from_item_id == item.id)).scalars())
    for source, _ in (intake, *meetings):
        if source.id not in linked:
            db.add(WorkItemLink(id=work.uuid7(), project_id=project.id, from_item_id=item.id, to_item_id=source.id,
                                link_type="derives_from"))
    version = _current(db, item)
    work._audit(db, project, "work.brief_assembled", user, {"item": item.key, "version": version.number,
                                                             "kept_pm_edits": kept})
    db.commit()
    return {"item": work.item_out(db, item, full=True), "kept_pm_edits": kept}


def _approved_brief(db: Session, project: Project, package_id: uuid.UUID) -> tuple[WorkPackage, dict, WorkItem]:
    package = db.execute(select(WorkPackage).where(WorkPackage.id == package_id, WorkPackage.project_id == project.id)
                         .with_for_update()).scalar_one_or_none()
    if package is None or package.department != PM:
        raise not_found()
    if package.status != "approved":
        raise AppError(409, "brief_not_approved", "Only an approved brief can be handed to the Business Analyst")
    entry = next((e for e in package.snapshot if e["kind"] == "project_brief"), None)
    if entry is None:
        raise AppError(422, "no_brief", "This package does not contain the project brief")
    if package.client_status != "approved":
        raise AppError(409, "client_approval_required", "The client has not approved this brief yet")
    brief = db.get(WorkItem, uuid.UUID(entry["item_id"]))
    if brief.current_version_id != uuid.UUID(entry["version_id"]) or brief.status != "approved":
        raise AppError(409, "brief_changed", "The brief changed after this approval; submit and approve it again")
    return package, entry, brief


def project_input(version: WorkItemVersion) -> list[str]:
    """The approved brief as the lifecycle's project input: one line per brief line, under its heading."""
    out = []
    for section in version.body.get("sections") or []:
        heading = str(section.get("heading", "")).split(". ", 1)[-1]
        for line in str(section.get("content", "")).splitlines():
            line = line.strip().removeprefix("- ")
            if line and line not in ("None recorded.", "Not recorded.") and heading != "Sources":
                out.append(f"{heading}: {line}"[:2000])
    return out[:200]


def _is_admin(db: Session, user: User, project: Project) -> bool:
    from app.organizations.models import Membership

    return db.execute(select(Membership.id).where(Membership.organization_id == project.organization_id,
                                                  Membership.user_id == user.id, Membership.role == "org_admin",
                                                  Membership.status == "active")).first() is not None


def start(db: Session, user: User, project_id: uuid.UUID, package_id: uuid.UUID, note: str, reason: str = ""):
    """Hands the client-approved brief to the BA department and starts the lifecycle (one transaction), with the
    project's kind of work. The project's PM starts it; an administrator may, with a reason, when the PM is not
    available."""
    from app.portal import service as portal
    from app.work import kickoff
    from app.workflows import service as engine

    project, _ = work._scope(db, user, project_id, oversight=True)  # an administrator may start it for the PM (RD-27)
    by_admin = project.project_manager_id != user.id
    if by_admin:
        if not _is_admin(db, user, project):
            raise AppError(403, "not_permitted", "Only the project's Project Manager, or an administrator, starts "
                                                 "delivery")
        if not reason.strip():
            raise AppError(422, "reason_required", "Say why you start delivery instead of the Project Manager")
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    if _started(db, project):
        raise AppError(409, "already_started", "Delivery has already started")
    package, entry, brief = _approved_brief(db, project, package_id)
    gaps = kickoff.missing(db, project)
    if gaps:
        raise AppError(409, "team_incomplete", "The team this kind of work needs is not complete", problems=gaps)
    if kickoff.held(db, project.id) is None:
        raise AppError(409, "kickoff_required", "Hold the project kickoff first")
    scope = project.delivery_scope
    version = _current(db, brief)
    workflow_version = portal.lifecycle_version(db, project, scope)
    handoff = Handoff(id=work.uuid7(), project_id=project.id, package_id=package.id, from_department=PM,
                      to_department=BA, note=(note.strip() or "The approved project brief; please start from it.")[:2000],
                      sender_user_id=user.id)
    db.add(handoff)
    for person in work.holders(db, project, BA):
        db.add(work.Notification(id=work.uuid7(), organization_id=project.organization_id, project_id=project.id,
                                 user_id=person, kind="handoff",
                                 message=f"The approved {TITLE} ({entry['key']} v{entry['number']}) was handed to "
                                         "your department; delivery has started"[:300]))
    work._audit(db, project, "work.brief_handed_off", user, {
        "handoff": str(handoff.id), "package": str(package.id), "sha256": package.sha256, "brief": entry["key"],
        "brief_version": entry["version_id"], "scope": scope,
        **({"started_by_administrator": True, "reason": reason.strip()[:500]} if by_admin else {})})
    if by_admin and project.project_manager_id:
        db.add(work.Notification(id=work.uuid7(), organization_id=project.organization_id, project_id=project.id,
                                 user_id=project.project_manager_id, kind=f"started_for_you:{package.id}",
                                 message=f"An administrator started delivery for you: {reason.strip()}"[:300]))
    db.flush()
    facts = {"scope": scope, "client_approvals": True, "brief": {"key": entry["key"], "version_id": entry["version_id"],
                                       "number": entry["number"], "package_id": str(package.id),
                                       "package_sha256": package.sha256, "handoff_id": str(handoff.id)}}
    execution = engine.start_execution(db, user, project_id=project.id, workflow_version_id=workflow_version.id,
                                       intake=project_input(version), facts=facts, as_project_manager=True)
    append_event(db, chain_key=org_chain(project.organization_id), event_type="work.delivery_started_from_brief",
                 actor_type="human", actor_id=str(user.id), organization_id=project.organization_id,
                 project_id=project.id, payload={"execution": str(execution.id), "brief": entry["key"],
                                                 "brief_version": entry["version_id"]})
    return execution, handoff


def status(db: Session, user: User, project_id: uuid.UUID) -> dict[str, Any]:
    """What the Brief and BA Handoff screens show: the brief, its approved packages with the client's decision, the
    kind of work, the kickoff, and whether delivery started."""
    from app.portal.lifecycle import SCOPE_LABELS
    from app.work import kickoff

    project, scope = work._scope(db, user, project_id, oversight=True)
    if not (work.reads_all(scope, PM) or _is_admin(db, user, project)):  # admins: to start delivery for the PM (RD-27)
        raise not_found()
    brief = db.execute(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.kind == "project_brief",
                                              WorkItem.status != "archived")).scalars().first()
    packages = db.execute(select(WorkPackage).where(WorkPackage.project_id == project.id,
                                                    WorkPackage.department == PM, WorkPackage.status == "approved")
                          .order_by(WorkPackage.number.desc())).scalars().all()
    approved = [{"id": str(p.id), "number": p.number, "title": p.title, "sha256": p.sha256,
                 "brief": next(e for e in p.snapshot if e["kind"] == "project_brief"),
                 "client_status": p.client_status, "client_note": p.client_note}
                for p in packages if any(e["kind"] == "project_brief" for e in p.snapshot)]
    validated = True
    try:
        _intake(db, project)
    except AppError:
        validated = False
    return {"brief": work.item_out(db, brief) if brief else None,
            "edited_by_pm": bool(brief and work.content_author(db, brief)),
            "intake_validated": validated, "kickoff_held": kickoff.held(db, project.id) is not None,
            "approved_packages": approved, "started": _started(db, project),
            "is_project_manager": project.project_manager_id == user.id,
            "is_admin": _is_admin(db, user, project), "has_project_manager": project.project_manager_id is not None,
            "kind_of_work": SCOPE_LABELS.get(project.delivery_scope or ""), "team_gaps": kickoff.missing(db, project)}


# The client's approval of the brief (start flow) -------------------------------------------------------------------

def send_to_client(db: Session, project: Project, package: WorkPackage, approver: User) -> None:
    """After the PM approves the brief, it waits for the client. The caller commits."""
    from app.projects.models import ProjectMember

    package.client_status = "awaiting"
    owners = db.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == project.id,
                                                            ProjectMember.project_role == "project_owner")).scalars()
    for person in owners:
        db.add(work.Notification(id=work.uuid7(), organization_id=project.organization_id, project_id=project.id,
                                 user_id=person, kind=f"brief_for_client:{package.id}",
                                 message="Your project brief is ready. Please read it and approve it, or ask for "
                                         "changes."))
    work._audit(db, project, "work.brief_sent_to_client", approver, {"package": str(package.id)})


def _latest_for_client(db: Session, project: Project) -> WorkPackage | None:
    return db.execute(select(WorkPackage).where(
        WorkPackage.project_id == project.id, WorkPackage.department == PM,
        WorkPackage.client_status.is_not(None)).order_by(WorkPackage.number.desc())).scalars().first()


def client_view(db: Session, user: User, project_id: uuid.UUID) -> dict[str, Any]:
    """The brief as the PM approved it (the exact version), and the client's decision."""
    from app.portal.lifecycle import SCOPE_LABELS
    from app.portal.service import _access

    project, role = _access(db, user, project_id)
    package = _latest_for_client(db, project)
    if package is None:
        return {"brief": None}
    entry = next(e for e in package.snapshot if e["kind"] == "project_brief")
    version = db.get(WorkItemVersion, uuid.UUID(entry["version_id"]))
    return {"brief": {"package_id": str(package.id), "key": entry["key"], "version": entry["number"],
                      "title": version.title, "sections": version.body.get("sections") or [],
                      "kind_of_work": SCOPE_LABELS.get(project.delivery_scope or ""),
                      "client_status": package.client_status, "client_note": package.client_note,
                      "decided_at": package.client_decided_at.isoformat() if package.client_decided_at else None,
                      "can_decide": role == "project_owner" and package.client_status == "awaiting"}}


def client_decide(db: Session, user: User, project_id: uuid.UUID, package_id: uuid.UUID, *, decision: str,
                  note: str) -> dict[str, Any]:
    """Only the project's client; only on the version the PM approved, while it is still current."""
    from datetime import UTC, datetime

    from app.portal.service import _owner

    project = _owner(db, user, project_id)
    package = db.execute(select(WorkPackage).where(WorkPackage.id == package_id, WorkPackage.project_id == project.id)
                         .with_for_update()).scalar_one_or_none()
    if package is None or not any(e["kind"] == "project_brief" for e in package.snapshot):
        raise not_found()
    if decision not in ("approve", "request_changes"):
        raise AppError(422, "invalid_decision", "Decision must be approve or request_changes")
    if package.client_status != "awaiting":
        raise AppError(409, "not_awaiting_client", "This brief is not waiting for your decision")
    if decision == "request_changes" and not note.strip():
        raise AppError(422, "note_required", "Say what should change")
    entry = next(e for e in package.snapshot if e["kind"] == "project_brief")
    brief_item = db.get(WorkItem, uuid.UUID(entry["item_id"]))
    if brief_item.current_version_id != uuid.UUID(entry["version_id"]):
        raise AppError(409, "brief_changed", "The brief changed after it was sent to you")
    package.client_status = "approved" if decision == "approve" else "changes_requested"
    package.client_decided_by_user_id, package.client_decided_at = user.id, datetime.now(UTC)
    package.client_note = note.strip()[:2000]
    if decision == "request_changes":
        brief_item.status = "changes_requested"
    if project.project_manager_id:
        db.add(work.Notification(
            id=work.uuid7(), organization_id=project.organization_id, project_id=project.id,
            user_id=project.project_manager_id,
            kind=f"brief_{'approved' if decision == 'approve' else 'changes'}:{package.id}",  # within 64 characters
            message=("The client approved the project brief. You can hand it to the Business Analyst."
                     if decision == "approve" else f"The client asked for changes to the brief: {note[:200]}")[:300]))
    work._audit(db, project, f"work.brief_client_{package.client_status}", user,
                {"package": str(package.id), "sha256": package.sha256})
    db.commit()
    return client_view(db, user, project.id)
