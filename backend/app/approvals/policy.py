"""Approval policies (APPROVAL_GOVERNANCE.md section 2). Pure logic, no database access.

A policy is turned into slots. Each slot names the project roles allowed to fill it and how many
distinct approvers it needs. A stage is approved when every slot is satisfied for the artifact
version the approvers judged. Sequential policies open slots one at a time.

Conditional policies are not supported yet and are refused by the compiler.
"""

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

KNOWN_ROLES = frozenset({"project_owner", "internal_reviewer", "team_member", "viewer"})
DEFAULT_POLICY: dict[str, Any] = {"type": "single", "role": "project_owner"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


PROFILE_ROLE = re.compile(r"^profile:[a-z][a-z0-9_\-]{1,63}$")


def _check_roles(roles: list[str]) -> list[str]:
    for role in roles:
        if role not in KNOWN_ROLES and not PROFILE_ROLE.match(role):
            raise ValueError(f"unknown project role '{role}'")
    if len(set(roles)) != len(roles):
        raise ValueError("roles must be unique")
    return roles


class SinglePolicy(_Strict):
    type: Literal["single"]
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        _check_roles([v])
        return v


class AnyOfPolicy(_Strict):
    type: Literal["any_of"]
    roles: list[str] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def _roles(cls, v: list[str]) -> list[str]:
        return _check_roles(v)


class AllOfPolicy(_Strict):
    type: Literal["all_of"]
    roles: list[str] = Field(min_length=2)

    @field_validator("roles")
    @classmethod
    def _roles(cls, v: list[str]) -> list[str]:
        return _check_roles(v)


class RoleBasedPolicy(_Strict):
    type: Literal["role_based"]
    roles: list[str] = Field(min_length=1)
    min_approvers: int = Field(ge=1, le=10)

    @field_validator("roles")
    @classmethod
    def _roles(cls, v: list[str]) -> list[str]:
        return _check_roles(v)


class SequentialStep(_Strict):
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        _check_roles([v])
        return v


class SequentialPolicy(_Strict):
    type: Literal["sequential"]
    steps: list[SequentialStep] = Field(min_length=2, max_length=10)


PolicyModel = Annotated[
    SinglePolicy | AnyOfPolicy | AllOfPolicy | RoleBasedPolicy | SequentialPolicy,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter = TypeAdapter(PolicyModel)


class PolicyError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def parse_policy(raw: dict[str, Any]) -> Any:
    try:
        return _ADAPTER.validate_python(raw)
    except ValidationError as exc:
        raise PolicyError([f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]) from exc


@dataclass(frozen=True)
class Slot:
    id: str
    roles: frozenset[str]
    required: int
    gated: bool  # sequential: opens only after the previous slot is satisfied


def slots_for(policy: Any) -> list[Slot]:
    if isinstance(policy, SinglePolicy):
        return [Slot("s1", frozenset({policy.role}), 1, gated=False)]
    if isinstance(policy, AnyOfPolicy):
        return [Slot("s1", frozenset(policy.roles), 1, gated=False)]
    if isinstance(policy, AllOfPolicy):
        return [Slot(f"s{i + 1}", frozenset({r}), 1, gated=False) for i, r in enumerate(policy.roles)]
    if isinstance(policy, RoleBasedPolicy):
        return [Slot("s1", frozenset(policy.roles), policy.min_approvers, gated=False)]
    if isinstance(policy, SequentialPolicy):
        return [
            Slot(f"s{i + 1}", frozenset({step.role}), 1, gated=i > 0)
            for i, step in enumerate(policy.steps)
        ]
    raise TypeError(f"unknown policy {type(policy).__name__}")


def satisfied_slots(slots: list[Slot], approvals: dict[str, set[Any]]) -> set[str]:
    """approvals maps slot id -> set of distinct approver ids that approved that slot."""
    return {s.id for s in slots if len(approvals.get(s.id, set())) >= s.required}


def is_complete(slots: list[Slot], approvals: dict[str, set[Any]]) -> bool:
    return satisfied_slots(slots, approvals) == {s.id for s in slots}


def open_slot_for(
    slots: list[Slot], role: str, approvals: dict[str, set[Any]], approver: Any
) -> Slot | None:
    """The slot this approver may fill now, or None. A person fills at most one slot per version."""
    if any(approver in people for people in approvals.values()):
        return None
    done = satisfied_slots(slots, approvals)
    for i, slot in enumerate(slots):
        if slot.id in done:
            continue
        if slot.gated and any(prev.id not in done for prev in slots[:i]):
            return None  # a sequential step is still waiting on an earlier one
        if role in slot.roles:
            return slot
        if slot.gated:
            return None  # the open sequential step belongs to another role
    return None
