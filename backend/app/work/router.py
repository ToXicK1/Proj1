import uuid
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.collab import service as collab
from app.core.errors import AppError
from app.jobs.api import queue
from app.portal.lifecycle import STAGES, TEAM, lead_key
from app.work import kinds
from app.work import service as work

router = APIRouter(prefix="/api/v1/projects/{project_id}/work", tags=["work"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemIn(_Strict):
    kind: str = Field(min_length=1, max_length=48)
    title: str = Field(min_length=1, max_length=300)
    body: dict[str, Any]
    provenance: Literal["confirmed", "assumption", "open_question"] = "confirmed"
    reason: str = Field(default="", max_length=500)


class ItemEdit(_Strict):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: dict[str, Any] | None = None
    provenance: Literal["confirmed", "assumption", "open_question"] | None = None
    reason: str = Field(default="", max_length=500)


class ArchiveIn(_Strict):
    archived: bool
    reason: str = Field(default="", max_length=300)


class LinkIn(_Strict):
    to_item_id: uuid.UUID
    link_type: str = Field(max_length=24)


class CommentIn(_Strict):
    body: str = Field(min_length=1, max_length=5000)
    version: int | None = Field(default=None, ge=1)
    anchor: dict[str, Any] | None = None


class PackageIn(_Strict):
    title: str = Field(default="", max_length=200)
    stage_key: str | None = Field(default=None, max_length=64)
    item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    note: str = Field(default="", max_length=2000)


class DecisionIn(_Strict):
    decision: Literal["approve", "request_changes"]
    note: str = Field(default="", max_length=2000)


class HandoffIn(_Strict):
    to_department: str = Field(max_length=64)
    note: str = Field(default="", max_length=2000)


class SendBackIn(_Strict):
    step: str = Field(min_length=1, max_length=64)
    note: str = Field(min_length=1, max_length=2000)


class AskIn(_Strict):
    question: str = Field(min_length=1, max_length=4000)
    item_id: uuid.UUID | None = None


class ReplyIn(_Strict):
    action: Literal["acknowledge", "request_clarification"]
    reply: str = Field(default="", max_length=2000)


@router.get("/kinds")
def list_kinds(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    work._scope(db, caller.user, project_id)
    return {"items": kinds.describe()}


@router.get("/team")
def team(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    """The six departments with people, AI lead, current step and pending work, from real records only."""
    project, scope = work._scope(db, caller.user, project_id)
    out = []
    for member in TEAM:
        people = collab.holders(db, project, member.profile)
        first = next((s for s in STAGES if s.profile == member.profile), None)
        card: dict[str, Any] = {
            "profile": member.profile, "title": member.title,
            "people": sorted(work._names(db, people).values()),
            "ai_lead": lead_key(first) if first else None,
            "visible": work.reads_all(scope, member.profile),
            "can_edit": caller.user.id in people,
            "work": work.counts(db, project.id, member.profile),
        }
        if card["visible"]:
            status = collab.department_status(db, caller.user, project_id, member.profile)
            steps = status["steps"]
            current = next((s for s in steps if s["status"] not in ("APPROVED", "COMPLETED", "SKIPPED")), None)
            card.update(started=status["started"], current=current, issues=status["issues"],
                        steps=len(steps), steps_done=sum(s["status"] in ("APPROVED", "COMPLETED") for s in steps),
                        awaiting_approval=sum(s["status"] == "AWAITING_HUMAN_REVIEW" for s in steps))
        out.append(card)
    return {"departments": out, "kind": scope.kind}


@router.get("/{department}/items")
def list_items(project_id: uuid.UUID, department: str, caller: CurrentCaller, db: DbSession,
               kind: str | None = None, status: str | None = None, provenance: str | None = None,
               q: str | None = Query(default=None, max_length=100), sort: str = "key",
               include_archived: bool = False) -> dict:
    return work.list_items(db, caller.user, project_id, department, kind=kind, status=status, provenance=provenance,
                           q=q, sort=sort, include_archived=include_archived)


@router.post("/{department}/items", status_code=201)
def create_item(project_id: uuid.UUID, department: str, body: ItemIn, caller: CsrfCaller, db: DbSession) -> dict:
    return work.create(db, caller.user, project_id, department, kind=body.kind, title=body.title, body=body.body,
                       provenance=body.provenance, reason=body.reason)


@router.get("/items/{item_id}")
def get_item(project_id: uuid.UUID, item_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return work.get_item(db, caller.user, project_id, item_id)


@router.put("/items/{item_id}")
def edit_item(project_id: uuid.UUID, item_id: uuid.UUID, body: ItemEdit, caller: CsrfCaller, db: DbSession) -> dict:
    return work.update(db, caller.user, project_id, item_id, expected_version=body.expected_version,
                       title=body.title, body=body.body, provenance=body.provenance, reason=body.reason)


@router.post("/items/{item_id}/archive")
def archive_item(project_id: uuid.UUID, item_id: uuid.UUID, body: ArchiveIn, caller: CsrfCaller,
                 db: DbSession) -> dict:
    return work.set_archived(db, caller.user, project_id, item_id, body.archived, body.reason)


@router.get("/items/{item_id}/compare")
def compare(project_id: uuid.UUID, item_id: uuid.UUID, caller: CurrentCaller, db: DbSession,
            a: int = Query(ge=1), b: int = Query(ge=1)) -> dict:
    return work.compare(db, caller.user, project_id, item_id, a, b)


@router.post("/items/{item_id}/links")
def add_link(project_id: uuid.UUID, item_id: uuid.UUID, body: LinkIn, caller: CsrfCaller, db: DbSession) -> dict:
    return work.link(db, caller.user, project_id, item_id, body.to_item_id, body.link_type)


@router.delete("/links/{link_id}", status_code=204)
def remove_link(project_id: uuid.UUID, link_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> None:
    work.unlink(db, caller.user, project_id, link_id)


@router.post("/items/{item_id}/comments")
def add_comment(project_id: uuid.UUID, item_id: uuid.UUID, body: CommentIn, caller: CsrfCaller,
                db: DbSession) -> dict:
    return {"items": work.comment(db, caller.user, project_id, item_id, body=body.body, version=body.version,
                                  anchor=body.anchor)}


@router.post("/comments/{comment_id}/resolve", status_code=204)
def resolve(project_id: uuid.UUID, comment_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> None:
    work.resolve_comment(db, caller.user, project_id, comment_id)


@router.get("/traceability")
def traceability(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return work.traceability(db, caller.user, project_id)


@router.get("/{department}/packages")
def packages(project_id: uuid.UUID, department: str, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": work.list_packages(db, caller.user, project_id, department)}


@router.post("/{department}/packages", status_code=201)
def submit(project_id: uuid.UUID, department: str, body: PackageIn, caller: CsrfCaller, db: DbSession) -> dict:
    return work.submit_package(db, caller.user, project_id, department, title=body.title, item_ids=body.item_ids,
                               note=body.note, stage_key=body.stage_key)


@router.post("/packages/{package_id}/decision")
def decide(project_id: uuid.UUID, package_id: uuid.UUID, body: DecisionIn, request: Request, tasks: BackgroundTasks,
           caller: CsrfCaller, db: DbSession) -> dict:
    out = work.decide_package(db, caller.user, project_id, package_id, decision=body.decision, note=body.note)
    execution_id = work.step_execution_id(db, package_id)
    if execution_id is not None:  # a step decision: let the workflow continue (next step, or the rework)
        queue(request, tasks, db, "portal.drive", {"execution_id": str(execution_id)},
              dedupe_key=f"drive:{execution_id}", project_id=project_id)
    return out


@router.post("/packages/{package_id}/handoffs", status_code=201)
def hand_off(project_id: uuid.UUID, package_id: uuid.UUID, body: HandoffIn, caller: CsrfCaller,
             db: DbSession) -> dict:
    return work.hand_off(db, caller.user, project_id, package_id, to_department=body.to_department, note=body.note)


@router.get("/{department}/steps")
def department_steps(project_id: uuid.UUID, department: str, caller: CurrentCaller, db: DbSession) -> dict:
    """The department's lifecycle steps and what each waits for. Its own team, managers and administrators only."""
    from app.work import bridge

    project, scope = work._scope(db, caller.user, project_id)
    if not work.reads_all(scope, work._department(department)):
        raise AppError(403, "not_permitted", "Not your department")
    return {"items": bridge.department_steps(db, caller.user, project, department),
            "can_edit": work.edits(db, caller.user, project, department)}


@router.post("/steps/{review_key}/send-back")
def send_back(project_id: uuid.UUID, review_key: str, body: SendBackIn, request: Request, tasks: BackgroundTasks,
              caller: CsrfCaller, db: DbSession) -> dict:
    """From Human Professional Review or User Review: one earlier step goes back for rework with a note."""
    from app.work import bridge

    project, _ = work._scope(db, caller.user, project_id)
    execution_id = bridge.send_back(db, caller.user, project=project, review_key=review_key, target_key=body.step,
                                    note=body.note)
    queue(request, tasks, db, "portal.drive", {"execution_id": str(execution_id)},
          dedupe_key=f"drive:{execution_id}", project_id=project_id)
    return {"sent_back": body.step}


@router.post("/{department}/assistant", status_code=202)
def ask_assistant(project_id: uuid.UUID, department: str, body: AskIn, request: Request, tasks: BackgroundTasks,
                  caller: CsrfCaller, db: DbSession) -> dict:
    from app.work import assistant

    out = assistant.ask(db, caller.user, project_id, department, question=body.question, item_id=body.item_id)
    queue(request, tasks, db, "work.assistant", {"exchange_id": out["id"]}, dedupe_key=f"assistant:{out['id']}",
          project_id=project_id)
    return out


@router.get("/{department}/assistant")
def assistant_history(project_id: uuid.UUID, department: str, caller: CurrentCaller, db: DbSession) -> dict:
    from app.work import assistant

    return {"items": assistant.history(db, caller.user, project_id, department)}


@router.post("/assistant/{exchange_id}/proposals/{index}")
def add_proposal(project_id: uuid.UUID, exchange_id: uuid.UUID, index: int, caller: CsrfCaller,
                 db: DbSession) -> dict:
    from app.work import assistant

    return assistant.add_proposal(db, caller.user, project_id, exchange_id, index)


@router.post("/items/{item_id}/attachments", status_code=201)
async def add_attachment(project_id: uuid.UUID, item_id: uuid.UUID, request: Request, caller: CsrfCaller,
                         db: DbSession, filename: str = Query(min_length=1, max_length=255)) -> dict:
    """The file is the request body (Content-Type: its type); its name is the `filename` query parameter."""
    from app.work import attachments

    data = await request.body()
    return attachments.attach(db, request.app.state.settings, caller.user, project_id, item_id, filename=filename,
                              content_type=request.headers.get("content-type", ""), data=data,
                              transport=request.app.state.storage_transport)


@router.get("/items/{item_id}/attachments")
def item_attachments(project_id: uuid.UUID, item_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    from app.work import attachments

    return {"items": attachments.list_for(db, caller.user, project_id, item_id)}


@router.get("/attachments/{attachment_id}")
def get_attachment(project_id: uuid.UUID, attachment_id: uuid.UUID, request: Request, caller: CurrentCaller,
                   db: DbSession) -> Response:
    from app.work import attachments

    row, data = attachments.download(db, request.app.state.settings, caller.user, project_id, attachment_id,
                                     transport=request.app.state.storage_transport)
    return Response(content=data, media_type=row.content_type, headers={
        "Content-Disposition": f'attachment; filename="{row.filename}"', "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store"})


@router.get("/client-form")
def client_form(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    """The client's optional pre-meeting answers (D3): unconfirmed input for the PM's intake. Internal team only."""
    from sqlalchemy import select

    from app.portal.models import IntakeRevision
    from app.portal.service import LABELS

    project, _ = work._scope(db, caller.user, project_id)
    row = db.execute(select(IntakeRevision).where(IntakeRevision.project_id == project.id)
                     .order_by(IntakeRevision.revision.desc())).scalars().first()
    items = (row.items or {}) if row else {}
    return {"answers": [{"field": key, "label": LABELS.get(key, key), "value": str((v or {}).get("value") or ""),
                         "tag": (v or {}).get("tag")} for key, v in items.items() if (v or {}).get("value")],
            "status": row.status if row else None}


@router.get("/{department}/handoffs")
def handoffs(project_id: uuid.UUID, department: str, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": work.list_handoffs(db, caller.user, project_id, department)}


@router.post("/handoffs/{handoff_id}/reply")
def reply(project_id: uuid.UUID, handoff_id: uuid.UUID, body: ReplyIn, caller: CsrfCaller, db: DbSession) -> dict:
    return work.reply_handoff(db, caller.user, project_id, handoff_id, action=body.action, reply=body.reply)
