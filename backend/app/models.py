"""Import every model so Base.metadata is complete (used by Alembic and the drift test)."""

from app.agents.models import AgentConfiguration, AgentConfigVersion, Profile, ReviewRecord  # noqa: F401
from app.approvals.models import ApprovalDecision, ChangeRequest  # noqa: F401
from app.artifacts.models import Artifact, ArtifactVersion  # noqa: F401
from app.audit.models import AuditChain, AuditEvent  # noqa: F401
from app.auth.models import EmailToken, User, UserSession  # noqa: F401
from app.core.db import Base
from app.hooks.models import HookDefinition, HookExecution, HookVersion  # noqa: F401
from app.notifications.models import EmailOutbox, Notification  # noqa: F401
from app.organizations.models import Membership, Organization, OrganizationInvitation  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401
from app.providers.models import AgentRun, AiProvider, ModelRoute, SecretReference, TokenUsage  # noqa: F401
from app.rules.models import ChangeProposal, ProjectTeam, Rule, RuleVersion, Team  # noqa: F401
from app.sensors.models import RiskAcceptance, SensorEvidence, SensorExecution  # noqa: F401
from app.skills.models import Skill, SkillVersion  # noqa: F401
from app.workflows.models import (  # noqa: F401
    StageExecution,
    StageTransition,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowVersion,
)

metadata = Base.metadata
