"""BRD and SRS drafts assembled by the platform from the department's approved records (no AI involved).

They are built when Human Professional Review gathers the department's work, so the exact draft versions are part of
what the professional approves. Every line names its record and version (REQ-003 v2), so the documents stay traceable
to the records. A draft is a `system_draft`: a person confirms or edits it before it can be submitted. A draft the
professional has edited is never overwritten; it is kept, and the review notes that the records may have moved on.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activity import service as activity
from app.audit.service import append_event, org_chain
from app.projects.models import Project
from app.work import service as work
from app.work.models import WorkItem, WorkItemLink, WorkItemVersion

BA = "business_analyst"
TITLES = {"brd": "Business Requirements Document (BRD)", "srs": "Software Requirements Specification (SRS)"}


def _approved(db: Session, project: Project, department: str) -> dict[str, list[tuple[WorkItem, WorkItemVersion]]]:
    rows = db.execute(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.department == department,
                                             WorkItem.status == "approved").order_by(WorkItem.key)).scalars()
    out: dict[str, list[tuple[WorkItem, WorkItemVersion]]] = {}
    for item in rows:
        out.setdefault(item.kind, []).append((item, db.get(WorkItemVersion, item.current_version_id)))
    return out


def _step_text(db: Session, execution_id: uuid.UUID, stage_key: str, field: str) -> str:
    from app.artifacts import service as artifacts
    from app.workflows import service as engine

    stage = engine.stage_rows(db, execution_id).get(stage_key)
    current = artifacts.current_version(db, stage.id) if stage else None
    value = current[1].content_json.get(field) if current else None
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value)
    return str(value).strip() if value else ""


def _ref(item: WorkItem, version: WorkItemVersion) -> str:
    return f"{item.key} v{version.number}"


def _lines(entries: list[tuple[WorkItem, WorkItemVersion]], render: Any) -> str:
    return "\n".join(render(i, v) for i, v in entries) if entries else "None approved yet."


def _requirement(i: WorkItem, v: WorkItemVersion) -> str:
    body = v.body
    text = f"- {_ref(i, v)} {v.title}: {body.get('description', '')}"
    if body.get("priority"):
        text += f" Priority: {body['priority']}."
    for criterion in body.get("acceptance_criteria") or []:
        text += f"\n  - Acceptance: {criterion}"
    return text


def build(db: Session, project: Project, execution_id: uuid.UUID) -> dict[str, list[dict[str, str]]]:
    """The two drafts' sections, from what is approved now."""
    records = _approved(db, project, BA)
    requirements = records.get("requirement", [])
    by_type = {t: [(i, v) for i, v in requirements if v.body.get("type") == t]
               for t in ("business", "functional", "non_functional", "constraint")}
    stories = records.get("user_story", [])
    links = db.execute(select(WorkItemLink).where(WorkItemLink.project_id == project.id)).scalars().all()
    keys = {i.id: i.key for kind in records.values() for i, _ in kind}
    trace = {i.key: sorted(keys[link.from_item_id] for link in links
                           if link.to_item_id == i.id and link.from_item_id in keys) for i, _ in requirements}
    summary = _step_text(db, execution_id, "ba_intake_review", "summary") or "Not yet summarized."
    in_scope = _step_text(db, execution_id, "ba_scope", "in_scope")
    out_scope = _step_text(db, execution_id, "ba_scope", "out_of_scope")
    first_release = _step_text(db, execution_id, "ba_scope", "first_release")
    success = _step_text(db, execution_id, "ba_scope", "success_measures")
    constraints = _step_text(db, execution_id, "ba_discovery", "constraints")
    brd = [
        {"heading": "1. Purpose and business problem", "content": summary},
        {"heading": "2. Stakeholders", "content": _lines(records.get("stakeholder", []), lambda i, v:
                                                         f"- {_ref(i, v)} {v.title}: {v.body.get('role', '')}")},
        {"heading": "3. Business requirements", "content": _lines(by_type["business"], _requirement)},
        {"heading": "4. Scope", "content": "\n\n".join(p for p in (
            f"In scope:\n{in_scope}" if in_scope else "", f"Out of scope:\n{out_scope}" if out_scope else "",
            f"First release:\n{first_release}" if first_release else "",
            f"Success measures:\n{success}" if success else "") if p) or "Not yet defined."},
        {"heading": "5. Assumptions", "content": _lines(records.get("assumption", []), lambda i, v:
                                                        f"- {_ref(i, v)} {v.title}: {v.body.get('description', '')}")},
        {"heading": "6. Risks", "content": _lines(records.get("risk", []), lambda i, v: (
            f"- {_ref(i, v)} {v.title}: {v.body.get('description', '')}"
            + (f" Mitigation: {v.body['mitigation']}" if v.body.get("mitigation") else "")))},
        {"heading": "7. Open questions", "content": _lines(records.get("discovery_question", []), lambda i, v: (
            f"- {_ref(i, v)} {v.body.get('question', v.title)}"
            + (f" Answer: {v.body['answer']}" if v.body.get("answer") else " (unanswered)")))},
    ]
    srs = [
        {"heading": "1. Introduction", "content": f"{summary}\n\nThis specification lists the approved "
                                                  "requirements and user stories; each line names its record."},
        {"heading": "2. Functional requirements", "content": _lines(by_type["functional"], _requirement)},
        {"heading": "3. Non-functional requirements", "content": _lines(by_type["non_functional"], _requirement)},
        {"heading": "4. Constraints", "content": "\n".join(p for p in (
            _lines(by_type["constraint"], _requirement) if by_type["constraint"] else "", constraints) if p)
            or "None approved yet."},
        {"heading": "5. User stories", "content": _lines(stories, lambda i, v: (
            f"- {_ref(i, v)} As a {v.body.get('role', '')}, I want {v.body.get('want', '')}"
            + (f", so that {v.body['so_that']}" if v.body.get("so_that") else "") + "."
            + "".join(f"\n  - Acceptance: {c}" for c in v.body.get("acceptance_criteria") or [])))},
        {"heading": "6. Traceability", "content": "\n".join(
            f"- {key}: {', '.join(found) if found else 'no linked records yet'}" for key, found in trace.items())
            or "No approved requirements yet."},
    ]
    return {"brd": brd, "srs": srs}


def assemble(db: Session, *, project: Project, stage_execution_id: uuid.UUID, execution_id: uuid.UUID,
             doc_types: list[str]) -> list[dict[str, Any]]:
    """Creates or refreshes the drafts for this review step. Does not commit. Returns what was included."""
    drafts = build(db, project, execution_id)
    sources = [{"record": i.key, "version_id": str(v.id)} for kind in _approved(db, project, BA).values()
               for i, v in kind][:50]
    out = []
    for doc_type in doc_types:
        body = {"doc_type": doc_type, "sections": drafts[doc_type]}
        existing = next((i for i in db.execute(select(WorkItem).where(
            WorkItem.stage_execution_id == stage_execution_id, WorkItem.kind == "document",
            WorkItem.status != "archived")).scalars()
            if (db.get(WorkItemVersion, i.current_version_id).body or {}).get("doc_type") == doc_type), None)
        kept = False
        if existing is None:
            item = WorkItem(id=work.uuid7(), organization_id=project.organization_id, project_id=project.id,
                            department=BA, kind="document", key=work._next_key(db, project.id, "DOC"),
                            title=TITLES[doc_type], status="draft", provenance="system_draft",
                            stage_execution_id=stage_execution_id)
            db.add(item)
            db.flush()
            work._add_version(db, item, title=TITLES[doc_type], body=body, provenance="system_draft", author=None,
                              agent=work.PLATFORM, reason="assembled from the approved records", sources=sources)
        elif work.content_author(db, existing) is not None:
            item, kept = existing, True  # the professional's own wording wins; it is never overwritten
            activity.note("output", f"Kept the professional's edited {TITLES[doc_type]}; the approved records may "
                          "have changed since", {"item": existing.key})
        else:
            item = existing
            current = db.get(WorkItemVersion, item.current_version_id)
            if current.body != body or current.provenance != "system_draft":
                work._add_version(db, item, title=TITLES[doc_type], body=body, provenance="system_draft",
                                  author=None, agent=work.PLATFORM, reason="re-assembled from the approved records",
                                  sources=sources)
                item.status = "draft"
        db.flush()  # the new version must be readable below
        version = db.get(WorkItemVersion, item.current_version_id)
        out.append({"key": item.key, "doc_type": doc_type, "title": version.title, "version": version.number,
                    "version_id": str(version.id), "kept_professional_edits": kept})
    append_event(db, chain_key=org_chain(project.organization_id), event_type="work.documents_assembled",
                 actor_type="system", organization_id=project.organization_id, project_id=project.id,
                 payload={"documents": [{"key": d["key"], "version": d["version"]} for d in out]})
    activity.note("output", f"Assembled {', '.join(TITLES[d] for d in doc_types)} from the approved records",
                  {"documents": [d["key"] for d in out]})
    return out
