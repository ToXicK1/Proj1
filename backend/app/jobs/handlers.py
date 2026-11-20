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


HANDLERS: dict[str, Handler] = {
    "portal.drive": _drive,
    "portal.stage": _stage,
    "portal.resume": _resume,
    "portal.answer": _answer,
    "collab.triage": _triage,
}
