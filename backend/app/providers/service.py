"""Provider administration and execution.

Execution contract for one stage task:
- candidates are the route's primary provider and model, then its fallbacks, in order
- retryable errors are retried with backoff on the same candidate; non-retryable errors move on
- output must parse as a JSON object with the task's required keys; one repair attempt is made
  on the same candidate before moving on
- every provider call writes an AgentRun row and an audit event; metadata only, never prompts,
  outputs or credentials
- the caller's transaction owns the commit, so run records and the stage transition land together
"""

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.config import Settings
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.organizations.models import Membership
from app.providers.adapters import build_adapter
from app.providers.base import ADAPTER_TYPES, CompletionRequest, ProviderAdapter, ProviderError
from app.providers.models import AgentRun, AiProvider, ModelRoute, SecretReference, TokenUsage
from app.providers.secrets import Sealed, SecretError, open_secret, seal
from app.providers.tasks import AiTask, system_prompt, user_prompt

MAX_ATTEMPTS = 3  # first try plus two retries, per candidate
# Micro-USD per million tokens, keyed by (adapter_type, model). Empty by default: a cost is only
# reported when a price has been entered for that exact model. Prices are never guessed.
PRICES_MICRO_USD_PER_MTOK: dict[tuple[str, str], tuple[int, int]] = {}


class ProviderRunFailed(Exception):
    def __init__(self, kind: str, attempts: int) -> None:
        super().__init__(kind)
        self.kind = kind
        self.attempts = attempts


@dataclass(frozen=True)
class _Outcome:
    text: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    kind: str | None


def cost_micro_usd(adapter_type: str, model: str, input_tokens: int, output_tokens: int) -> int | None:
    price = PRICES_MICRO_USD_PER_MTOK.get((adapter_type, model))
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) // 1_000_000


def _require_admin(db: Session, user: User, organization_id: uuid.UUID) -> None:
    membership = db.execute(
        select(Membership).where(Membership.user_id == user.id, Membership.organization_id == organization_id)
    ).scalar_one_or_none()
    if membership is None:
        raise not_found()
    if membership.role != "org_admin":
        raise AppError(403, "not_permitted", "Only organization administrators manage providers")


def _store_secret(db: Session, settings: Settings, user: User, organization_id: uuid.UUID, name: str,
                  api_key: str) -> SecretReference:
    sealed = seal(settings, api_key, organization_id=str(organization_id), name=name)
    ref = SecretReference(
        id=uuid7(),
        organization_id=organization_id,
        name=name,
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
        key_version=sealed.key_version,
        last4=sealed.last4,
        created_by=user.id,
    )
    db.add(ref)
    db.flush()
    return ref


def _validate_base_url(adapter_type: str, base_url: str | None) -> None:
    if base_url is None:
        return
    if not base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise AppError(422, "invalid_base_url", "base_url must use https (plain http only for localhost)")


def create_provider(db: Session, settings: Settings, user: User, *, organization_id: uuid.UUID, name: str,
                    adapter_type: str, base_url: str | None, api_key: str | None) -> AiProvider:
    _require_admin(db, user, organization_id)
    if adapter_type not in ADAPTER_TYPES:
        raise AppError(422, "invalid_adapter", "Unknown adapter type")
    if adapter_type == "mock" and settings.app_env not in ("development", "test"):
        raise AppError(422, "invalid_adapter", "The mock provider is not available in this environment")
    if adapter_type in ("anthropic", "openai", "gemini") and not api_key:
        raise AppError(422, "api_key_required", "This provider needs an API key")
    if adapter_type == "openai_compatible" and not base_url:
        raise AppError(422, "base_url_required", "An OpenAI-compatible server needs a base URL")
    _validate_base_url(adapter_type, base_url)
    if db.execute(select(AiProvider.id).where(AiProvider.organization_id == organization_id,
                                              AiProvider.name == name)).first():
        raise AppError(409, "provider_exists", "A provider with this name already exists")

    ref = _store_secret(db, settings, user, organization_id, f"provider:{name}", api_key) if api_key else None
    provider = AiProvider(
        id=uuid7(),
        organization_id=organization_id,
        name=name,
        adapter_type=adapter_type,
        base_url=base_url,
        secret_reference_id=ref.id if ref else None,
        status="active",
    )
    db.add(provider)
    db.flush()
    append_event(db, chain_key=org_chain(organization_id), event_type="provider.created",
                 actor_type="human", actor_id=str(user.id), organization_id=organization_id,
                 payload={"provider": str(provider.id), "adapter": adapter_type})
    db.commit()
    return provider


def rotate_key(db: Session, settings: Settings, user: User, *, organization_id: uuid.UUID,
               provider_id: uuid.UUID, api_key: str) -> AiProvider:
    _require_admin(db, user, organization_id)
    provider = _provider(db, organization_id, provider_id)
    if provider.secret_reference_id is None:
        raise AppError(422, "no_secret", "This provider does not use an API key")
    old = db.get(SecretReference, provider.secret_reference_id)
    ref = _store_secret(db, settings, user, organization_id, f"provider:{provider.name}", api_key)
    old.rotated_at = ref.created_at
    provider.secret_reference_id = ref.id
    append_event(db, chain_key=org_chain(organization_id), event_type="provider.key_rotated",
                 actor_type="human", actor_id=str(user.id), organization_id=organization_id,
                 payload={"provider": str(provider.id)})
    db.commit()
    return provider


def _provider(db: Session, organization_id: uuid.UUID, provider_id: uuid.UUID) -> AiProvider:
    provider = db.get(AiProvider, provider_id)
    if provider is None or provider.organization_id != organization_id:
        raise not_found()
    return provider


def create_route(db: Session, user: User, *, organization_id: uuid.UUID, key: str, primary_provider_id: uuid.UUID,
                 primary_model: str, fallbacks: list[dict[str, Any]]) -> ModelRoute:
    _require_admin(db, user, organization_id)
    _provider(db, organization_id, primary_provider_id)
    checked: list[dict[str, str]] = []
    for fb in fallbacks:
        provider_id = uuid.UUID(str(fb["provider_id"]))
        _provider(db, organization_id, provider_id)
        checked.append({"provider_id": str(provider_id), "model": str(fb["model"])})
    if db.execute(select(ModelRoute.id).where(ModelRoute.organization_id == organization_id,
                                              ModelRoute.key == key)).first():
        raise AppError(409, "route_exists", "A route with this key already exists")
    route = ModelRoute(id=uuid7(), organization_id=organization_id, key=key,
                       primary_provider_id=primary_provider_id, primary_model=primary_model, fallbacks=checked)
    db.add(route)
    db.commit()
    return route


def _adapter(db: Session, settings: Settings, provider: AiProvider, transport: httpx.BaseTransport | None) -> ProviderAdapter:
    api_key = None
    if provider.secret_reference_id is not None:
        ref = db.get(SecretReference, provider.secret_reference_id)
        api_key = open_secret(settings, _sealed(ref), organization_id=str(provider.organization_id),
                              name=ref.name)
    return build_adapter(provider.adapter_type, api_key=api_key, base_url=provider.base_url,
                         transport=transport, app_env=settings.app_env)


def _sealed(ref: SecretReference) -> Sealed:
    return Sealed(ciphertext=ref.ciphertext, nonce=ref.nonce, key_version=ref.key_version, last4=ref.last4)


def _call_with_retries(adapter: ProviderAdapter, request: CompletionRequest, settings: Settings) -> list[_Outcome]:
    """Every HTTP attempt is returned in order. Retryable errors back off and retry on the same
    candidate; anything else stops at once. The last outcome decides success."""
    outcomes: list[_Outcome] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = adapter.complete(request)
            outcomes.append(_Outcome(result.text, result.usage.input_tokens, result.usage.output_tokens,
                                     result.latency_ms, None))
            return outcomes
        except ProviderError as exc:
            outcomes.append(_Outcome(None, 0, 0, 0, exc.kind))
            if not exc.retryable or attempt == MAX_ATTEMPTS:
                break
            time.sleep(settings.provider_backoff_seconds * (2 ** (attempt - 1)))
    return outcomes


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_output(text: str, required: tuple[str, ...]) -> dict[str, Any] | None:
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        data = json.loads(cleaned)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if any(key not in data or data[key] in (None, "") for key in required):
        return None
    return data


def _record(db: Session, *, organization_id, project_id, stage_execution_id, route_key, provider: AiProvider,
            model: str, attempt: int, outcome: _Outcome, settings: Settings, kind: str = "lead",
            agent_version_id: uuid.UUID | None = None, manifest: dict[str, Any] | None = None) -> uuid.UUID:
    status = "failed" if outcome.kind else "succeeded"
    run = AgentRun(
        id=uuid7(),
        organization_id=organization_id,
        project_id=project_id,
        stage_execution_id=stage_execution_id,
        route_key=route_key,
        provider_id=provider.id,
        adapter_type=provider.adapter_type,
        model=model,
        attempt=attempt,
        status=status,
        error_kind=outcome.kind,
        latency_ms=outcome.latency_ms,
        kind=kind,
        agent_version_id=agent_version_id,
        context_manifest=manifest or {},
    )
    db.add(run)
    db.flush()
    if status == "succeeded":
        db.add(TokenUsage(
            agent_run_id=run.id,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            cost_micro_usd=cost_micro_usd(provider.adapter_type, model, outcome.input_tokens, outcome.output_tokens),
        ))
    append_event(
        db,
        chain_key=org_chain(organization_id),
        event_type="provider.call",
        actor_type="provider",
        actor_id=str(provider.id),
        organization_id=organization_id,
        project_id=project_id,
        payload={"route": route_key, "adapter": provider.adapter_type, "model": model, "attempt": attempt,
                 "status": status, "error_kind": outcome.kind, "latency_ms": outcome.latency_ms,
                 "input_tokens": outcome.input_tokens, "output_tokens": outcome.output_tokens},
    )
    return run.id


def run_structured(
    db: Session,
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    stage_execution_id: uuid.UUID,
    route_key: str,
    system: str,
    user: str,
    required_keys: tuple[str, ...],
    kind: str = "lead",
    agent_version_id: uuid.UUID | None = None,
    manifest: dict[str, Any] | None = None,
    accept: Callable[[dict[str, Any]], str | None] | None = None,
    sink: list[uuid.UUID] | None = None,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    """One structured call with fallback, retries and one repair. Every attempt is recorded.

    accept, when given, returns an error message for output that parses but is not acceptable;
    such output is treated like output that does not parse.
    """
    route = db.execute(select(ModelRoute).where(ModelRoute.organization_id == organization_id,
                                                ModelRoute.key == route_key)).scalar_one_or_none()
    if route is None:
        raise ProviderRunFailed("no_route", 0)
    candidates = [(route.primary_provider_id, route.primary_model)] + [
        (uuid.UUID(f["provider_id"]), f["model"]) for f in route.fallbacks
    ]
    if not allow_fallback:
        candidates = candidates[:1]  # pinned: the primary provider only, no fallback
    base = CompletionRequest(system=system, user=user, model="")
    attempts_total = 0
    last_kind = "unavailable"
    last_run_id: uuid.UUID | None = None
    for provider_id, model in candidates:
        provider = db.get(AiProvider, provider_id)
        if provider is None or provider.organization_id != organization_id or provider.status != "active":
            last_kind = "invalid_request"
            continue
        try:
            adapter = _adapter(db, settings, provider, transport)
        except (SecretError, ProviderError):
            last_kind = "auth"
            continue
        request = replace(base, model=model)
        for repair in (False, True):
            attempts_total += 1
            outcomes = _call_with_retries(adapter, request, settings)
            for index, outcome in enumerate(outcomes):
                if index > 0:
                    attempts_total += 1
                run_id = _record(db, organization_id=organization_id, project_id=project_id,
                                 stage_execution_id=stage_execution_id, route_key=route_key, provider=provider,
                                 model=model, attempt=attempts_total, outcome=outcome, settings=settings,
                                 kind=kind, agent_version_id=agent_version_id, manifest=manifest)
                last_run_id = run_id
            outcome = outcomes[-1]
            if outcome.kind is not None:
                last_kind = outcome.kind
                break
            parsed = parse_output(outcome.text or "", required_keys)
            if parsed is not None and (accept is None or accept(parsed) is None):
                if sink is not None:
                    sink.append(last_run_id)
                return parsed
            last_kind = "bad_response"
            request = replace(
                request,
                user=request.user + "\nYour last reply was not acceptable: it must be a JSON object with the "
                "required keys and valid values. Reply again with only that object.",
            )
            if repair:
                break
    raise ProviderRunFailed(last_kind, attempts_total)


def run_task(
    db: Session,
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    stage_execution_id: uuid.UUID,
    route_key: str,
    task: AiTask,
    project_name: str,
    project_type: str,
    description: str,
    feedback: tuple[str, ...] = (),
    rules_text: str = "",
    rule_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system = system_prompt(task)
    return run_structured(
        db, settings, transport=transport, organization_id=organization_id, project_id=project_id,
        stage_execution_id=stage_execution_id, route_key=route_key,
        system=f"{rules_text}\n\n{system}" if rules_text else system,
        user=user_prompt(project_name, project_type, description, feedback),
        required_keys=task.required_keys,
        manifest={"sources": ["project_input", "feedback"], "feedback_count": len(feedback),
                  "rules": rule_refs or []},
    )


def probe(db: Session, settings: Settings, user: User, *, organization_id: uuid.UUID, provider_id: uuid.UUID,
          model: str, transport: httpx.BaseTransport | None) -> dict[str, Any]:
    _require_admin(db, user, organization_id)
    provider = _provider(db, organization_id, provider_id)
    started = time.perf_counter()
    try:
        adapter = _adapter(db, settings, provider, transport)
        outcomes = _call_with_retries(
            adapter,
            CompletionRequest(system="Reply with JSON. KEYS: ok", user="health check", model=model,
                              max_tokens=16, timeout_seconds=15),
            settings,
        )
        error = outcomes[-1].kind
    except (SecretError, ProviderError) as exc:
        error = exc.kind if isinstance(exc, ProviderError) else "auth"
    latency = int((time.perf_counter() - started) * 1000)
    ok = error is None
    provider.last_health_ok = ok
    provider.last_health_at = datetime.now(UTC)
    provider.last_health_error = None if ok else error
    append_event(db, chain_key=org_chain(organization_id), event_type="provider.health_checked",
                 actor_type="provider", actor_id=str(provider.id), organization_id=organization_id,
                 payload={"ok": ok, "error_kind": error, "latency_ms": latency})
    db.commit()
    return {"ok": ok, "error_kind": error, "latency_ms": latency}
