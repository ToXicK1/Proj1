from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_PLACEHOLDER = "dev-only-change-me"


class Settings(BaseSettings):
    """Runtime configuration. All values come from AIDLC_* environment variables or .env."""

    model_config = SettingsConfigDict(env_prefix="AIDLC_", env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+pg8000://aidlc:aidlc@localhost:5432/aidlc"
    secret_key: str = DEV_SECRET_PLACEHOLDER
    public_base_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173"]

    session_cookie_name: str = "aidlc_session"
    session_ttl_hours: int = 8
    cookie_secure: bool = False

    min_password_length: int = 12
    max_password_length: int = 128
    email_token_ttl_hours: int = 24
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    auth_rate_limit_per_minute: int = 20
    invite_ttl_days: int = 7
    invites_per_org_per_hour: int = 30

    # Base64 of 32 random bytes. Required outside development. Store in a secret manager.
    secret_encryption_key: str | None = None
    provider_backoff_seconds: float = 0.5
    provider_timeout_seconds: float = 120.0  # a full deliverable takes longer than a short answer
    provider_max_tokens: int = 4096
    signup_mode: Literal["shared", "personal"] = "shared"  # one organization, or one per signup
    bootstrap_admin_email: str | None = None  # an existing account that administers the shared organization
    default_llm_base_url: str | None = None  # connected automatically for the shared organization
    default_llm_model: str | None = None
    default_llm_adapter: str = "openai_compatible"
    sandbox_dir: str | None = None  # the job folder shared with the sandbox service
    sandbox_timeout_seconds: float = 200.0

    # Job queue and worker (RD-4)
    jobs_inline: bool = False  # tests only: the API runs queued jobs itself after the response
    job_lease_seconds: float = 300.0  # a worker that stops renewing for this long loses its job to another
    job_poll_seconds: float = 1.0
    job_sweep_interval_seconds: float = 60.0
    job_sweep_grace_seconds: float = 120.0  # how long work may wait without a job before the sweep queues one

    # Object storage (RD-5): S3 API, MinIO locally. Credentials come only from the environment.
    storage_endpoint: str | None = None  # for example http://minio:9000; unset disables object storage
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    storage_bucket: str = "aidlc"
    storage_region: str = "us-east-1"

    @property
    def storage_enabled(self) -> bool:
        return bool(self.storage_endpoint and self.storage_access_key and self.storage_secret_key)

    def assert_safe_for_environment(self) -> None:
        """Refuse to run outside development with the placeholder signing key."""
        if self.app_env != "development" and self.secret_key == DEV_SECRET_PLACEHOLDER:
            raise RuntimeError("AIDLC_SECRET_KEY must be set outside development")
        if self.jobs_inline and self.app_env not in ("development", "test"):
            raise RuntimeError("AIDLC_JOBS_INLINE is for tests; production work runs in the worker")


@lru_cache
def get_settings() -> Settings:
    return Settings()
