import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.collab import service
from app.portal import service as portal

router = APIRouter(prefix="/api/v1/portal/projects/{project_id}", tags=["collaboration"])
team_router = APIRouter(prefix="/api/v1/team-chat", tags=["collaboration"])
oversight_router = APIRouter(prefix="/api/v1/oversight", tags=["collaboration"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeamMessageIn(_Strict):
    channel: str = Field(min_length=2, max_length=64)
    body: str = Field(min_length=1, max_length=4000)
    mentions: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class TicketIn(_Strict):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    kind: Literal["question", "change", "defect", "other"] = "question"
    profile: str = Field(max_length=64)
    assignee: uuid.UUID | None = None


class CommentIn(_Strict):
    body: str = Field(min_length=1, max_length=4000)


class ActionIn(_Strict):
    action: Literal["approve_proposal", "resolve", "close", "reopen", "accept"]
    note: str = Field(default="", max_length=2000)


class GlobalMessageIn(_Strict):
    channel: str = Field(min_length=2, max_length=64)
    body: str = Field(min_length=1, max_length=4000)
    to: uuid.UUID | None = None  # a direct message to one person


@oversight_router.get("")
def oversight(caller: CurrentCaller, db: DbSession) -> dict:
    return service.oversight(db, caller.user)


@team_router.get("/channels")
def global_channels(caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.global_channels(db, caller.user), "kind": service.chat_info(db, caller.user)["kind"]}


@team_router.get("/people")
def global_people(caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.global_people(db, caller.user)}


@team_router.get("/messages/{channel}")
def global_messages(channel: str, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.global_messages(db, caller.user, channel)}


@team_router.post("/messages", status_code=201)
def post_global_message(body: GlobalMessageIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.post_global_message(db, caller.user, channel=body.channel, body=body.body, to=body.to)


@router.get("/scope")
def scope(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.scope_out(db, caller.user, project_id)


@router.get("/people")
def people(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.people(db, caller.user, project_id)}


@router.get("/team-chat/{channel}")
def team_chat(project_id: uuid.UUID, channel: str, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.team_messages(db, caller.user, project_id, channel)}


@router.post("/team-chat", status_code=201)
def post_team_message(project_id: uuid.UUID, body: TeamMessageIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.post_team_message(db, caller.user, project_id, channel=body.channel, body=body.body,
                                     mentions=body.mentions)


@router.get("/departments/{profile}/status")
def department_status(project_id: uuid.UUID, profile: str, caller: CurrentCaller, db: DbSession) -> dict:
    return service.department_status(db, caller.user, project_id, profile)


@router.get("/tickets")
def tickets(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.list_tickets(db, caller.user, project_id)}


@router.post("/tickets", status_code=201)
def raise_ticket(project_id: uuid.UUID, body: TicketIn, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
                 db: DbSession) -> dict:
    out, ticket_id = service.create_ticket(db, caller.user, project_id, title=body.title, body=body.body,
                                           kind=body.kind, profile=body.profile, assignee=body.assignee)
    state = request.app.state
    tasks.add_task(service.triage, state.session_factory, state.settings, state.provider_transport, ticket_id)
    return out


@router.get("/tickets/{ticket_id}")
def ticket(project_id: uuid.UUID, ticket_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.get_ticket(db, caller.user, project_id, ticket_id)


@router.post("/tickets/{ticket_id}/comments")
def comment(project_id: uuid.UUID, ticket_id: uuid.UUID, body: CommentIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.comment_ticket(db, caller.user, project_id, ticket_id, body.body)


@router.post("/tickets/{ticket_id}/actions")
def act(project_id: uuid.UUID, ticket_id: uuid.UUID, body: ActionIn, request: Request, tasks: BackgroundTasks,
        caller: CsrfCaller, db: DbSession) -> dict:
    out = service.act_on_ticket(db, caller.user, project_id, ticket_id, action=body.action, note=body.note)
    execution = portal._execution(db, project_id)
    if body.action == "approve_proposal" and execution is not None:  # an accepted change starts the AI's rework
        state = request.app.state
        tasks.add_task(portal.drive, state.session_factory, state.settings, state.provider_transport, execution.id)
    return out
