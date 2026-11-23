"""Import every model so Base.metadata is complete (used by Alembic and the drift test)."""

from app.activity.models import AiActivity  # noqa: F401
from app.agents.models import AgentConfiguration, AgentConfigVersion, Profile, ReviewRecord  # noqa: F401
from app.approvals.models import ApprovalDecision, ChangeRequest  # noqa: F401
from app.artifacts.models import Artifact, ArtifactVersion  # noqa: F401
from app.audit.models import AuditChain, AuditEvent  # noqa: F401
from app.auth.models import EmailToken, User, UserSession  # noqa: F401
from app.collab.models import TeamMessage, Ticket, TicketComment  # noqa: F401
from app.core.db import Base
from app.hooks.models import HookDefinition, HookExecution, HookVersion  # noqa: F401
from app.jobs.models import Job  # noqa: F401
from app.notifications.models import EmailOutbox, Notification  # noqa: F401
from app.organizations.models import (  # noqa: F401
    MemberProfile,
    Membership,
    Organization,
    OrganizationInvitation,
)
from app.portal.models import IntakeRevision, OwnerFeedback, PortalMessage  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401
from app.providers.models import (  # noqa: F401
    AgentRun,
    AiProvider,
    ModelPrice,
    ModelRoute,
    RoutingPolicy,
    SecretReference,
    SpendBudget,
    TokenUsage,
    ToolExecution,
)
from app.rules.models import ChangeProposal, ProjectTeam, Rule, RuleVersion, Team  # noqa: F401
from app.sensors.models import RiskAcceptance, SensorEvidence, SensorExecution  # noqa: F401
from app.skills.models import Skill, SkillVersion  # noqa: F401
from app.storage.models import StoredObject  # noqa: F401
from app.studio.models import WorkflowDraft  # noqa: F401
from app.work.models import (  # noqa: F401
    Handoff,
    WorkComment,
    WorkItem,
    WorkItemLink,
    WorkItemVersion,
    WorkPackage,
)
from app.workflows.models import (  # noqa: F401
    OwnerQuestion,
    StageDependency,
    StageEscalation,
    StageExecution,
    StageTransition,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowVersion,
)

metadata = Base.metadata
