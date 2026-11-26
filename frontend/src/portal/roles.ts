/** The seven professional profiles (RD-20: the Project Manager first) and which project sections each kind of
 * person sees. */
export const PROFILES = [
  ["project_manager", "Project Manager"],
  ["business_analyst", "Business Analyst"],
  ["solution_architect", "Solution Architect"],
  ["ui_ux_designer", "UI/UX Designer"],
  ["software_developer", "Software Developer"],
  ["qa_security", "QA & Security"],
  ["devops_release", "DevOps & Release"],
] as const;

/** The six engineering departments: what an administrator ticks for a department professional. */
export const ENGINEERING = PROFILES.filter(([key]) => key !== "project_manager");

export const TABS = ["Overview", "Workspace", "Lifecycle", "Progress", "Project brief", "Deliverables", "Tickets",
  "Conversations", "Testing"] as const;
export type PortalTab = (typeof TABS)[number];

/** The backend enforces the same limits; this only decides what to show. */
export const TABS_FOR: Record<string, readonly PortalTab[]> = {
  owner: ["Overview", "Lifecycle", "Progress", "Project brief", "Deliverables", "Tickets", "Conversations", "Testing"],
  professional: ["Workspace", "Tickets", "Conversations"],
  admin: TABS.filter((t) => t !== "Workspace"),  // administrators oversee: no department's workspace is theirs
  manager: TABS,
  member: ["Overview"],
};
