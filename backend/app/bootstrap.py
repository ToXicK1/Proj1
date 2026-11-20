"""Makes a fresh platform usable: ready workflows, the shared organization and the default AI connection.

Run at start-up (`python -m app.bootstrap`). Every step is safe to repeat.
"""

import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (registers every table)
from app.auth.models import User
from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_session_factory
from app.organizations.models import Membership, Organization
from app.portal import lifecycle
from app.providers import service as providers
from app.providers.models import AiProvider, ModelRoute
from app.storage import service as storage
from app.storage.s3 import StorageError
from app.workflows.compiler import compile_workflow
from app.workflows.models import WorkflowDefinition, WorkflowVersion
from app.workflows.seed import seed_templates
from app.workflows.service import publish_version
from app.workflows.work import KNOWN_WORK

DEFAULT_ROUTE = "default"
DEFAULT_PROVIDER = "Local AI"


def seed_lifecycle(db: Session) -> None:
    seed_templates(db)
    for scope in lifecycle.SCOPES:
        spec = lifecycle.workflow_spec(scope)
        compiled = compile_workflow(spec, known_work=set(KNOWN_WORK))
        latest = db.execute(
            select(WorkflowVersion.sha256).join(WorkflowDefinition)
            .where(WorkflowDefinition.organization_id.is_(None), WorkflowDefinition.key == spec["key"])
            .order_by(WorkflowVersion.version.desc())).scalars().first()
        if latest != compiled.sha256:
            publish_version(db, spec)


def connect_default_ai(db: Session, settings: Settings, org: Organization, admin: User) -> None:
    """Connects the configured model once. Changes made later by an administrator are left alone."""
    mock = settings.default_llm_adapter == "mock"  # offline connection, for automated browser tests
    if not settings.default_llm_model or not (mock or settings.default_llm_base_url):
        return
    has_route = db.execute(select(ModelRoute.id).where(ModelRoute.organization_id == org.id,
                                                       ModelRoute.key == DEFAULT_ROUTE)).first()
    if not has_route:
        provider = db.execute(select(AiProvider).where(AiProvider.organization_id == org.id,
                                                       AiProvider.name == DEFAULT_PROVIDER)).scalar_one_or_none()
        if provider is None:
            provider = providers.create_provider(
                db, settings, admin, organization_id=org.id, name=DEFAULT_PROVIDER,
                adapter_type=settings.default_llm_adapter, base_url=None if mock else settings.default_llm_base_url,
                api_key=None)
        providers.create_route(db, admin, organization_id=org.id, key=DEFAULT_ROUTE, primary_provider_id=provider.id,
                               primary_model=settings.default_llm_model, fallbacks=[])
    lifecycle.provision(db, admin, org.id, DEFAULT_ROUTE)


def prepare_shared_org(db: Session, settings: Settings) -> None:
    """Makes the configured administrator's organization the shared one, when none exists yet."""
    org = db.execute(select(Organization).where(Organization.is_default.is_(True))).scalar_one_or_none()
    admin = None
    if settings.bootstrap_admin_email:
        admin = db.execute(select(User).where(User.email == settings.bootstrap_admin_email.strip().lower(),
                                              User.status == "active")).scalar_one_or_none()
    if org is None and admin is not None:
        org = db.execute(select(Organization).join(Membership).where(
            Membership.user_id == admin.id, Membership.role == "org_admin").order_by(Organization.created_at)
        ).scalars().first()
        if org is not None:
            org.is_default = True
            db.commit()
    if org is None:
        return
    if admin is None or not db.execute(select(Membership.id).where(
            Membership.organization_id == org.id, Membership.user_id == admin.id,
            Membership.role == "org_admin", Membership.status == "active")).first():
        admin = db.execute(select(User).join(Membership, Membership.user_id == User.id).where(
            Membership.organization_id == org.id, Membership.role == "org_admin",
            Membership.status == "active").order_by(Membership.created_at)).scalars().first()
    if admin is not None:
        connect_default_ai(db, settings, org, admin)


def prepare_storage(settings: Settings, attempts: int = 30) -> None:
    """Creates the bucket. The storage server may still be starting, so this waits up to about a minute."""
    if not settings.storage_enabled:
        return
    for attempt in range(attempts):
        try:
            storage.ensure_bucket(settings)
            return
        except (httpx.HTTPError, StorageError):
            if attempt == attempts - 1:
                raise
            time.sleep(2)


def main() -> None:
    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        seed_lifecycle(db)
        prepare_shared_org(db, settings)
    prepare_storage(settings)


if __name__ == "__main__":
    main()
