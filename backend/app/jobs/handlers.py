"""What each kind of job does. Handlers only call existing services; they never change state on their own."""

import uuid

from app.jobs.service import Handler, JobContext


def _drive(ctx: JobContext) -> None:
    from app.portal import service as portal

    portal.drive(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["execution_id"]))


def _resume(ctx: JobContext) -> None:
    from app.portal import service as portal

    portal.resume(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["execution_id"]),
                  ctx.payload["stage_key"])


def _answer(ctx: JobContext) -> None:
    from app.portal import service as portal

    portal.answer_question(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["message_id"]),
                           finish=ctx.finish_in)


def _triage(ctx: JobContext) -> None:
    from app.collab import service as collab

    collab.triage(ctx.factory, ctx.settings, ctx.transport, uuid.UUID(ctx.payload["ticket_id"]),
                  finish=ctx.finish_in)


HANDLERS: dict[str, Handler] = {
    "portal.drive": _drive,
    "portal.resume": _resume,
    "portal.answer": _answer,
    "collab.triage": _triage,
}
