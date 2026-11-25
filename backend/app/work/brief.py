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


def build(intake: tuple[WorkItem, WorkItemVersion], meetings: list[tuple[WorkItem, WorkItemVersion]]
          ) -> list[dict[str, str]]:
    """The brief's sections. Intake lines cite the intake; meeting lines cite their meeting."""
    _, version = intake
    body, ref = version.body, _ref(*intake)

    def lines(*fields: str, meeting_fields: tuple[str, ...] = ()) -> str:
        out = [f"- {value} ({ref})" for f in fields for value in body.get(f) or []]
        out += [f"- {value} ({_ref(m, v)})" for f in meeting_fields for m, v in meetings for value in v.body.get(f) or []]
        return "\n".join(out) or "None recorded."

    def text(field: str) -> str:
        return f"{body[field]} ({ref})" if body.get(field) else "Not recorded."

    return [
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
    intake = _intake(db, project)
    meetings = _meetings(db, project)
    body = {"sections": build(intake, meetings)}
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


def start(db: Session, user: User, project_id: uuid.UUID, package_id: uuid.UUID, scope: str, note: str):
    """The project's PM hands the approved brief to the BA department and starts the lifecycle (one transaction)."""
    from app.portal import service as portal
    from app.workflows import service as engine

    project, _ = work._scope(db, user, project_id)
    work._require_editor(db, user, project, PM)
    if project.project_manager_id != user.id:
        raise AppError(403, "not_permitted", "Only the project's Project Manager starts delivery")
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    if _started(db, project):
        raise AppError(409, "already_started", "Delivery has already started")
    package, entry, brief = _approved_brief(db, project, package_id)
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
        "brief_version": entry["version_id"], "scope": scope})
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
    """What the Brief and BA Handoff screens show: the brief, its approved packages, and whether delivery started."""
    from app.portal.service import DEFAULT_SCOPE, SCOPE_LABELS, SCOPES

    project, scope = work._scope(db, user, project_id)
    if not work.reads_all(scope, PM):
        raise not_found()
    brief = db.execute(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.kind == "project_brief",
                                              WorkItem.status != "archived")).scalars().first()
    packages = db.execute(select(WorkPackage).where(WorkPackage.project_id == project.id,
                                                    WorkPackage.department == PM, WorkPackage.status == "approved")
                          .order_by(WorkPackage.number.desc())).scalars().all()
    approved = [{"id": str(p.id), "number": p.number, "title": p.title, "sha256": p.sha256,
                 "brief": next(e for e in p.snapshot if e["kind"] == "project_brief")}
                for p in packages if any(e["kind"] == "project_brief" for e in p.snapshot)]
    validated = True
    try:
        _intake(db, project)
    except AppError:
        validated = False
    return {"brief": work.item_out(db, brief) if brief else None,
            "edited_by_pm": bool(brief and work.content_author(db, brief)),
            "intake_validated": validated, "approved_packages": approved, "started": _started(db, project),
            "is_project_manager": project.project_manager_id == user.id,
            "scopes": [{"key": k, "label": SCOPE_LABELS[k]} for k in SCOPES], "default_scope": DEFAULT_SCOPE}
