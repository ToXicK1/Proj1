import type { Tone } from "../components/ui";

/** Each department's own navigation (the brief's module lists). A module is either built on a record kind, one of the
 * shared screens, or not built yet: then it says which step brings it, and nothing pretends to work. */

export type Module =
  | { key: string; label: string; screen: "overview" | "steps" | "packages" | "handoffs" | "traceability" | "conversations" | "scope" | "changes" | "intake" | "analysis" }
  | { key: string; label: string; screen: "records"; kinds: string[] }
  | { key: string; label: string; screen: "later"; step: string; what: string };

const later = (key: string, label: string, step: string, what: string): Module => ({ key, label, screen: "later", step, what });

export const MODULES: Record<string, Module[]> = {
  // RD-20: the Project Manager's own workspace. The modules arrive in the roadmap's phases (PM_CLIENT_ARCHITECTURE.md).
  project_manager: [
    { key: "overview", label: "PM Overview", screen: "overview" },
    { key: "meetings", label: "Client Meetings", screen: "records", kinds: ["meeting"] },
    { key: "analysis", label: "AI Meeting Analysis", screen: "analysis" },
    { key: "intake", label: "Project Intake", screen: "intake" },
    later("brief", "Project Brief", "P4", "the versioned Project Brief you approve before the BA starts"),
    later("ba_handoff", "BA Handoff", "P4", "handing the approved intake package to the Business Analyst"),
    later("sprints", "Sprint Management", "P6", "sprint plans you approve before the engine starts them"),
    later("tasks", "Task Allocation", "P6", "department tasks with owners, priorities and due dates"),
    later("timeline", "Timeline and Dependencies", "P6", "milestones and what blocks what"),
    later("risks", "Risks and Issues", "P6", "the project's risks and issues with explicit owners"),
    later("changes", "Change Requests", "P7", "change requests with impact from each department"),
    later("reports", "Deliverable Reviews and Reports", "P8", "status reports you review before the client sees them"),
    { key: "steps", label: "Lifecycle steps", screen: "steps" },
    { key: "handoffs", label: "Handoffs", screen: "handoffs" },
    { key: "conversations", label: "PM Conversations", screen: "conversations" },
  ],
  business_analyst: [
    { key: "overview", label: "BA Overview", screen: "overview" },
    { key: "steps", label: "Lifecycle steps", screen: "steps" },
    { key: "discovery", label: "Discovery", screen: "records", kinds: ["discovery_question"] },
    { key: "requirements", label: "Requirements", screen: "records", kinds: ["requirement"] },
    { key: "documents", label: "BRD / SRS Documents", screen: "records", kinds: ["document"] },
    { key: "stories", label: "User Stories", screen: "records", kinds: ["user_story"] },
    { key: "flows", label: "Process Flows", screen: "records", kinds: ["process_flow"] },
    { key: "stakeholders", label: "Stakeholders", screen: "records", kinds: ["stakeholder"] },
    { key: "scope", label: "Scope & Priorities", screen: "scope" },
    { key: "traceability", label: "Traceability Matrix", screen: "traceability" },
    { key: "risks", label: "Risks & Assumptions", screen: "records", kinds: ["risk", "assumption"] },
    { key: "changes", label: "Change Requests", screen: "changes" },
    { key: "reviews", label: "Reviews & Approvals", screen: "packages" },
    { key: "handoffs", label: "Handoffs", screen: "handoffs" },
    { key: "conversations", label: "BA Conversations", screen: "conversations" },
  ],
  solution_architect: [
    { key: "overview", label: "Architecture Overview", screen: "overview" },
    { key: "steps", label: "Lifecycle steps", screen: "steps" },
    { key: "requirements", label: "Requirements Analysis", screen: "records", kinds: ["architecture_driver"] },
    { key: "system", label: "System Design", screen: "records", kinds: ["architecture_diagram", "architecture_document"] },
    { key: "components", label: "Component Architecture", screen: "records", kinds: ["component"] },
    { key: "database", label: "Database Design", screen: "records", kinds: ["data_entity"] },
    { key: "api", label: "API & Integrations", screen: "records", kinds: ["api_endpoint"] },
    { key: "tech", label: "Technology Decisions", screen: "records", kinds: ["adr"] },
    { key: "security", label: "Security Architecture", screen: "records", kinds: ["security_control"] },
    { key: "infra", label: "Infrastructure Design", screen: "records", kinds: ["infra_resource"] },
    { key: "adr", label: "Architecture Decision Records", screen: "records", kinds: ["adr"] },
    { key: "risks", label: "Technical Risks", screen: "records", kinds: ["tech_risk", "architecture_finding"] },
    { key: "reviews", label: "Reviews & Approvals", screen: "packages" },
    { key: "handoffs", label: "Handoffs", screen: "handoffs" },
    { key: "conversations", label: "Architect Conversations", screen: "conversations" },
  ],
  ui_ux_designer: [
    { key: "overview", label: "Design Overview", screen: "overview" },
    { key: "steps", label: "Lifecycle steps", screen: "steps" },
    { key: "research", label: "Research & Discovery", screen: "records", kinds: ["persona", "research_note"] },
    { key: "journeys", label: "User Journeys", screen: "records", kinds: ["user_journey"] },
    { key: "ia", label: "Information Architecture", screen: "records", kinds: ["ia_node"] },
    { key: "wireframes", label: "Wireframes", screen: "records", kinds: ["screen"] },
    later("visual", "Visual Design", "7.2c", "the design canvas: frames, layers, properties and tokens, rendered as real HTML"),
    { key: "system", label: "Design System", screen: "records", kinds: ["design_token"] },
    { key: "library", label: "Component Library", screen: "records", kinds: ["ui_component"] },
    { key: "prototypes", label: "Prototypes", screen: "records", kinds: ["prototype_flow"] },
    { key: "feedback", label: "Design Feedback", screen: "records", kinds: ["design_finding"] },
    later("versions", "Design Versions", "7.2c", "screen versions side by side on the canvas"),
    later("figma", "Figma", "7.2d", "linking and versioning Figma files, once you connect Figma"),
    { key: "reviews", label: "Reviews & Approvals", screen: "packages" },
    { key: "handoffs", label: "Developer Handoff", screen: "handoffs" },
    { key: "conversations", label: "Designer Conversations", screen: "conversations" },
  ],
  software_developer: [
    { key: "overview", label: "Development Overview", screen: "overview" },
    { key: "steps", label: "Lifecycle steps", screen: "steps" },
    later("tasks", "Requirements & Tasks", "7.3", "development tasks from approved stories"),
    later("plan", "Implementation Plan", "7.3", "modules, dependencies and sequencing"),
    later("repo", "Repository Explorer", "7.3", "the platform repository, and GitHub once connected"),
    later("modules", "Modules & Components", "7.3", "module records linked to the architecture"),
    later("api", "API Development", "7.3", "implemented endpoints against the API contract"),
    later("db", "Database & Migrations", "7.3", "migrations against the approved data model"),
    later("builds", "Build & Execution", "7.3", "real sandbox builds and logs"),
    later("tests", "Unit & Integration Tests", "7.3", "real sandbox test results"),
    later("review", "Code Review", "7.3", "diffs, findings and the human decision"),
    later("defects", "Defects & Rework", "7.4", "defects received from QA"),
    later("docs", "Documentation", "7.3", "developer documentation"),
    { key: "reviews", label: "Reviews & Approvals", screen: "packages" },
    { key: "handoffs", label: "Handoffs", screen: "handoffs" },
    { key: "conversations", label: "Developer Conversations", screen: "conversations" },
  ],
  qa_security: [
    { key: "overview", label: "QA Overview", screen: "overview" },
    { key: "steps", label: "Lifecycle steps", screen: "steps" },
    later("strategy", "Test Strategy", "7.4", "the test strategy document"),
    later("cases", "Test Cases", "7.4", "test cases linked to requirements"),
    later("suites", "Test Suites", "7.4", "suites and campaigns"),
    later("execution", "Test Execution", "7.4", "manual and automated runs with evidence"),
    later("functional", "Functional Testing", "7.4", "functional runs"),
    later("api", "API & Integration Testing", "7.4", "API runs"),
    later("regression", "Regression Testing", "7.4", "regression runs"),
    later("performance", "Performance Testing", "7.4", "short load runs against the preview environment"),
    later("security", "Security Assessment", "7.4", "assessment sections and findings"),
    later("vulns", "Vulnerability Management", "7.4", "dependency and static analysis findings"),
    later("defects", "Defect Management", "7.4", "the defect board"),
    later("uat", "UAT", "7.4", "the owner's acceptance testing"),
    later("reports", "Quality Reports", "7.4", "reports from recorded runs"),
    { key: "reviews", label: "Sign-off", screen: "packages" },
    { key: "handoffs", label: "Handoffs", screen: "handoffs" },
    { key: "conversations", label: "QA Conversations", screen: "conversations" },
  ],
  devops_release: [
    { key: "overview", label: "DevOps Overview", screen: "overview" },
    { key: "steps", label: "Lifecycle steps", screen: "steps" },
    later("infra", "Infrastructure", "7.5", "the infrastructure overview"),
    later("envs", "Environments", "7.5", "development, test and the local staging environment"),
    later("pipelines", "CI/CD Pipelines", "7.5", "recorded pipeline runs with logs"),
    later("artifacts", "Build Artifacts", "7.5", "release artifacts"),
    later("config", "Configuration & Secrets", "7.5", "configuration (secret values are never shown)"),
    later("deploy", "Deployment Management", "7.5", "deployments to the local staging environment"),
    later("release", "Release Planning", "7.5", "release plans"),
    later("readiness", "Release Readiness", "7.5", "the readiness checklist from real records"),
    later("monitoring", "Monitoring & Logs", "7.5", "health checks of the staging environment"),
    later("incidents", "Incidents", "7.5", "incident records"),
    later("rollback", "Rollback & Recovery", "7.5", "rollback plans"),
    later("handover", "Operational Handover", "7.5", "the handover package"),
    { key: "reviews", label: "Release Approval", screen: "packages" },
    { key: "handoffs", label: "Handoffs", screen: "handoffs" },
    { key: "conversations", label: "DevOps Conversations", screen: "conversations" },
  ],
};

export const DEPARTMENT_PATH: Record<string, string> = {
  project_manager: "pm", business_analyst: "ba", solution_architect: "architect", ui_ux_designer: "design",
  software_developer: "dev", qa_security: "qa", devops_release: "devops",
};
export const PATH_DEPARTMENT: Record<string, string> = Object.fromEntries(
  Object.entries(DEPARTMENT_PATH).map(([k, v]) => [v, k]));

export const PROVENANCE_LABEL: Record<string, [string, Tone]> = {
  confirmed: ["Confirmed", "success"],
  assumption: ["Assumption", "warning"],
  ai_suggestion: ["AI suggestion", "info"],
  open_question: ["Open question", "pending"],
  system_draft: ["Platform draft", "info"],
};
export const STATUS_LABEL: Record<string, [string, Tone]> = {
  draft: ["Draft", "neutral"], in_review: ["In review", "pending"], approved: ["Approved", "success"],
  changes_requested: ["Changes requested", "warning"], archived: ["Archived", "neutral"],
  submitted: ["Awaiting decision", "pending"], superseded: ["Superseded", "neutral"],
  sent: ["Sent", "pending"], acknowledged: ["Acknowledged", "success"],
  clarification_requested: ["Clarification requested", "warning"],
};
