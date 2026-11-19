import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.portal import service

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])
FeedbackKind = Literal["defect", "new_requirement", "enhancement", "usability", "security_concern", "scope_change"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerIn(_Strict):
    field: str = Field(max_length=32)
    kind: Literal["answer", "dont_know", "you_decide"] = "answer"
    answer: str = Field(default="", max_length=2000)


class ConfirmIn(_Strict):
    revision: int = Field(ge=1)
    accept_assumptions: list[str] = Field(default_factory=list, max_length=8)
    scope: str = Field(default="feature", max_length=32)


class DecisionIn(_Strict):
    version_id: uuid.UUID
    decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"]
    comment: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


class MessageIn(_Strict):
    body: str = Field(min_length=1, max_length=4000)
    profile: str | None = Field(default=None, max_length=64)
    artifact_version_id: uuid.UUID | None = None


class TestReportIn(_Strict):
    steps: str = Field(min_length=1, max_length=2000)
    expected: str = Field(min_length=1, max_length=1000)
    actual: str = Field(min_length=1, max_length=1000)
    severity: Literal["low", "medium", "high"] = "medium"
    artifact_version_id: uuid.UUID | None = None


class TriageIn(_Strict):
    kind: FeedbackKind
    status: Literal["open", "triaged", "in_progress", "resolved", "rejected"]
    reason: str = Field(min_length=3, max_length=300)


def _drive(tasks: BackgroundTasks, request: Request, execution_id: uuid.UUID) -> None:
    state = request.app.state
    tasks.add_task(service.drive, state.session_factory, state.settings, state.provider_transport, execution_id)


@router.get("/my-reviews")
def my_reviews(caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.my_reviews(db, caller.user)}


@router.get("/projects/{project_id}")
def workspace(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.workspace(db, caller.user, project_id)


@router.get("/projects/{project_id}/intake")
def intake(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.get_intake(db, caller.user, project_id)


@router.post("/projects/{project_id}/intake/answers")
def answer(project_id: uuid.UUID, body: AnswerIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.answer_intake(db, caller.user, project_id, body.field, body.kind, body.answer)


@router.post("/projects/{project_id}/intake/confirm", status_code=202)
def confirm(project_id: uuid.UUID, body: ConfirmIn, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
            db: DbSession) -> dict:
    execution = service.confirm_intake(db, caller.user, project_id, body.revision, body.accept_assumptions,
                                       body.scope)
    _drive(tasks, request, execution.id)
    return {"started": True}


@router.get("/projects/{project_id}/deliverables")
def deliverables(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.deliverables(db, caller.user, project_id)}


@router.post("/projects/{project_id}/deliverables/{stage}/decision")
def decide(project_id: uuid.UUID, stage: str, body: DecisionIn, request: Request, tasks: BackgroundTasks,
           caller: CsrfCaller, db: DbSession) -> dict:
    execution_id = service.decide(db, caller.user, project_id, stage, version_id=body.version_id,
                                  decision=body.decision, comment=body.comment, idempotency_key=body.idempotency_key)
    _drive(tasks, request, execution_id)
    return {"recorded": True}


@router.get("/projects/{project_id}/versions/{version_id}/code.zip")
def download_code(project_id: uuid.UUID, version_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> Response:
    filename, content = service.code_archive(db, caller.user, project_id, version_id)
    return Response(content, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "X-Content-Type-Options": "nosniff"})


@router.post("/projects/{project_id}/stages/{stage}/retry", status_code=202)
def retry(project_id: uuid.UUID, stage: str, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
          db: DbSession) -> dict:
    execution_id, stage_key = service.retry(db, caller.user, project_id, stage)
    state = request.app.state
    tasks.add_task(service.resume, state.session_factory, state.settings, state.provider_transport, execution_id,
                   stage_key)
    return {"started": True}


@router.get("/projects/{project_id}/messages")
def messages(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.messages(db, caller.user, project_id)}


@router.post("/projects/{project_id}/messages", status_code=201)
def post_message(project_id: uuid.UUID, body: MessageIn, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
                 db: DbSession) -> dict:
    items, answer_for = service.post_message(db, caller.user, project_id, body=body.body, profile=body.profile,
                                             artifact_version_id=body.artifact_version_id)
    if answer_for:
        state = request.app.state
        tasks.add_task(service.answer_question, state.session_factory, state.settings, state.provider_transport,
                       answer_for)
    return {"items": items}


class ReplyIn(_Strict):
    profile: str = Field(max_length=64)
    body: str = Field(min_length=1, max_length=4000)


@router.post("/projects/{project_id}/messages/replies", status_code=201)
def reply(project_id: uuid.UUID, body: ReplyIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.reply_as_professional(db, caller.user, project_id, profile=body.profile, body=body.body)


@router.get("/projects/{project_id}/feedback")
def feedback(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.feedback(db, caller.user, project_id)}


@router.post("/projects/{project_id}/test-reports", status_code=201)
def test_report(project_id: uuid.UUID, body: TestReportIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.report_test_result(db, caller.user, project_id, steps=body.steps, expected=body.expected,
                                      actual=body.actual, severity=body.severity,
                                      artifact_version_id=body.artifact_version_id)


@router.post("/projects/{project_id}/feedback/{feedback_id}/triage")
def triage(project_id: uuid.UUID, feedback_id: uuid.UUID, body: TriageIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.triage(db, caller.user, project_id, feedback_id, kind=body.kind, status=body.status,
                          reason=body.reason)
