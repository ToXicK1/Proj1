"""Spend controls for administrators: prices, monthly budgets, paused providers, and what has been spent.

Everything here is organization-admin only and enforced on the server. Changes are written to the audit chain.
Budgets are enforced where AI calls are made (service.run_structured), not here and not in the browser.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import append_event, org_chain
from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import not_found
from app.projects.models import Project
from app.providers import costs
from app.providers.models import (
    AgentRun,
    AiProvider,
    ModelPrice,
    ModelRoute,
    SpendBudget,
    TokenUsage,
)
from app.providers.service import _require_admin

router = APIRouter(prefix="/api/v1/orgs/{organization_id}", tags=["spend"])

MAX_USD_PER_MTOK = 1000.0  # a typing mistake guard: no model costs more than this per million tokens


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceIn(_Strict):
    adapter_type: Literal["anthropic", "openai", "gemini", "openai_compatible", "mock"]
    model: str = Field(min_length=1, max_length=120)
    input_usd_per_mtok: float = Field(ge=0, le=MAX_USD_PER_MTOK)
    output_usd_per_mtok: float = Field(ge=0, le=MAX_USD_PER_MTOK)
    # Left out: a tenth of the input price for cache reads, 1.25 times for cache writes.
    cache_read_usd_per_mtok: float | None = Field(default=None, ge=0, le=MAX_USD_PER_MTOK)
    cache_write_usd_per_mtok: float | None = Field(default=None, ge=0, le=MAX_USD_PER_MTOK)


class BudgetIn(_Strict):
    project_id: uuid.UUID | None = None
    limit_usd: float = Field(gt=0, le=1_000_000)
    warn_percent: int = Field(default=80, ge=1, le=100)
    on_limit: Literal["pause", "free_only"] = "pause"


class StrategyIn(_Strict):
    strategy: Literal["ordered", "cheapest"]


def _micro(usd: float) -> int:
    return round(usd * costs.MICRO)


def _audit(db: Session, user: User, organization_id: uuid.UUID, event: str, payload: dict) -> None:
    append_event(db, chain_key=org_chain(organization_id), event_type=event, actor_type="human",
                 actor_id=str(user.id), organization_id=organization_id, payload=payload)


def _price_out(adapter: str, model: str, p: costs.Price, row_id: uuid.UUID | None = None) -> dict:
    return {"id": str(row_id) if row_id else None, "adapter_type": adapter, "model": model, "source": p.source,
            "input_usd_per_mtok": costs.usd(p.input_micro), "output_usd_per_mtok": costs.usd(p.output_micro),
            "cache_read_usd_per_mtok": costs.usd(p.cache_read_micro),
            "cache_write_usd_per_mtok": costs.usd(p.cache_write_micro)}


def prices(db: Session, organization_id: uuid.UUID) -> list[dict]:
    rows = db.execute(select(ModelPrice).where(ModelPrice.organization_id == organization_id)).scalars().all()
    own = {(r.adapter_type, r.model): r for r in rows}
    out = [_price_out(r.adapter_type, r.model, costs.price_for(db, organization_id, r.adapter_type, r.model), r.id)
           for r in rows]
    for adapter, model in costs.DEFAULT_PRICES_USD:
        if (adapter, model) not in own:
            out.append(_price_out(adapter, model, costs.price_for(db, organization_id, adapter, model)))
    return sorted(out, key=lambda p: (p["adapter_type"], p["model"]))


def provider_state(provider: AiProvider) -> dict:
    reason = costs.paused_reason(provider)
    return {"paused": reason is not None, "paused_reason": reason,
            "paused_until": provider.paused_until.isoformat() if reason and provider.paused_until else None}


def summary(db: Session, organization_id: uuid.UUID) -> dict:
    """This month's spend, budgets, provider pauses and prices."""
    since = costs.month_start()
    total, unpriced = costs.spent(db, organization_id)
    by_model = db.execute(
        select(AiProvider.name, AgentRun.model, func.count(), func.coalesce(func.sum(TokenUsage.cost_micro_usd), 0),
               func.coalesce(func.sum(TokenUsage.input_tokens), 0), func.coalesce(func.sum(TokenUsage.output_tokens), 0),
               func.coalesce(func.sum(TokenUsage.cache_read_tokens), 0))
        .join(AgentRun, AgentRun.id == TokenUsage.agent_run_id)
        .join(AiProvider, AiProvider.id == AgentRun.provider_id)
        .where(AgentRun.organization_id == organization_id, AgentRun.created_at >= since)
        .group_by(AiProvider.name, AgentRun.model).order_by(AiProvider.name, AgentRun.model)).all()
    by_project = db.execute(
        select(Project.id, Project.name, func.coalesce(func.sum(TokenUsage.cost_micro_usd), 0))
        .join(AgentRun, AgentRun.project_id == Project.id).join(TokenUsage, TokenUsage.agent_run_id == AgentRun.id)
        .where(AgentRun.organization_id == organization_id, AgentRun.created_at >= since)
        .group_by(Project.id, Project.name).order_by(Project.name)).all()
    budgets = db.execute(select(SpendBudget).where(SpendBudget.organization_id == organization_id)).scalars().all()
    states = []
    for b in budgets:
        used, _ = costs.spent(db, organization_id, b.project_id)
        states.append(costs.describe_budget(costs.BudgetState(
            b, used, used >= b.monthly_limit_micro_usd, used >= b.monthly_limit_micro_usd * b.warn_percent / 100)))
    providers = db.execute(select(AiProvider).where(AiProvider.organization_id == organization_id)
                           .order_by(AiProvider.name)).scalars().all()
    return {
        "month_start": since.isoformat(),
        "spent_usd": costs.usd(total),
        "unpriced_runs": unpriced,
        "by_model": [{"provider": n, "model": m, "runs": c, "spent_usd": costs.usd(s), "input_tokens": i,
                      "output_tokens": o, "cache_read_tokens": cr} for n, m, c, s, i, o, cr in by_model],
        "by_project": [{"project_id": str(pid), "name": name, "spent_usd": costs.usd(s)} for pid, name, s in by_project],
        "budgets": states,
        "providers": [{"id": str(p.id), "name": p.name, "adapter_type": p.adapter_type, **provider_state(p)}
                      for p in providers],
        "prices": prices(db, organization_id),
    }


def overview(db: Session, organization_id: uuid.UUID) -> dict:
    """The short version for the Oversight page."""
    total, unpriced = costs.spent(db, organization_id)
    org_budget = db.execute(select(SpendBudget).where(SpendBudget.organization_id == organization_id,
                                                      SpendBudget.project_id.is_(None))).scalar_one_or_none()
    paused = [p.name for p in db.execute(select(AiProvider).where(AiProvider.organization_id == organization_id))
              .scalars() if costs.paused_reason(p)]
    return {"spent_usd": costs.usd(total), "unpriced_runs": unpriced,
            "limit_usd": costs.usd(org_budget.monthly_limit_micro_usd) if org_budget else None,
            "warn_percent": org_budget.warn_percent if org_budget else None, "paused_providers": paused}


# Endpoints -----------------------------------------------------------------------------------------------------------


@router.get("/spend")
def get_spend(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    _require_admin(db, caller.user, organization_id)
    return summary(db, organization_id)


@router.put("/model-prices")
def put_price(organization_id: uuid.UUID, body: PriceIn, caller: CsrfCaller, db: DbSession) -> dict:
    _require_admin(db, caller.user, organization_id)
    row = db.execute(select(ModelPrice).where(ModelPrice.organization_id == organization_id,
                                              ModelPrice.adapter_type == body.adapter_type,
                                              ModelPrice.model == body.model)).scalar_one_or_none()
    if row is None:
        row = ModelPrice(id=uuid7(), organization_id=organization_id, adapter_type=body.adapter_type, model=body.model)
        db.add(row)
    row.input_micro_usd = _micro(body.input_usd_per_mtok)
    row.output_micro_usd = _micro(body.output_usd_per_mtok)
    row.cache_read_micro_usd = _micro(body.cache_read_usd_per_mtok if body.cache_read_usd_per_mtok is not None
                                      else body.input_usd_per_mtok * costs.CACHE_READ_FACTOR)
    row.cache_write_micro_usd = _micro(body.cache_write_usd_per_mtok if body.cache_write_usd_per_mtok is not None
                                       else body.input_usd_per_mtok * costs.CACHE_WRITE_FACTOR)
    row.updated_at = datetime.now(UTC)
    _audit(db, caller.user, organization_id, "spend.price_set",
           {"adapter_type": body.adapter_type, "model": body.model, "input_micro": row.input_micro_usd,
            "output_micro": row.output_micro_usd})
    db.commit()
    return {"items": prices(db, organization_id)}


@router.delete("/model-prices/{price_id}")
def delete_price(organization_id: uuid.UUID, price_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    """Removes the organization's own price: the published default (if any) applies again."""
    _require_admin(db, caller.user, organization_id)
    row = db.get(ModelPrice, price_id)
    if row is None or row.organization_id != organization_id:
        raise not_found()
    _audit(db, caller.user, organization_id, "spend.price_removed", {"adapter_type": row.adapter_type,
                                                                     "model": row.model})
    db.delete(row)
    db.commit()
    return {"items": prices(db, organization_id)}


@router.put("/spend-budgets")
def put_budget(organization_id: uuid.UUID, body: BudgetIn, caller: CsrfCaller, db: DbSession) -> dict:
    _require_admin(db, caller.user, organization_id)
    if body.project_id is not None:
        project = db.get(Project, body.project_id)
        if project is None or project.organization_id != organization_id:
            raise not_found()
    scope = (SpendBudget.project_id.is_(None) if body.project_id is None
             else SpendBudget.project_id == body.project_id)
    row = db.execute(select(SpendBudget).where(SpendBudget.organization_id == organization_id, scope)) \
        .scalar_one_or_none()
    if row is None:
        row = SpendBudget(id=uuid7(), organization_id=organization_id, project_id=body.project_id)
        db.add(row)
    row.monthly_limit_micro_usd = _micro(body.limit_usd)
    row.warn_percent = body.warn_percent
    row.on_limit = body.on_limit
    row.updated_at = datetime.now(UTC)
    _audit(db, caller.user, organization_id, "spend.budget_set",
           {"project": str(body.project_id) if body.project_id else None, "limit_micro": row.monthly_limit_micro_usd,
            "warn_percent": row.warn_percent, "on_limit": row.on_limit})
    db.commit()
    return summary(db, organization_id)


@router.delete("/spend-budgets/{budget_id}")
def delete_budget(organization_id: uuid.UUID, budget_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    _require_admin(db, caller.user, organization_id)
    row = db.get(SpendBudget, budget_id)
    if row is None or row.organization_id != organization_id:
        raise not_found()
    _audit(db, caller.user, organization_id, "spend.budget_removed",
           {"project": str(row.project_id) if row.project_id else None})
    db.delete(row)
    db.commit()
    return summary(db, organization_id)


@router.post("/providers/{provider_id}/resume")
def resume_provider(organization_id: uuid.UUID, provider_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    """Clears a pause, for example after adding credit or fixing a key. A failure pauses it again."""
    _require_admin(db, caller.user, organization_id)
    provider = db.get(AiProvider, provider_id)
    if provider is None or provider.organization_id != organization_id:
        raise not_found()
    was = provider.paused_reason
    provider.paused_until, provider.paused_reason = None, None
    _audit(db, caller.user, organization_id, "provider.resumed", {"provider": str(provider.id), "was": was})
    db.commit()
    return {"id": str(provider.id), **provider_state(provider)}


@router.patch("/model-routes/{route_id}")
def set_strategy(organization_id: uuid.UUID, route_id: uuid.UUID, body: StrategyIn, caller: CsrfCaller,
                 db: DbSession) -> dict:
    _require_admin(db, caller.user, organization_id)
    route = db.get(ModelRoute, route_id)
    if route is None or route.organization_id != organization_id:
        raise not_found()
    if body.strategy == route.strategy:
        return {"id": str(route.id), "key": route.key, "strategy": route.strategy}
    route.strategy = body.strategy
    _audit(db, caller.user, organization_id, "route.strategy_set", {"route": route.key, "strategy": body.strategy})
    db.commit()
    return {"id": str(route.id), "key": route.key, "strategy": route.strategy}
