"""Routing policies: which model route a kind of AI task uses, optionally per department.

Resolution: a rule for this task and department, else a rule for this task, else the agent's own route.
A reviewer rule may require a different provider from the work it reviews; if no such provider is configured
the review fails with a clear reason instead of quietly reviewing its own provider's work.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError
from app.organizations.service import require_org_admin
from app.providers.models import ModelRoute, RoutingPolicy

TASKS = ("lead", "reviewer", "specialist", "answer", "triage")


@dataclass(frozen=True)
class Route:
    key: str
    require_different_provider: bool = False
    from_policy: bool = False


def route_for(db: Session, organization_id: uuid.UUID, task: str, profile: str | None, default: str) -> Route:
    rules = db.execute(select(RoutingPolicy).where(RoutingPolicy.organization_id == organization_id,
                                                   RoutingPolicy.task == task)).scalars().all()
    rule = next((r for r in rules if profile and r.profile_key == profile), None) or \
        next((r for r in rules if r.profile_key is None), None)
    if rule is None:
        return Route(default)
    return Route(rule.route_key, rule.require_different_provider, True)


def _out(row: RoutingPolicy) -> dict[str, Any]:
    return {"task": row.task, "profile": row.profile_key, "route": row.route_key,
            "require_different_provider": row.require_different_provider}


def list_policies(db: Session, user: User, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    require_org_admin(db, user.id, organization_id)
    rows = db.execute(select(RoutingPolicy).where(RoutingPolicy.organization_id == organization_id)
                      .order_by(RoutingPolicy.task, RoutingPolicy.profile_key)).scalars()
    return [_out(r) for r in rows]


def replace_policies(db: Session, user: User, organization_id: uuid.UUID,
                     rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replaces the whole policy in one step. Every route must exist; only reviewer rules may demand a
    different provider. Running projects keep their agent versions, but routing applies to their next calls."""
    require_org_admin(db, user.id, organization_id)
    routes = set(db.execute(select(ModelRoute.key).where(ModelRoute.organization_id == organization_id)).scalars())
    seen: set[tuple[str, str | None]] = set()
    problems = []
    for i, rule in enumerate(rules):
        if rule["task"] not in TASKS:
            problems.append(f"rules[{i}].task: must be one of {', '.join(TASKS)}")
        if rule["route"] not in routes:
            problems.append(f"rules[{i}].route: no model route called '{rule['route']}'")
        if rule.get("require_different_provider") and rule["task"] != "reviewer":
            problems.append(f"rules[{i}].require_different_provider: only reviewer rules can require this")
        key = (rule["task"], rule.get("profile"))
        if key in seen:
            problems.append(f"rules[{i}]: a rule for {key[0]} / {key[1] or 'every department'} already exists")
        seen.add(key)
    if problems:
        raise AppError(422, "invalid_routing_policy", "; ".join(problems))
    db.execute(delete(RoutingPolicy).where(RoutingPolicy.organization_id == organization_id))
    for rule in rules:
        db.add(RoutingPolicy(id=uuid7(), organization_id=organization_id, task=rule["task"],
                             profile_key=rule.get("profile"), route_key=rule["route"],
                             require_different_provider=bool(rule.get("require_different_provider"))))
    from app.audit.service import append_event, org_chain

    append_event(db, chain_key=org_chain(organization_id), event_type="routing.policy_replaced", actor_type="human",
                 actor_id=str(user.id), organization_id=organization_id, payload={"rules": len(rules)})
    db.commit()
    return list_policies(db, user, organization_id)
