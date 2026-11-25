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
          "workshop", "express", "ba-department", "departments")
# Department lifecycles (RD-1, Phase 7). Previews until all six are built (RD-14): never the default.
# Each scope lists departments in order; a department after the first starts from the first department's approved
# package, so the Solution Architect and UI/UX Designer run in parallel (RD-13).
DEPARTMENT_SCOPES: dict[str, tuple[str, ...]] = {
    "ba-department": ("business_analyst",),
    "departments": ("business_analyst", "solution_architect", "ui_ux_designer"),
}
SCOPE_LABELS = {
    "enterprise": "Enterprise: everything, with the most detail", "feature": "New product or feature: full lifecycle",
    "mvp": "Minimum viable product: no operations phase", "poc": "Proof of concept: fastest route to code",
    "bugfix": "Bug fix", "refactor": "Refactor existing code", "infra": "Infrastructure change",
    "security-patch": "Security patch", "classic": "Requirements to tested code",
    "workshop": "Workshop: full walkthrough", "express": "Express: small change, then ship",
    "ba-department": "Preview: the Business Analyst department lifecycle only (the other departments follow)",
    "departments": "Preview: the department lifecycle so far (Business Analyst, then Solution Architect and UI/UX "
                   "Designer in parallel)",
}
DEFAULT_SCOPE = "feature"
PHASES = ("Initialization", "Ideation", "Inception", "Construction", "Operation", "Business Analysis")


@dataclass(frozen=True)
class Member:
    profile: str
    title: str


TEAM: tuple[Member, ...] = (
    # RD-20: the Project Manager coordinates the six engineering departments; it never overrides their decisions.
    Member("project_manager", "Project Manager"),
    Member("business_analyst", "Business Analyst"), Member("solution_architect", "Solution Architect"),
    Member("ui_ux_designer", "UI/UX Designer"), Member("software_developer", "Software Developer"),
    Member("qa_security", "QA & Security Engineer"), Member("devops_release", "DevOps & Release Engineer"),
)
BY_PROFILE = {m.profile: m for m in TEAM}
PM, BA, SA, UX, DEV, QA, OPS = (m.profile for m in TEAM)
ENGINEERING = (BA, SA, UX, DEV, QA, OPS)  # the six engineering departments


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
    # Output key -> work record kind: the step proposes records and is approved through a package (7.1a).
    records: tuple[tuple[str, str], ...] = ()
    records_min: tuple[tuple[str, int], ...] = ()  # record lists that may not come back empty
    owner_visible: bool | None = None  # default: the owner sees AI steps
    owner_input: bool = False  # the owner gives input before the professional's final approval (RD-2)
    assemble: tuple[str, ...] = ()  # documents the platform drafts from approved records at this review step

    @property
    def gated(self) -> bool:
        """An AI step with a professional's gate."""
        return self.work == "ai:stage_work"

    @property
    def human_gate(self) -> bool:
        """Waits for a professional's decision: every AI step, and the department's review steps."""
        return self.gated or self.work in ("department_review", "owner_review")

    def in_scope(self, scope: str) -> bool:
        index = SCOPES.index(scope)
        return index < len(self.scopes) and self.scopes[index] == "1"


ALL = "1" * 11
CODE_BRIEF = (
    "Write a small, complete, runnable project that implements the approved work. Put every file in source_files, a "
    "JSON list of objects with path and content. Use relative paths such as app/core.py. Use only the Python standard "
    "library with pytest tests named test_*.py, or Node.js built-ins with node:test tests named *.test.js. Nothing can "
    "be installed and there is no network. Include real tests. If earlier feedback reports failures, fix them."
)
_I, _Id, _In, _C, _O = PHASES[:5]
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

_BA = "Business Analysis"
NONE = "0" * 11  # in no AWS-style scope; used only by the department lifecycle
BA_STAGES: tuple[Stage, ...] = (
    Stage("ba_intake_review", "B.1", _BA, "Intake Review", BA,
          "Review the confirmed brief. Summarize it, list what is still unclear as questions for the owner, and list "
          "the assumptions you would otherwise have to make. Never invent requirements.",
          ("summary", "open_questions", "assumptions"), NONE,
          records=(("open_questions", "discovery_question"), ("assumptions", "assumption"))),
    Stage("ba_discovery", "B.2", _BA, "Discovery", BA,
          "Identify the stakeholders, the current way of working and the constraints. Mark anything not stated in "
          "the brief as unconfirmed.",
          ("stakeholders", "current_process", "constraints"), NONE, records=(("stakeholders", "stakeholder"),),
          records_min=(("stakeholders", 1),)),
    Stage("ba_requirements", "B.3", _BA, "Requirements Analysis", BA,
          "Write the functional and non-functional requirements, each testable and traced to the brief or an "
          "approved earlier record. Keep assumptions separate.",
          ("requirements", "assumptions"), NONE,
          records=(("requirements", "requirement"), ("assumptions", "assumption")), records_min=(("requirements", 1),)),
    Stage("ba_user_stories", "B.4", _BA, "User Story Development", BA,
          "Write user stories for the approved requirements, each with testable acceptance criteria.",
          ("user_stories",), NONE, records=(("user_stories", "user_story"),), records_min=(("user_stories", 1),)),
    Stage("ba_scope", "B.5", _BA, "Scope Definition", BA,
          "Define what is in and out of scope, the first release, how success is measured, and the main risks.",
          ("in_scope", "out_of_scope", "first_release", "success_measures", "risks"), NONE,
          records=(("risks", "risk"),)),
    Stage("ba_requirements_review", "B.6", _BA, "Requirements Review", BA,
          "Independently review the department's approved work as a whole: gaps, contradictions, untestable "
          "requirements, stories without requirements, and scope that does not match. Report findings with severity. "
          "You advise; you never approve.",
          ("verdict", "findings"), NONE, records=(("findings", "review_finding"),), owner_visible=False),
    Stage("ba_professional_review", "B.7", _BA, "Human Professional Review", BA, "", ("package",), NONE,
          work="department_review", owner_visible=False, assemble=("brd", "srs")),
    Stage("ba_user_review", "B.8", _BA, "User Review and Approval", BA, "", ("package",), NONE,
          work="owner_review", owner_visible=True, owner_input=True),
)
_SA, _UX = "Solution Architecture", "UI/UX Design"
SA_STAGES: tuple[Stage, ...] = (
    Stage("sa_requirements_analysis", "S.1", _SA, "Requirements Analysis", SA,
          "Read the approved Business Analyst package. List the architecture drivers: the quality attributes, "
          "constraints and key functions that shape the design, each traced to a requirement.",
          ("summary", "drivers"), NONE, records=(("drivers", "architecture_driver"),), records_min=(("drivers", 1),)),
    Stage("sa_decomposition", "S.2", _SA, "System Decomposition", SA,
          "Split the system into components with clear responsibilities and interfaces.",
          ("components", "notes"), NONE, records=(("components", "component"),), records_min=(("components", 1),)),
    Stage("sa_technology", "S.3", _SA, "Technology Selection", SA,
          "Choose the technologies, each as an architecture decision with its context, the alternatives considered "
          "and the consequences.", ("decisions",), NONE, records=(("decisions", "adr"),),
          records_min=(("decisions", 1),)),
    Stage("sa_data", "S.4", _SA, "Data Architecture", SA,
          "Design the data model: entities with their attributes, keys and relationships, and why.",
          ("entities",), NONE, records=(("entities", "data_entity"),), records_min=(("entities", 1),)),
    Stage("sa_api", "S.5", _SA, "API and Integration", SA,
          "Define the API endpoints and external integrations, with request and response shapes, authentication "
          "and errors.", ("endpoints",), NONE, records=(("endpoints", "api_endpoint"),),
          records_min=(("endpoints", 1),)),
    Stage("sa_security_infra", "S.6", _SA, "Security and Infrastructure", SA,
          "Set out the security controls (authentication, authorization, trust boundaries, data protection) and the "
          "proposed infrastructure, and the technical risks. Nothing is provisioned: this is a design.",
          ("controls", "resources", "risks"), NONE,
          records=(("controls", "security_control"), ("resources", "infra_resource"), ("risks", "tech_risk")),
          records_min=(("controls", 1),)),
    Stage("sa_documentation", "S.7", _SA, "Architecture Documentation", SA,
          "Write the architecture document from the approved work: overview, components, data, interfaces, "
          "security, infrastructure and decisions.", ("documents",), NONE,
          records=(("documents", "architecture_document"),), records_min=(("documents", 1),)),
    Stage("sa_review", "S.8", _SA, "Independent Review", SA,
          "Independently review the architecture as a whole against the requirements: coverage, scalability, "
          "security, maintainability and operational feasibility. Report findings with severity. You advise; you "
          "never approve.", ("verdict", "findings"), NONE, records=(("findings", "architecture_finding"),),
          owner_visible=False),
    Stage("sa_professional_review", "S.9", _SA, "Human Review", SA, "", ("package",), NONE,
          work="department_review", owner_visible=False),
    Stage("sa_user_review", "S.10", _SA, "User Review", SA, "", ("package",), NONE,
          work="owner_review", owner_visible=True, owner_input=True),
)
UX_STAGES: tuple[Stage, ...] = (
    Stage("ux_discovery", "U.1", _UX, "Design Discovery", UX,
          "From the approved Business Analyst package, describe the personas and what is known about how they "
          "work. Mark anything not stated as unconfirmed.", ("personas", "research"), NONE,
          records=(("personas", "persona"), ("research", "research_note")), records_min=(("personas", 1),)),
    Stage("ux_ia", "U.2", _UX, "Information Architecture", UX,
          "Lay out the site map: the screens and sections, what each is for and how they nest.",
          ("site_map",), NONE, records=(("site_map", "ia_node"),), records_min=(("site_map", 1),)),
    Stage("ux_journeys", "U.3", _UX, "User Journey Mapping", UX,
          "Map the main journeys step by step for each persona, with their pain points.",
          ("journeys",), NONE, records=(("journeys", "user_journey"),), records_min=(("journeys", 1),)),
    Stage("ux_wireframes", "U.4", _UX, "Wireframes", UX,
          "Describe each screen as a wireframe: its purpose, its sections from top to bottom, and its loading, empty "
          "and error states.", ("screens",), NONE, records=(("screens", "screen"),), records_min=(("screens", 1),)),
    Stage("ux_visual", "U.5", _UX, "Visual Design", UX,
          "Propose the design tokens and the reusable components. Keep the platform's colours: forest green as the "
          "identity, beige surfaces, electric purple only for AI features; keep contrast accessible.",
          ("tokens", "components"), NONE, records=(("tokens", "design_token"), ("components", "ui_component")),
          records_min=(("components", 1),)),
    Stage("ux_prototype", "U.6", _UX, "Prototype and UI Specs", UX,
          "Define how the screens connect: for each interaction, the screen it starts on, what triggers it and "
          "where it leads.", ("flows",), NONE, records=(("flows", "prototype_flow"),), records_min=(("flows", 1),)),
    Stage("ux_review", "U.7", _UX, "Independent Review", UX,
          "Independently review the design as a whole: unnecessary steps, missing states, accessibility, "
          "consistency with the requirements. Report findings with severity. You advise; you never approve.",
          ("verdict", "findings"), NONE, records=(("findings", "design_finding"),), owner_visible=False),
    Stage("ux_professional_review", "U.8", _UX, "Human Review", UX, "", ("package",), NONE,
          work="department_review", owner_visible=False),
    Stage("ux_user_review", "U.9", _UX, "User Design Review and Approval", UX, "", ("package",), NONE,
          work="owner_review", owner_visible=True, owner_input=True),
)
# D1 (RD-2 amended): the steps the client signs off after the professional, on the same version. UAT and milestones
# join when those phases exist.
CLIENT_SIGN_OFF: dict[str, str] = {"ba_user_review": "BRD baseline", "ux_user_review": "Design sign-off"}
DEPARTMENT_STAGES: dict[str, tuple[Stage, ...]] = {"business_analyst": BA_STAGES, "solution_architect": SA_STAGES,
                                                   "ui_ux_designer": UX_STAGES}


def departments_for(scope: str) -> tuple[str, ...]:
    """The engineering departments a kind of work needs: each must have a professional before delivery starts."""
    if scope in DEPARTMENT_SCOPES:
        return DEPARTMENT_SCOPES[scope]
    special = {x.id for group in DEPARTMENT_STAGES.values() for x in group}
    found = {s.profile for s in STAGES if s.gated and s.id not in special and s.in_scope(scope)}
    return tuple(p for p in ENGINEERING if p in found)


# What a later department reads from the first one's approved work, most important first.
CROSS_READS = ("ba_requirements", "ba_user_stories", "ba_scope", "ba_discovery", "ba_intake_review")
STAGES = STAGES + BA_STAGES + SA_STAGES + UX_STAGES
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


PM_ASSISTANT = "project-manager-assistant"
PM_PERSONA = (
    "You assist the human Project Manager of a software project. You analyse meeting notes and project information, "
    "structure what the client said, point out what is missing or contradictory, and suggest follow-up questions. "
    "You only use the material you are given. You never invent facts, progress, dates or approvals, and you never "
    "make business decisions: everything you produce is a provisional suggestion the Project Manager reviews. "
    "Keep what the client stated apart from your own assumptions.")


CLIENT_ASSISTANT = "client-assistant"
# RD-23: one assistant for the client, in place of the per-department representatives. It works only from what the
# client may see; questions and changes go to the client's Project Manager.
CLIENT_PERSONA = (
    "You are the client's project assistant on a software project. You explain, in plain and friendly language, "
    "where the project stands and what the approved deliverables say, using only the material you are given. You "
    "never promise dates, scope, prices or approvals, never decide anything, and never describe how the delivery "
    "team or its tools work inside. When the client asks for a change or something you cannot answer from the "
    "material, say that their Project Manager will follow up.")


def lead_key(stage: Stage) -> str:
    return f"{stage.id.replace('_', '-')}-lead"


def reviewer_key(profile: str) -> str:
    return f"{profile.replace('_', '-')}-reviewer"


def _record_format(stage: Stage) -> str:
    """How the AI must shape the lists that become records."""
    from app.work.kinds import KINDS

    parts = []
    for key, kind_key in stage.records:
        kind = KINDS[kind_key]
        fields = ", ".join(f"{f.name}{' (required)' if f.required else ''}"
                           + (f" one of {'/'.join(f.choices)}" if f.choices else "")
                           + (" as a list of texts" if f.type == "list" else "")
                           + (" as JSON" if f.type == "json" else "") for f in kind.fields)
        need = dict(stage.records_min).get(key)
        import json

        from app.work.kinds import example

        parts.append(f"{key} must be a JSON list of objects, each with a short title and: {fields}."
                     + (f" Give at least {need}, written from the project input." if need
                        else " An empty list is allowed only if nothing applies.")
                     + f" One entry looks like {json.dumps(example(kind))}; write real content, not the placeholders.")
    return " ".join(parts)


def department_spec(scope: str) -> dict[str, Any]:
    """The department lifecycle (Phase 7): each department's steps in order, each reading that department's earlier
    work. Departments after the first start from the first one's approved package and run in parallel (RD-13)."""
    departments = DEPARTMENT_SCOPES[scope]
    out: list[dict[str, Any]] = []
    first = DEPARTMENT_STAGES[departments[0]]
    for department in departments:
        out += _department_steps(DEPARTMENT_STAGES[department],
                                 after=None if department == departments[0] else first[-1].id,
                                 cross=() if department == departments[0] else CROSS_READS)
    titles = ", ".join(BY_PROFILE[d].title for d in departments)
    return {"key": template_key(scope), "name": f"AI-DLC departments (preview): {titles}",
            "execution": "parallel" if len(departments) > 1 else "sequential", "stages": out}


def _department_steps(chosen: tuple[Stage, ...], *, after: str | None, cross: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for index, stage in enumerate(chosen):
        item: dict[str, Any] = {
            "id": stage.id, "name": stage.name,
            "depends_on": [chosen[index - 1].id] if index else ([after] if after else []),
            "work": stage.work, "output_required_keys": list(stage.keys), "profile": stage.profile,
            "human_gate": stage.human_gate, "protected": True, "mandatory": not stage.gated,
            "owner_visible": stage.gated if stage.owner_visible is None else stage.owner_visible,
            "approval_policy": {"type": "single", "role": f"profile:{stage.profile}"},
            "client_approval": stage.id in CLIENT_SIGN_OFF,
            "sensors": [{"key": "secret_detection", "mandatory": True, "config": {}}],
        }
        earlier = [c.id for c in chosen[:index]]
        if earlier or cross:
            item["reads"] = (list(reversed(earlier)) + list(cross))[:20]
        if stage.records:
            item["records"] = dict(stage.records)
        if stage.records_min:
            item["records_min"] = dict(stage.records_min)
        if stage.owner_input:
            item["owner_input"] = True
        if stage.assemble:
            item["assemble"] = list(stage.assemble)
        if stage.gated:
            item |= {"agent": lead_key(stage), "reviewer": reviewer_key(stage.profile)}
            if "review" in stage.id:
                item.pop("reviewer")  # it is the review; nobody reviews the reviewer's advice but the professional
        out.append(item)
    return out


def workflow_spec(scope: str) -> dict[str, Any]:
    if scope in DEPARTMENT_SCOPES:
        return department_spec(scope)
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
    if PM_ASSISTANT not in existing:
        agents.create_agent(
            db, user, organization_id=organization_id, profile_key=PM, key=PM_ASSISTANT, kind="lead",
            instructions=PM_PERSONA, required_keys=["answer"], model_route=model_route,
            context_sources=["project_input"], tools=[])
    if CLIENT_ASSISTANT not in existing:
        agents.create_agent(
            db, user, organization_id=organization_id, profile_key=PM, key=CLIENT_ASSISTANT, kind="lead",
            instructions=CLIENT_PERSONA, required_keys=["reply"], model_route=model_route,
            context_sources=["project_input"], tools=[])
    for stage in STAGES:
        if not stage.gated:
            continue
        instructions = (f"You support a {BY_PROFILE[stage.profile].title} on the {stage.name} step of a software "
                        f"project. {stage.brief} Build on the approved earlier work when it is provided.")
        if stage.records:
            instructions += " " + _record_format(stage)
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
