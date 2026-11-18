"""Import every model so Base.metadata is complete (used by Alembic and the drift test)."""

from app.approvals.models import ApprovalDecision, ChangeRequest  # noqa: F401
from app.artifacts.models import Artifact, ArtifactVersion  # noqa: F401
from app.audit.models import AuditChain, AuditEvent  # noqa: F401
from app.auth.models import EmailToken, User, UserSession  # noqa: F401
from app.core.db import Base
from app.notifications.models import EmailOutbox  # noqa: F401
from app.organizations.models import Membership, Organization  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401
from app.providers.models import AgentRun, AiProvider, ModelRoute, SecretReference, TokenUsage  # noqa: F401
from app.workflows.models import (  # noqa: F401
    StageExecution,
    StageTransition,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowVersion,
)

metadata = Base.metadata
