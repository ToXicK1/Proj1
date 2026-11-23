"""Money: what each model costs, what has been spent, budgets, and which providers are paused.

Prices are per million tokens. Claude's are seeded from Anthropic's published list prices (as of 2026-11-03);
administrators can override any price, and must enter prices for other providers: a cost is never guessed, so a
model with no price records no cost and does not count toward a budget (the spend view says how many such runs
there were). Cache reads are billed at about a tenth of the input price, cache writes at about 1.25 times.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.providers.models import AgentRun, AiProvider, ModelPrice, SpendBudget, TokenUsage

MICRO = 1_000_000

# (input, output) US dollars per million tokens, Anthropic list prices (claude-api reference, 2026-11-03).
DEFAULT_PRICES_USD: dict[tuple[str, str], tuple[float, float]] = {
    ("anthropic", "claude-opus-5-5"): (4.00, 20.00),
    ("anthropic", "claude-sonnet-5-5"): (2.00, 10.00),
    ("anthropic", "claude-haiku-5-5"): (0.10, 0.50),
    ("anthropic", "claude-fable-5-2"): (8.00, 40.00),
    ("anthropic", "claude-opus-5"): (5.00, 25.00),
    ("anthropic", "claude-sonnet-5"): (2.00, 10.00),
}
CACHE_READ_FACTOR = 0.1
CACHE_WRITE_FACTOR = 1.25


@dataclass(frozen=True)
class Price:
    input_micro: int  # micro-dollars per million input tokens
    output_micro: int
    cache_read_micro: int
    cache_write_micro: int
    source: str  # "organization" or "default"

    def cost(self, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> int:
        """Micro-dollars. input_tokens are the uncached input tokens."""
        return (input_tokens * self.input_micro + output_tokens * self.output_micro
                + cache_read * self.cache_read_micro + cache_write * self.cache_write_micro) // MICRO


def _from_usd(inp: float, out: float, source: str) -> Price:
    return Price(int(inp * MICRO), int(out * MICRO), int(inp * CACHE_READ_FACTOR * MICRO),
                 int(inp * CACHE_WRITE_FACTOR * MICRO), source)


def price_for(db: Session, organization_id: uuid.UUID, adapter_type: str, model: str) -> Price | None:
    row = db.execute(select(ModelPrice).where(ModelPrice.organization_id == organization_id,
                                              ModelPrice.adapter_type == adapter_type,
                                              ModelPrice.model == model)).scalar_one_or_none()
    if row is not None:
        return Price(row.input_micro_usd, row.output_micro_usd, row.cache_read_micro_usd, row.cache_write_micro_usd,
                     "organization")
    if (adapter_type, model) in DEFAULT_PRICES_USD:
        return _from_usd(*DEFAULT_PRICES_USD[(adapter_type, model)], "default")
    if adapter_type == "mock":
        return Price(0, 0, 0, 0, "default")
    return None


def estimate(price: Price | None, prompt_chars: int, max_output_tokens: int) -> int | None:
    """An upper bound for one call, before it is made: about four characters per token, and the full output
    allowance. Unknown price: unknown cost."""
    if price is None:
        return None
    return price.cost(prompt_chars // 4, max_output_tokens)


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(now: datetime | None = None) -> datetime:
    start = month_start(now)
    return (start + timedelta(days=32)).replace(day=1)


def spent(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None = None,
          since: datetime | None = None) -> tuple[int, int]:
    """(micro-dollars spent, runs with no price) this month for the organization, or one project."""
    query = select(func.coalesce(func.sum(TokenUsage.cost_micro_usd), 0),
                   func.count().filter(TokenUsage.cost_micro_usd.is_(None))) \
        .join(AgentRun, AgentRun.id == TokenUsage.agent_run_id) \
        .where(AgentRun.organization_id == organization_id, AgentRun.created_at >= (since or month_start()))
    if project_id is not None:
        query = query.where(AgentRun.project_id == project_id)
    total, unpriced = db.execute(query).one()
    return int(total), int(unpriced)


@dataclass(frozen=True)
class BudgetState:
    budget: SpendBudget
    spent: int
    over: bool
    warned: bool


def budget_states(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None) -> list[BudgetState]:
    """The organization's budget and, if set, the project's, with this month's spend against each."""
    rows = db.execute(select(SpendBudget).where(
        SpendBudget.organization_id == organization_id,
        (SpendBudget.project_id.is_(None)) | (SpendBudget.project_id == project_id))).scalars().all()
    out = []
    for row in rows:
        used, _ = spent(db, organization_id, row.project_id)
        out.append(BudgetState(row, used, used >= row.monthly_limit_micro_usd,
                               used >= row.monthly_limit_micro_usd * row.warn_percent / 100))
    return out


# Provider health -----------------------------------------------------------------------------------------------------

COOLDOWN_SECONDS = {"rate_limited": 60.0, "unavailable": 30.0, "timeout": 30.0}


def paused_reason(provider: AiProvider, now: datetime | None = None) -> str | None:
    now = now or datetime.now(UTC)
    if provider.paused_until is not None and provider.paused_until > now:
        return provider.paused_reason or "paused"
    return None


def is_long_pause(provider: AiProvider, now: datetime | None = None) -> bool:
    """Out of credit or key refused, as opposed to a cooldown of at most an hour."""
    now = now or datetime.now(UTC)
    return provider.paused_until is not None and provider.paused_until > now + timedelta(hours=1, minutes=1)


def pause_for(kind: str, retry_after: float | None, now: datetime | None = None) -> tuple[datetime, str] | None:
    """How long a provider is skipped after a failure, and why. None: no pause."""
    now = now or datetime.now(UTC)
    if kind == "quota_exhausted":
        return next_month_start(now), "out of credit or at its spend cap"
    if kind == "auth":
        return now + timedelta(days=3650), "the API key was refused"
    if kind in COOLDOWN_SECONDS:
        wait = retry_after if retry_after and 0 < retry_after <= 3600 else COOLDOWN_SECONDS[kind]
        return now + timedelta(seconds=wait), {"rate_limited": "rate limited", "unavailable": "not answering",
                                               "timeout": "too slow to answer"}[kind]
    return None


def usd(micro: int | None) -> float | None:
    return None if micro is None else round(micro / MICRO, 4)


def describe_budget(state: BudgetState) -> dict[str, Any]:
    b = state.budget
    return {"id": str(b.id), "project_id": str(b.project_id) if b.project_id else None,
            "limit_usd": usd(b.monthly_limit_micro_usd), "warn_percent": b.warn_percent, "on_limit": b.on_limit,
            "spent_usd": usd(state.spent), "over": state.over, "warned": state.warned}
