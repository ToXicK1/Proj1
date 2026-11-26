"""What each kind of job does. Handlers only call existing services; they never change state on their own."""

import uuid

from app.activity import service as activity
from app.jobs.service import Handler, JobContext


def _drive(ctx: JobContext) -> None:
    from app.portal import service as portal

    portal.drive(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["execution_id"]))


def _resume(ctx: JobContext) -> None:
    from app.portal import service as portal

    portal.resume(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["execution_id"]),
                  ctx.payload["stage_key"])


def _stage(ctx: JobContext) -> None:
    from app.portal import service as portal

    portal.run_stage(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["execution_id"]),
                     ctx.payload["stage_key"])


def _answer(ctx: JobContext) -> None:
    from app.portal import service as portal
    from app.portal.models import PortalMessage

    message_id = uuid.UUID(ctx.payload["message_id"])
    with ctx.factory() as db:
        message = db.get(PortalMessage, message_id)
        department = message.profile_key if message else None
    with activity.scope(profile_key=department):  # the answer belongs to that department's log
        portal.answer_question(ctx.factory, ctx.settings, ctx.transport, message_id, finish=ctx.finish_in)


def _triage(ctx: JobContext) -> None:
    from app.collab import service as collab
    from app.collab.models import Ticket

    ticket_id = uuid.UUID(ctx.payload["ticket_id"])
    with ctx.factory() as db:
        ticket = db.get(Ticket, ticket_id)
        department = ticket.profile_key if ticket else None
    with activity.scope(profile_key=department):
        collab.triage(ctx.factory, ctx.settings, ctx.transport, ticket_id, finish=ctx.finish_in)


def _assistant(ctx: JobContext) -> None:
    from app.work import assistant
    from app.work.assistant import AssistantExchange

    exchange_id = uuid.UUID(ctx.payload["exchange_id"])
    with ctx.factory() as db:
        row = db.get(AssistantExchange, exchange_id)
        department = row.department if row else None
    with activity.scope(profile_key=department):
        assistant.run(ctx.factory, ctx.settings, ctx.transport, exchange_id, finish=ctx.finish_in)


def _meeting_analysis(ctx: JobContext) -> None:
    from app.work import pm_analysis

    with activity.scope(profile_key="project_manager"):
        pm_analysis.run(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["exchange_id"]),
                        finish=ctx.finish_in)


def _developer_ai(ctx: JobContext) -> None:
    from app.devai import service as devai

    devai.run(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["run_id"]), finish=ctx.finish_in)


def _codebase_index(ctx: JobContext) -> None:
    from app.codebase import service as codebase

    codebase.run_index(ctx.factory, uuid.UUID(ctx.payload["index_id"]), finish=ctx.finish_in)


HANDLERS: dict[str, Handler] = {
    "codebase.index": _codebase_index,
    "developer_ai.run": _developer_ai,
    "work.meeting_analysis": _meeting_analysis,
    "work.assistant": _assistant,
    "portal.drive": _drive,
    "portal.stage": _stage,
    "portal.resume": _resume,
    "portal.answer": _answer,
    "collab.triage": _triage,
}
