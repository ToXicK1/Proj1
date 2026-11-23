import type { Tone } from "../components/ui";

/** Each department's own navigation (the brief's module lists). A module is either built on a record kind, one of the
 * shared screens, or not built yet: then it says which step brings it, and nothing pretends to work. */

export type Module =
  | { key: string; label: string; screen: "overview" | "steps" | "packages" | "handoffs" | "traceability" | "conversations" | "scope" | "changes" }
  | { key: string; label: string; screen: "records"; kinds: string[] }
  | { key: string; label: string; screen: "later"; step: string; what: string };

const later = (key: string, label: string, step: string, what: string): Module => ({ key, label, screen: "later", step, what });

export const MODULES: Record<string, Module[]> = {
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
    later("requirements", "Requirements Analysis", "7.2", "the approved BA package with analysis notes"),
    later("system", "System Design", "7.2", "editable system, context and component diagrams"),
    later("components", "Component Architecture", "7.2", "component records and diagrams"),
    later("database", "Database Design", "7.2", "entities, keys, relationships, ER view and SQL export"),
    later("api", "API & Integrations", "7.2", "endpoints with schemas and OpenAPI import and export"),
    later("tech", "Technology Decisions", "7.2", "comparisons and Architecture Decision Records"),
    later("security", "Security Architecture", "7.2", "trust boundaries, data classification, encryption"),
    later("infra", "Infrastructure Design", "7.2", "proposed infrastructure, labelled as a design"),
    later("adr", "Architecture Decision Records", "7.2", "ADRs"),
    later("risks", "Technical Risks", "7.2", "the technical risk register"),
    { key: "reviews", label: "Reviews & Approvals", screen: "packages" },
    { key: "handoffs", label: "Handoffs", screen: "handoffs" },
    { key: "conversations", label: "Architect Conversations", screen: "conversations" },
  ],
  ui_ux_designer: [
    { key: "overview", label: "Design Overview", screen: "overview" },
    { key: "steps", label: "Lifecycle steps", screen: "steps" },
    later("research", "Research & Discovery", "7.2", "research notes and personas"),
    later("journeys", "User Journeys", "7.2", "journey maps"),
    later("ia", "Information Architecture", "7.2", "site maps and navigation"),
    later("wireframes", "Wireframes", "7.2", "the design canvas"),
    later("visual", "Visual Design", "7.2", "the design canvas with tokens"),
    later("system", "Design System", "7.2", "tokens and reusable components"),
    later("library", "Component Library", "7.2", "component specifications"),
    later("prototypes", "Prototypes", "7.2", "linked screens previewed in the browser"),
    later("feedback", "Design Feedback", "7.2", "feedback pinned to screens"),
    later("versions", "Design Versions", "7.2", "screen versions and comparison"),
    later("figma", "Figma", "7.2", "linking and versioning Figma files, once you connect Figma"),
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
  business_analyst: "ba", solution_architect: "architect", ui_ux_designer: "design",
  software_developer: "dev", qa_security: "qa", devops_release: "devops",
};
export const PATH_DEPARTMENT: Record<string, string> = Object.fromEntries(
  Object.entries(DEPARTMENT_PATH).map(([k, v]) => [v, k]));

export const PROVENANCE_LABEL: Record<string, [string, Tone]> = {
  confirmed: ["Confirmed", "success"],
  assumption: ["Assumption", "warning"],
  ai_suggestion: ["AI suggestion", "info"],
  open_question: ["Open question", "pending"],
};
export const STATUS_LABEL: Record<string, [string, Tone]> = {
  draft: ["Draft", "neutral"], in_review: ["In review", "pending"], approved: ["Approved", "success"],
  changes_requested: ["Changes requested", "warning"], archived: ["Archived", "neutral"],
  submitted: ["Awaiting decision", "pending"], superseded: ["Superseded", "neutral"],
  sent: ["Sent", "pending"], acknowledged: ["Acknowledged", "success"],
  clarification_requested: ["Clarification requested", "warning"],
};
