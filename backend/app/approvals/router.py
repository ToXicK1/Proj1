import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, ConfigDict, Field

from app.approvals import service
from app.auth.deps import CsrfCaller, CurrentCaller, DbSession

router = APIRouter(prefix="/api/v1/workflow-executions", tags=["approvals"])

StageKey = Annotated[str, Path(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionIn(_Strict):
    artifact_version_id: uuid.UUID
    decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"]
    comment: str = Field(default="", max_length=service.MAX_COMMENT)
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


@router.get("/{execution_id}/stages/{stage_key}/review")
def review(execution_id: uuid.UUID, stage_key: StageKey, caller: CurrentCaller, db: DbSession) -> dict:
    return service.review_view(db, caller.user, execution_id, stage_key)


@router.post("/{execution_id}/stages/{stage_key}/decisions")
def decide(
    execution_id: uuid.UUID,
    stage_key: StageKey,
    body: DecisionIn,
    caller: CsrfCaller,
    db: DbSession,
) -> dict:
    return service.submit_decision(
        db,
        caller.user,
        execution_id=execution_id,
        stage_key=stage_key,
        artifact_version_id=body.artifact_version_id,
        decision=body.decision,
        comment=body.comment,
        idempotency_key=body.idempotency_key,
    )
