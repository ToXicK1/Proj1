import { DEPARTMENT_PATH } from "./modules";

// Each role's Workspace has two layers:
// - its overview: the role's working page, with what waits on the person, the AI's steps, the assistant, the work
//   to review and the role's records (the department workspace);
// - its tools: the professional tools the role works in (the Developer: the IDE and the Codebase Explorer). Roles
//   get their tools one at a time; until then the overview is all there is.
// Used by the sidebar, the Workspace page and the team summary, so a role always opens the same places.

export interface RoleTool { name: string; what: string; to: (projectId: string) => string }
export interface RoleSpace { overview: RoleTool; tools: RoleTool[] }

const page = (key: string) => (p: string) => `/projects/${encodeURIComponent(p)}/work/${DEPARTMENT_PATH[key]}`;
const overview = (key: string, name: string, what: string): RoleTool => ({ name, what, to: page(key) });

export const ROLE_SPACES: Record<string, RoleSpace> = {
  software_developer: {
    overview: overview("software_developer", "Development overview",
      "What waits on you, the AI's steps, the assistant, work to review and the department's records"),
    tools: [
      { name: "IDE", what: "Code, source control, change sets, build and test, terminal, Developer AI",
        to: (p) => `/projects/${encodeURIComponent(p)}/ide` },
      { name: "Codebase Explorer", what: "The repository's structure and dependencies",
        to: (p) => `/projects/${encodeURIComponent(p)}/codebase` },
    ],
  },
  business_analyst: { overview: overview("business_analyst", "Requirements overview",
    "The AI's drafts, requirements, user stories, BRD and SRS, the assistant and work to review"), tools: [] },
  solution_architect: { overview: overview("solution_architect", "Architecture overview",
    "The AI's drafts, architecture records, decisions, APIs and data models"), tools: [] },
  ui_ux_designer: { overview: overview("ui_ux_designer", "Design overview",
    "The AI's drafts, screens, flows and design records"), tools: [] },
  qa_security: { overview: overview("qa_security", "QA overview",
    "The AI's drafts, test cases, defects and security checks"), tools: [] },
  devops_release: { overview: overview("devops_release", "DevOps overview",
    "The AI's drafts, pipelines, environments and releases"), tools: [] },
  project_manager: { overview: overview("project_manager", "Project overview",
    "Meetings, the brief, kickoff, plans and every department's work"), tools: [] },
};

/** Where a role's link goes for a project: its overview. */
export function workspaceFor(profile: string, projectId: string): string {
  return (ROLE_SPACES[profile]?.overview.to ?? page(profile))(projectId);
}
