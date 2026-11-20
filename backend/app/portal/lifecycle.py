"""The ready-made delivery lifecycle: five phases, thirty-three stages, six professional profiles.

The phase and stage structure and the scope selection follow the AI-DLC methodology (awslabs/aidlc-workflows,
MIT-0). The wording, agents and implementation here are our own. Each stage belongs to one profile, and only a
person holding that profile can approve it.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import service as agents
from app.agents.models import AgentConfiguration, Profile
from app.auth.models import User
from app.core.errors import AppError
from app.organizations.service import require_org_admin
from app.providers.models import ModelRoute

SCOPES = ("enterprise", "feature", "mvp", "poc", "bugfix", "refactor", "infra", "security-patch", "classic",
          "workshop", "express")
SCOPE_LABELS = {
    "enterprise": "Enterprise: everything, with the most detail", "feature": "New product or feature: full lifecycle",
    "mvp": "Minimum viable product: no operations phase", "poc": "Proof of concept: fastest route to code",
    "bugfix": "Bug fix", "refactor": "Refactor existing code", "infra": "Infrastructure change",
    "security-patch": "Security patch", "classic": "Requirements to tested code",
    "workshop": "Workshop: full walkthrough", "express": "Express: small change, then ship",
}
DEFAULT_SCOPE = "feature"
PHASES = ("Initialization", "Ideation", "Inception", "Construction", "Operation")


@dataclass(frozen=True)
class Member:
    profile: str
    title: str


TEAM: tuple[Member, ...] = (
    Member("business_analyst", "Business Analyst"), Member("solution_architect", "Solution Architect"),
    Member("ui_ux_designer", "UI/UX Designer"), Member("software_developer", "Software Developer"),
    Member("qa_security", "QA & Security Engineer"), Member("devops_release", "DevOps & Release Engineer"),
)
BY_PROFILE = {m.profile: m for m in TEAM}
BA, SA, UX, DEV, QA, OPS = (m.profile for m in TEAM)


@dataclass(frozen=True)
class Stage:
    id: str
    number: str
    phase: str
    name: str
    profile: str
    brief: str
    keys: tuple[str, ...]
    scopes: str  # one flag per entry in SCOPES
    work: str = "ai:stage_work"
    sandbox: str | None = None  # "self", or the stage whose generated files are tested here

    @property
    def gated(self) -> bool:
        return self.work == "ai:stage_work"

    def in_scope(self, scope: str) -> bool:
        return self.scopes[SCOPES.index(scope)] == "1"


ALL = "1" * 11
CODE_BRIEF = (
    "Write a small, complete, runnable project that implements the approved work. Put every file in source_files, a "
    "JSON list of objects with path and content. Use relative paths such as app/core.py. Use only the Python standard "
    "library with pytest tests named test_*.py, or Node.js built-ins with node:test tests named *.test.js. Nothing can "
    "be installed and there is no network. Include real tests. If earlier feedback reports failures, fix them."
)
_I, _Id, _In, _C, _O = PHASES
STAGES: tuple[Stage, ...] = (
    Stage("workspace_scaffold", "0.1", _I, "Workspace Scaffold", OPS, "", ("project_name",), ALL, "workspace_scaffold"),
    Stage("workspace_detection", "0.2", _I, "Workspace Detection", OPS, "", ("project_kind",), ALL, "workspace_detection"),
    Stage("state_initialization", "0.3", _I, "State Initialization", OPS, "", ("brief_items",), ALL, "state_initialization"),
    Stage("intent_capture", "1.1", _Id, "Intent Capture & Framing", BA, "Frame the problem, the people affected and the outcome wanted.",
          ("problem_statement", "target_users", "desired_outcomes", "open_questions"), "11110000000"),
    Stage("market_research", "1.2", _Id, "Market Research", BA, "Outline the market and comparable products. Mark anything unverified as an assumption.",
          ("market_summary", "competitors", "differentiators", "assumptions"), "11000000000"),
    Stage("feasibility", "1.3", _Id, "Feasibility & Constraints", SA, "Assess technical feasibility and the constraints that shape the work.",
          ("feasibility_summary", "constraints", "risks", "recommendation"), "11100000000"),
    Stage("scope_definition", "1.4", _Id, "Scope Definition", BA, "Define what is in and out of scope and how success is measured.",
          ("in_scope", "out_of_scope", "success_measures", "assumptions"), "11100000000"),
    Stage("team_formation", "1.5", _Id, "Team Formation", BA, "Describe the skills and responsibilities this work needs.",
          ("roles_needed", "responsibilities", "gaps"), "11000000000"),
    Stage("rough_mockups", "1.6", _Id, "Rough Mockups", UX, "Describe rough screens that make the idea concrete.",
          ("screens", "primary_flow", "design_questions"), "11100000000"),
    Stage("approval_handoff", "1.7", _Id, "Approval & Handoff", BA, "Summarize the ideation outcome for handoff into detailed work.",
          ("summary", "decisions", "handoff_items"), "11000000000"),
    Stage("reverse_engineering", "2.1", _In, "Reverse Engineering", DEV, "Describe what must be understood about any existing system. State clearly if there is none.",
          ("existing_system", "components", "findings"), "11111101111"),
    Stage("practices_discovery", "2.2", _In, "Practices Discovery", OPS, "Set out the engineering, testing and delivery practices to follow.",
          ("development_practices", "testing_practices", "delivery_practices"), "11100010110"),
    Stage("requirements_analysis", "2.3", _In, "Requirements Analysis", BA, "Write functional and non-functional requirements, keeping assumptions separate.",
          ("functional_requirements", "non_functional_requirements", "assumptions", "open_questions"), ALL),
    Stage("user_stories", "2.4", _In, "User Stories", BA, "Write user stories with testable acceptance criteria.",
          ("personas", "user_stories", "acceptance_criteria"), "11100000110"),
    Stage("refined_mockups", "2.5", _In, "Refined Mockups", UX, "Refine screens, navigation and states against the approved stories.",
          ("screens", "navigation", "states", "accessibility_notes"), "11100000110"),
    Stage("domain_design", "2.6", _In, "Domain Design", SA, "Define the domain concepts, their relationships and business rules.",
          ("domain_entities", "relationships", "business_rules"), "11100000110"),
    Stage("units_generation", "2.7", _In, "Units Generation", SA, "Split the work into independently deliverable units.",
          ("units", "dependencies", "story_mapping"), "11100000110"),
    Stage("contract_design", "2.8", _In, "Contract Design", SA, "Define the interfaces and data contracts between units.",
          ("interfaces", "data_contracts", "error_handling"), "11100000110"),
    Stage("delivery_planning", "2.9", _In, "Delivery Planning", BA, "Plan the order of delivery, milestones and risks.",
          ("milestones", "sequence", "risks"), "11100000110"),
    Stage("functional_design", "3.1", _C, "Functional Design", SA, "Design the behavior, data and business logic of each unit.",
          ("logic", "data_models", "business_rules"), "11100100110"),
    Stage("nfr_requirements", "3.2", _C, "NFR Requirements", SA, "Set measurable performance, security, reliability and scaling targets.",
          ("performance", "security", "reliability", "technology_choices"), "11100011110"),
    Stage("nfr_design", "3.3", _C, "NFR Design", SA, "Design how those quality targets will be met.",
          ("patterns", "components", "tradeoffs"), "11100010110"),
    Stage("infrastructure_design", "3.4", _C, "Infrastructure Design", OPS, "Map the design onto infrastructure and environments.",
          ("services", "environments", "deployment_architecture"), "11100010110"),
    Stage("code_generation", "3.5", _C, "Code Generation", DEV, CODE_BRIEF,
          ("plan", "source_files", "tests_to_write", "known_limits"), ALL, sandbox="self"),
    Stage("build_and_test", "3.6", _C, "Build and Test", QA, "Write further test cases, security checks and steps the owner can try. The platform "
          "builds and tests the generated code itself, so never state results.",
          ("build_steps", "test_cases", "security_checks", "owner_test_steps"), ALL, sandbox="code_generation"),
    Stage("ci_pipeline", "3.7", _C, "CI Pipeline", OPS, "Define the continuous integration pipeline.",
          ("pipeline_stages", "quality_checks", "artifacts"), "11100010010"),
    Stage("deployment_pipeline", "4.1", _O, "Deployment Pipeline", OPS, "Define the deployment pipeline and its approvals.",
          ("pipeline_stages", "approvals", "rollback_plan"), "11001111011"),
    Stage("environment_provisioning", "4.2", _O, "Environment Provisioning", OPS, "Specify the environments and their security posture. Do not claim that anything exists yet.",
          ("environments", "configuration", "security_posture"), "11000010010"),
    Stage("deployment_execution", "4.3", _O, "Deployment Execution", OPS, "Write the release runbook. Do not claim that anything was deployed.",
          ("release_steps", "verification", "rollback_steps"), "11001111011"),
    Stage("observability_setup", "4.4", _O, "Observability Setup", OPS, "Define metrics, logs, dashboards and alerts.",
          ("metrics", "logs", "alerts"), "11000010011"),
    Stage("incident_response", "4.5", _O, "Incident Response", OPS, "Write incident response procedures and runbooks.",
          ("severity_levels", "procedures", "runbooks"), "11000000010"),
    Stage("performance_validation", "4.6", _O, "Performance Validation", QA, "Plan load tests against the agreed targets. Do not claim results.",
          ("scenarios", "targets", "pass_criteria"), "11000000010"),
    Stage("feedback_optimization", "4.7", _O, "Feedback & Optimization", OPS, "Plan how operating feedback will drive improvements.",
          ("signals", "review_cadence", "improvements"), "11000000010"),
)
BY_STAGE = {s.id: s for s in STAGES}

# The approved earlier work each step needs, most important first. Steps not listed get their nearest earlier work.
# Only stages that are in the chosen scope and come earlier are used.
READS: dict[str, tuple[str, ...]] = {
    "requirements_analysis": ("intent_capture", "scope_definition", "feasibility", "market_research",
                              "reverse_engineering"),
    "user_stories": ("requirements_analysis", "scope_definition", "intent_capture"),
    "refined_mockups": ("user_stories", "rough_mockups", "requirements_analysis"),
    "domain_design": ("requirements_analysis", "user_stories"),
    "units_generation": ("domain_design", "user_stories", "requirements_analysis"),
    "contract_design": ("units_generation", "domain_design", "requirements_analysis"),
    "delivery_planning": ("units_generation", "scope_definition", "requirements_analysis"),
    "functional_design": ("units_generation", "domain_design", "contract_design", "user_stories",
                          "requirements_analysis"),
    "nfr_requirements": ("requirements_analysis", "feasibility", "practices_discovery"),
    "nfr_design": ("nfr_requirements", "functional_design"),
    "infrastructure_design": ("nfr_design", "nfr_requirements", "practices_discovery"),
    "code_generation": ("requirements_analysis", "user_stories", "functional_design", "contract_design",
                        "domain_design", "refined_mockups", "nfr_requirements", "units_generation",
                        "reverse_engineering", "intent_capture"),
    "build_and_test": ("code_generation", "requirements_analysis", "user_stories", "nfr_requirements",
                       "practices_discovery"),
    "ci_pipeline": ("practices_discovery", "build_and_test", "code_generation"),
    "deployment_pipeline": ("ci_pipeline", "infrastructure_design"),
    "environment_provisioning": ("infrastructure_design", "nfr_requirements"),
    "deployment_execution": ("deployment_pipeline", "environment_provisioning", "build_and_test"),
    "observability_setup": ("nfr_requirements", "infrastructure_design"),
    "incident_response": ("observability_setup", "deployment_execution"),
    "performance_validation": ("nfr_requirements", "build_and_test"),
    "feedback_optimization": ("observability_setup", "incident_response", "requirements_analysis"),
    "approval_handoff": ("intent_capture", "scope_definition", "feasibility", "rough_mockups"),
}


# Read-only tools every lead gets: look up the brief and approved earlier work on demand (Phase 6)
LEAD_TOOLS = ("list_approved_work", "read_artifact", "read_project", "search_approved_work")


def template_key(scope: str) -> str:
    return f"aidlc-{scope}"


def lead_key(stage: Stage) -> str:
    return f"{stage.id.replace('_', '-')}-lead"


def reviewer_key(profile: str) -> str:
    return f"{profile.replace('_', '-')}-reviewer"


def workflow_spec(scope: str) -> dict[str, Any]:
    chosen = [s for s in STAGES if s.in_scope(scope)]
    out = []
    for index, stage in enumerate(chosen):
        item: dict[str, Any] = {
            "id": stage.id, "name": stage.name, "depends_on": [chosen[index - 1].id] if index else [],
            "work": stage.work, "output_required_keys": list(stage.keys), "profile": stage.profile,
            "human_gate": stage.gated, "owner_visible": stage.gated,
        }
        earlier = {c.id for c in chosen[:index]}
        reads = [r for r in READS.get(stage.id, ()) if r in earlier]
        if reads:
            item["reads"] = reads
        if stage.gated:
            item |= {"protected": True, "approval_policy": {"type": "single", "role": f"profile:{stage.profile}"},
                     "agent": lead_key(stage), "reviewer": reviewer_key(stage.profile),
                     "sensors": [{"key": "secret_detection", "mandatory": True, "config": {}}]}
            if stage.sandbox:
                item |= {"sandbox": True, "sandbox_source": None if stage.sandbox == "self" else stage.sandbox}
                item["sensors"] += [{"key": "code_builds", "mandatory": True, "config": {}},
                                    {"key": "unit_tests", "mandatory": True, "config": {}}]
        out.append(item)
    return {"key": template_key(scope), "name": f"AI-DLC: {SCOPE_LABELS[scope]}", "execution": "sequential",
            "stages": out}


def provision(db: Session, user: User, organization_id: uuid.UUID, model_route: str) -> dict[str, int]:
    """Creates any missing profile and agent. Existing ones, including edited ones, are kept."""
    require_org_admin(db, user.id, organization_id)
    if not db.execute(select(ModelRoute.id).where(ModelRoute.organization_id == organization_id,
                                                  ModelRoute.key == model_route)).first():
        raise AppError(404, "unknown_model_route", "Model route does not exist")
    profiles = set(db.execute(select(Profile.key).where(Profile.organization_id == organization_id)).scalars())
    existing = set(db.execute(select(AgentConfiguration.key).where(
        AgentConfiguration.organization_id == organization_id)).scalars())
    for member in TEAM:
        if member.profile not in profiles:
            agents.create_profile(db, user, organization_id=organization_id, key=member.profile, name=member.title)
        key = reviewer_key(member.profile)
        if key not in existing:
            agents.create_agent(
                db, user, organization_id=organization_id, profile_key=member.profile, key=key, kind="reviewer",
                instructions=f"You independently review work produced for a {member.title}. Look for gaps, "
                             "contradictions and claims the material does not support.",
                required_keys=["verdict", "findings"], model_route=model_route,
                context_sources=["stage_artifact"], tools=[])
    for stage in STAGES:
        if not stage.gated:
            continue
        instructions = (f"You support a {BY_PROFILE[stage.profile].title} on the {stage.name} step of a software "
                        f"project. {stage.brief} Build on the approved earlier work when it is provided.")
        if lead_key(stage) not in existing:
            agents.create_agent(
                db, user, organization_id=organization_id, profile_key=stage.profile, key=lead_key(stage), kind="lead",
                instructions=instructions, required_keys=list(stage.keys), model_route=model_route,
                context_sources=["project_input", "feedback", "upstream_deliverables"], tools=list(LEAD_TOOLS))
            continue
        current = agents.latest(db, organization_id, lead_key(stage)).version
        stale_code = stage.sandbox == "self" and "source_files" not in current.instructions
        if stale_code or not current.tools:  # bring older teams up to date; edited instructions are kept otherwise
            agents.add_version(
                db, user, organization_id=organization_id, key=lead_key(stage),
                instructions=instructions if stale_code else current.instructions,
                required_keys=list(current.required_keys), model_route=current.model_route,
                context_sources=list(current.context_sources),
                tools=sorted(set(current.tools) | set(LEAD_TOOLS)))
    return {"profiles": len(TEAM), "stages": len(STAGES)}
