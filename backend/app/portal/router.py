import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.activity import service as activity
from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.jobs.api import queue
from app.portal import service, supervision

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])
FeedbackKind = Literal["defect", "new_requirement", "enhancement", "usability", "security_concern", "scope_change"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerIn(_Strict):
    field: str = Field(max_length=32)
    kind: Literal["answer", "dont_know", "you_decide"] = "answer"
    answer: str = Field(default="", max_length=2000)


class SendIn(_Strict):
    revision: int = Field(ge=1)


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


def _drive(tasks: BackgroundTasks, request: Request, db: Session, project_id: uuid.UUID,
           execution_id: uuid.UUID) -> None:
    queue(request, tasks, db, "portal.drive", {"execution_id": str(execution_id)},
          dedupe_key=f"drive:{execution_id}", project_id=project_id)


@router.get("/my-reviews")
def my_reviews(caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.my_reviews(db, caller.user)}


@router.get("/projects/{project_id}")
def workspace(project_id: uuid.UUID, request: Request, caller: CurrentCaller, db: DbSession) -> dict:
    return service.workspace(db, caller.user, project_id, managed=_managed(request))


@router.get("/projects/{project_id}/activity")
def ai_activity(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    """What the AI is doing on this project, live. Professional team only; owners get 403."""
    return activity.project_activity(db, caller.user, project_id)


@router.get("/projects/{project_id}/intake")
def intake(project_id: uuid.UUID, request: Request, caller: CurrentCaller, db: DbSession) -> dict:
    return service.get_intake(db, caller.user, project_id, managed=_managed(request))


def _managed(request: Request) -> bool:
    return request.app.state.settings.account_mode == "managed"


@router.post("/projects/{project_id}/intake/send")
def send_intake(project_id: uuid.UUID, body: SendIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.send_to_pm(db, caller.user, project_id, body.revision)


@router.post("/projects/{project_id}/intake/answers")
def answer(project_id: uuid.UUID, body: AnswerIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.answer_intake(db, caller.user, project_id, body.field, body.kind, body.answer)


@router.post("/projects/{project_id}/intake/confirm", status_code=202)
def confirm(project_id: uuid.UUID, body: ConfirmIn, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
            db: DbSession) -> dict:
    execution = service.confirm_intake(db, caller.user, project_id, body.revision, body.accept_assumptions,
                                       body.scope, managed=_managed(request))
    _drive(tasks, request, db, project_id, execution.id)
    return {"started": True}


@router.get("/projects/{project_id}/deliverables")
def deliverables(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.deliverables(db, caller.user, project_id)}


@router.post("/projects/{project_id}/deliverables/{stage}/decision")
def decide(project_id: uuid.UUID, stage: str, body: DecisionIn, request: Request, tasks: BackgroundTasks,
           caller: CsrfCaller, db: DbSession) -> dict:
    execution_id = service.decide(db, caller.user, project_id, stage, version_id=body.version_id,
                                  decision=body.decision, comment=body.comment, idempotency_key=body.idempotency_key)
    _drive(tasks, request, db, project_id, execution_id)
    return {"recorded": True}


@router.get("/projects/{project_id}/versions/{version_id}/code.zip")
def download_code(project_id: uuid.UUID, version_id: uuid.UUID, request: Request, caller: CurrentCaller,
                  db: DbSession) -> Response:
    state = request.app.state
    filename, content = service.code_archive(db, caller.user, project_id, version_id, state.settings,
                                             state.storage_transport)
    return Response(content, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "X-Content-Type-Options": "nosniff"})


@router.post("/projects/{project_id}/stages/{stage}/retry", status_code=202)
def retry(project_id: uuid.UUID, stage: str, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
          db: DbSession) -> dict:
    execution_id, stage_key = service.retry(db, caller.user, project_id, stage)
    queue(request, tasks, db, "portal.resume", {"execution_id": str(execution_id), "stage_key": stage_key},
          dedupe_key=f"resume:{execution_id}:{stage_key}", project_id=project_id)
    return {"started": True}


class EscalateIn(_Strict):
    reason: str = Field(min_length=3, max_length=2000)


class ResolveIn(_Strict):
    resolution: str = Field(min_length=3, max_length=2000)


class QuestionIn(_Strict):
    question: str = Field(min_length=3, max_length=2000)


class AnswerOwnerIn(_Strict):
    answer: str = Field(min_length=1, max_length=4000)


@router.get("/projects/{project_id}/escalations")
def list_escalations(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": supervision.escalations(db, caller.user, project_id)}


@router.post("/projects/{project_id}/stages/{stage}/escalations", status_code=201)
def escalate(project_id: uuid.UUID, stage: str, body: EscalateIn, caller: CsrfCaller, db: DbSession) -> dict:
    """Pauses the step: it is neither run nor approved until a professional resolves the escalation."""
    return supervision.escalate(db, caller.user, project_id, stage, body.reason)


@router.post("/projects/{project_id}/escalations/{escalation_id}/resolve")
def resolve_escalation(project_id: uuid.UUID, escalation_id: uuid.UUID, body: ResolveIn, request: Request,
                       tasks: BackgroundTasks, caller: CsrfCaller, db: DbSession) -> dict:
    out, execution_id = supervision.resolve(db, caller.user, project_id, escalation_id, body.resolution)
    _drive(tasks, request, db, project_id, execution_id)  # work that was held back may continue
    return out


@router.post("/projects/{project_id}/deliverables/{stage}/questions", status_code=201)
def ask_owner(project_id: uuid.UUID, stage: str, body: QuestionIn, caller: CsrfCaller, db: DbSession) -> dict:
    return supervision.ask_owner(db, caller.user, project_id, stage, body.question)


@router.post("/projects/{project_id}/questions/{question_id}/answer")
def answer_owner_question(project_id: uuid.UUID, question_id: uuid.UUID, body: AnswerOwnerIn, request: Request,
                          tasks: BackgroundTasks, caller: CsrfCaller, db: DbSession) -> dict:
    execution_id = supervision.answer(db, caller.user, project_id, question_id, body.answer)
    _drive(tasks, request, db, project_id, execution_id)  # the AI updates the work with the answer
    return {"recorded": True}


@router.post("/projects/{project_id}/questions/{question_id}/withdraw")
def withdraw_question(project_id: uuid.UUID, question_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    return supervision.withdraw(db, caller.user, project_id, question_id)


@router.get("/projects/{project_id}/messages")
def messages(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.messages(db, caller.user, project_id)}


@router.post("/projects/{project_id}/messages", status_code=201)
def post_message(project_id: uuid.UUID, body: MessageIn, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
                 db: DbSession) -> dict:
    items, answer_for = service.post_message(db, caller.user, project_id, body=body.body, profile=body.profile,
                                             artifact_version_id=body.artifact_version_id,
                                             managed=_managed(request))
    if answer_for:
        queue(request, tasks, db, "portal.answer", {"message_id": str(answer_for)},
              dedupe_key=f"answer:{answer_for}", project_id=project_id)
    return {"items": items}


class ReplyIn(_Strict):
    profile: str = Field(max_length=64)
    body: str = Field(min_length=1, max_length=4000)


@router.post("/projects/{project_id}/messages/replies", status_code=201)
def reply(project_id: uuid.UUID, body: ReplyIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.reply_as_professional(db, caller.user, project_id, profile=body.profile, body=body.body)


class ChangeIn(_Strict):
    summary: str = Field(min_length=3, max_length=300)
    details: str = Field(default="", max_length=4000)
    artifact_version_id: uuid.UUID | None = None


@router.post("/projects/{project_id}/change-requests", status_code=201)
def request_change(project_id: uuid.UUID, body: ChangeIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.request_change(db, caller.user, project_id, summary=body.summary.strip(), details=body.details,
                                  artifact_version_id=body.artifact_version_id)


@router.get("/projects/{project_id}/progress")
def client_progress(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.client_progress(db, caller.user, project_id)


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
