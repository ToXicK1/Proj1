from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.agents.router import router as agents_router
from app.approvals.router import router as approvals_router
from app.auth.router import router as auth_router
from app.collab.router import oversight_router, team_router
from app.collab.router import router as collab_router
from app.core import correlation
from app.core.config import Settings, get_settings
from app.core.correlation import CorrelationMiddleware
from app.core.db import make_engine, make_session_factory
from app.core.errors import register_error_handlers
from app.core.ratelimit import SlidingWindowLimiter
from app.governance.router import router as governance_router
from app.organizations.members_router import router as members_router
from app.organizations.router import router as orgs_router
from app.portal.router import router as portal_router
from app.projects.router import router as projects_router
from app.providers.router import router as providers_router
from app.skills.router import router as skills_router
from app.storage import service as storage
from app.studio.router import router as studio_router
from app.workflows.router import router as workflows_router


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.assert_safe_for_environment()

    app = FastAPI(title="AI-DLC Orchestration Platform", version="0.2.0", docs_url="/api/docs")
    app.state.settings = settings
    app.state.engine = engine or make_engine(settings.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.auth_limiter = SlidingWindowLimiter(settings.auth_rate_limit_per_minute)
    app.state.invite_limiter = SlidingWindowLimiter(settings.invites_per_org_per_hour, 3600.0)
    # Test hooks: httpx transports (for example httpx.MockTransport) replace the network for providers and storage.
    app.state.provider_transport = None
    app.state.storage_transport = None
    correlation.configure_logging()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    register_error_handlers(app)
    app.add_middleware(CorrelationMiddleware)  # outermost, so every response and log line carries the ID

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz() -> JSONResponse:
        """Ready to serve: the database answers and, when configured, object storage does too."""
        checks: dict[str, str] = {}
        try:
            with app.state.session_factory() as db:
                db.execute(text("select 1"))
            checks["database"] = "ok"
        except Exception:  # noqa: BLE001 - reported, not raised
            checks["database"] = "unavailable"
        if settings.storage_enabled:
            checks["storage"] = "ok" if storage.ready(settings, app.state.storage_transport) else "unavailable"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if ok else "unavailable", "checks": checks}, status_code=200 if ok else 503)

    app.include_router(auth_router)
    app.include_router(orgs_router)
    app.include_router(members_router)
    app.include_router(projects_router)
    app.include_router(workflows_router)
    app.include_router(approvals_router)
    app.include_router(providers_router)
    app.include_router(agents_router)
    app.include_router(skills_router)
    app.include_router(governance_router)
    app.include_router(studio_router)
    app.include_router(portal_router)
    app.include_router(collab_router)
    app.include_router(team_router)
    app.include_router(oversight_router)
    return app

