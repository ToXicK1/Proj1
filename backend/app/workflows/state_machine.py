"""Stage state machine (WORKFLOW_ENGINE.md section 2). Pure logic: no database access.

Every legal edge is listed with the actor types allowed to take it. Edges not listed are invalid.
AI agents and providers never appear in any allow-list, so they can never move a stage.
"""

from enum import StrEnum


class StageStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    READY = "READY"
    RUNNING = "RUNNING"
    AI_COMPLETED = "AI_COMPLETED"
    VALIDATING = "VALIDATING"
    AWAITING_HUMAN_REVIEW = "AWAITING_HUMAN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class ActorType(StrEnum):
    HUMAN = "human"
    SYSTEM = "system"
    AI_AGENT = "ai_agent"
    PROVIDER = "provider"


SYS = frozenset({ActorType.SYSTEM})
HUMAN = frozenset({ActorType.HUMAN})
ANY_OPERATOR = frozenset({ActorType.SYSTEM, ActorType.HUMAN})

S = StageStatus

# (from, to) -> actor types allowed to take the edge.
EDGES: dict[tuple[StageStatus, StageStatus], frozenset[ActorType]] = {
    (S.NOT_STARTED, S.READY): SYS,
    (S.NOT_STARTED, S.SKIPPED): SYS,
    (S.NOT_STARTED, S.CANCELLED): HUMAN,
    (S.READY, S.RUNNING): ANY_OPERATOR,
    (S.READY, S.BLOCKED): SYS,
    (S.READY, S.CANCELLED): HUMAN,
    (S.RUNNING, S.AI_COMPLETED): SYS,
    (S.RUNNING, S.FAILED): SYS,
    (S.RUNNING, S.CANCELLED): HUMAN,
    (S.AI_COMPLETED, S.VALIDATING): SYS,
    (S.VALIDATING, S.AWAITING_HUMAN_REVIEW): SYS,
    (S.VALIDATING, S.BLOCKED): SYS,
    (S.VALIDATING, S.FAILED): SYS,
    (S.BLOCKED, S.RUNNING): SYS,
    (S.BLOCKED, S.VALIDATING): SYS,
    (S.BLOCKED, S.CANCELLED): HUMAN,
    (S.AWAITING_HUMAN_REVIEW, S.APPROVED): HUMAN,
    (S.AWAITING_HUMAN_REVIEW, S.CHANGES_REQUESTED): HUMAN,
    (S.AWAITING_HUMAN_REVIEW, S.REJECTED): HUMAN,
    (S.AWAITING_HUMAN_REVIEW, S.CANCELLED): HUMAN,
    (S.CHANGES_REQUESTED, S.RUNNING): SYS,
    (S.CHANGES_REQUESTED, S.CANCELLED): HUMAN,
    (S.REJECTED, S.READY): HUMAN,
    (S.APPROVED, S.AWAITING_HUMAN_REVIEW): SYS,  # invalidation when an upstream artifact changes
    (S.FAILED, S.READY): HUMAN,
    (S.FAILED, S.CANCELLED): HUMAN,
}

TERMINAL = frozenset({S.SKIPPED, S.CANCELLED})

# Statuses that satisfy a dependency for downstream stages.
SATISFIES_DEPENDENCY = frozenset({S.APPROVED, S.SKIPPED})


class InvalidTransition(Exception):
    """Raised for an edge that does not exist, or one the actor may not take."""

    def __init__(self, from_status: StageStatus, to_status: StageStatus, reason: str) -> None:
        super().__init__(f"{from_status} -> {to_status}: {reason}")
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason


def check_transition(from_status: StageStatus, to_status: StageStatus, actor: ActorType) -> None:
    allowed = EDGES.get((from_status, to_status))
    if allowed is None:
        raise InvalidTransition(from_status, to_status, "transition is not defined")
    if actor not in allowed:
        raise InvalidTransition(from_status, to_status, f"actor '{actor}' may not take this transition")


def is_legal(from_status: StageStatus, to_status: StageStatus, actor: ActorType) -> bool:
    try:
        check_transition(from_status, to_status, actor)
    except InvalidTransition:
        return False
    return True
