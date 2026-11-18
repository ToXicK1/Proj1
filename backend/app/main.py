from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from app.agents.router import router as agents_router
from app.approvals.router import router as approvals_router
from app.auth.router import router as auth_router
from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_session_factory
from app.core.errors import register_error_handlers
from app.core.ratelimit import SlidingWindowLimiter
from app.organizations.router import router as orgs_router
from app.projects.router import router as projects_router
from app.providers.router import router as providers_router
from app.workflows.router import router as workflows_router


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.assert_safe_for_environment()

    app = FastAPI(title="AI-DLC Orchestration Platform", version="0.2.0", docs_url="/api/docs")
    app.state.settings = settings
    app.state.engine = engine or make_engine(settings.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.auth_limiter = SlidingWindowLimiter(settings.auth_rate_limit_per_minute)
    # Test hook: an httpx transport (for example httpx.MockTransport) replaces the network for providers.
    app.state.provider_transport = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    register_error_handlers(app)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(orgs_router)
    app.include_router(projects_router)
    app.include_router(workflows_router)
    app.include_router(approvals_router)
    app.include_router(providers_router)
    app.include_router(agents_router)
    return app

