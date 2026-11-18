// Typed client for the backend API. The CSRF token lives in memory only; the session cookie is
// HttpOnly and never readable from script.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problems: string[];

  constructor(status: number, code: string, message: string, problems: string[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.problems = problems;
  }
}

export interface UserDto {
  id: string;
  email: string;
  display_name: string;
}

export interface SessionDto {
  user: UserDto;
  csrf_token: string;
}

export interface OrgDto {
  id: string;
  name: string;
  slug: string;
  role: "org_admin" | "member";
}

export interface ProjectDto {
  id: string;
  organization_id: string;
  name: string;
  description: string;
  project_type: string;
  status: string;
}

export interface InvitationPreviewDto {
  organization: string;
  role: string;
  project: string | null;
  project_role: string | null;
  email_hint: string;
}

export interface OrgMemberDto {
  user_id: string;
  display_name: string;
  email: string;
  role: "org_admin" | "member";
  is_you: boolean;
}

export interface OrgMembersDto {
  members: OrgMemberDto[];
  invitations: { id: string; email: string; role: string; project_role: string | null; project_id: string | null }[];
}

export interface ProjectMemberDto {
  user_id: string;
  display_name: string;
  role: string;
}

export interface SensorSpec {
  key: string;
  mandatory?: boolean;
  severity?: string | null;
  allow_risk_acceptance?: boolean;
  config?: Record<string, unknown>;
}

export interface StageSpec {
  id: string;
  name: string;
  work: string;
  depends_on?: string[];
  protected?: boolean;
  approval_policy?: Record<string, unknown> | null;
  output_required_keys?: string[];
  condition?: string | null;
  model_route?: string | null;
  profile?: string | null;
  agent?: string | null;
  reviewer?: string | null;
  sensors?: SensorSpec[];
}

export interface WorkflowSpecDto {
  key: string;
  name: string;
  execution?: string;
  stages: StageSpec[];
}

export interface StudioAgentDto {
  key: string;
  kind: "lead" | "reviewer";
  profile: string;
  version: number | null;
  instructions: string;
  required_keys: string[];
  model_route: string | null;
  context_sources: string[];
  tools: string[];
}

export interface StudioCatalogDto {
  work: { key: string; ai: boolean }[];
  roles: string[];
  policy_types: string[];
  sensors: { key: string; category: string; description: string; evidence_kind: string | null }[];
  profiles: { key: string; name: string }[];
  agents: StudioAgentDto[];
  model_routes: string[];
  tools: { key: string; permission_class: string; grantable: boolean }[];
  context_sources: { lead: string[]; reviewer: string[] };
  rule_scopes: string[];
  rule_kinds: string[];
  hook_events: string[];
  hook_pre_events: string[];
  hook_blockable: [string, string][];
  hook_actions: Record<string, string>;
}

export interface StudioVersionDto {
  id: string;
  version: number;
  sha256: string;
  created_at: string;
}

export interface StudioDraftDto {
  key: string;
  name: string;
  spec: WorkflowSpecDto;
  revision: number;
  updated_at: string;
}

export interface StudioWorkflowSummaryDto {
  key: string;
  name: string;
  scope: "platform" | "organization";
  latest: StudioVersionDto | null;
  draft_revision: number | null;
}

export interface StudioWorkflowDto {
  key: string;
  scope: "platform" | "organization";
  draft: StudioDraftDto | null;
  versions: (StudioVersionDto & { spec: WorkflowSpecDto })[];
}

export interface StudioRuleDto {
  id: string;
  key: string;
  scope_type: string;
  scope_key: string;
  kind: string;
  status: string;
  version: number;
  name: string;
}

export interface StudioHookDto {
  key: string;
  enabled: boolean;
  version: number;
  event: string;
  phase: string;
  action: string;
  failure_policy: string;
}

export interface StudioProposalDto {
  id: string;
  target: string;
  key: string;
  payload: Record<string, unknown>;
  conflicts: string[];
  proposer_type: string;
  status: string;
}

export interface AgentVersionBody {
  instructions: string;
  required_keys: string[];
  model_route: string;
  context_sources: string[];
  tools: string[];
}

const orgPath = (orgId: string) => `/api/v1/orgs/${encodeURIComponent(orgId)}`;
const studioPath = (orgId: string) => `${orgPath(orgId)}/studio`;

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

interface Problem {
  code?: string;
  title?: string;
  problems?: string[];
}

export async function request<T>(method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  const res = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = (await res.json().catch(() => ({}))) as Problem & T;
  if (!res.ok) {
    throw new ApiError(res.status, data.code ?? "http_error", data.title ?? "Something went wrong", data.problems);
  }
  return data;
}

export const api = {
  signup: (email: string, password: string, displayName: string) =>
    request<{ status: string }>("POST", "/api/v1/auth/signup", {
      email,
      password,
      display_name: displayName,
    }),
  verifyEmail: (token: string) => request<{ status: string }>("POST", "/api/v1/auth/verify-email", { token }),
  login: (email: string, password: string) =>
    request<SessionDto>("POST", "/api/v1/auth/login", { email, password }),
  logout: () => request<{ status: string }>("POST", "/api/v1/auth/logout"),
  me: () => request<SessionDto>("GET", "/api/v1/auth/me"),
  listOrgs: () => request<{ items: OrgDto[] }>("GET", "/api/v1/orgs"),
  listProjects: () => request<{ items: ProjectDto[] }>("GET", "/api/v1/projects"),
  getProject: (id: string) => request<ProjectDto>("GET", `/api/v1/projects/${encodeURIComponent(id)}`),
  previewInvitation: (token: string) => request<InvitationPreviewDto>("POST", "/api/v1/invitations/preview", { token }),
  acceptInvitation: (token: string) =>
    request<{ organization_id: string; project_id: string | null }>("POST", "/api/v1/invitations/accept", { token }),
  listMembers: (orgId: string) => request<OrgMembersDto>("GET", `/api/v1/orgs/${encodeURIComponent(orgId)}/members`),
  createInvitation: (orgId: string, email: string, role: string, projectId: string | null, projectRole: string | null) =>
    request<{ id: string }>("POST", `/api/v1/orgs/${encodeURIComponent(orgId)}/invitations`, {
      email,
      role,
      project_id: projectId,
      project_role: projectRole,
    }),
  revokeInvitation: (orgId: string, id: string) =>
    request("POST", `/api/v1/orgs/${encodeURIComponent(orgId)}/invitations/${encodeURIComponent(id)}/revoke`),
  setOrgRole: (orgId: string, userId: string, role: string) =>
    request("PUT", `/api/v1/orgs/${encodeURIComponent(orgId)}/members/${encodeURIComponent(userId)}`, { role }),
  removeMember: (orgId: string, userId: string) =>
    request("DELETE", `/api/v1/orgs/${encodeURIComponent(orgId)}/members/${encodeURIComponent(userId)}`),
  listProjectMembers: (projectId: string) =>
    request<{ items: ProjectMemberDto[] }>("GET", `/api/v1/projects/${encodeURIComponent(projectId)}/members`),
  setProjectRole: (projectId: string, userId: string, role: string) =>
    request("PUT", `/api/v1/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`, { role }),
  removeProjectMember: (projectId: string, userId: string) =>
    request("DELETE", `/api/v1/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`),
  studioCatalog: (orgId: string) => request<StudioCatalogDto>("GET", `${studioPath(orgId)}/catalog`),
  studioWorkflows: (orgId: string) =>
    request<{ items: StudioWorkflowSummaryDto[] }>("GET", `${studioPath(orgId)}/workflows`),
  studioWorkflow: (orgId: string, key: string) =>
    request<StudioWorkflowDto>("GET", `${studioPath(orgId)}/workflows/${encodeURIComponent(key)}`),
  saveStudioDraft: (orgId: string, key: string, spec: WorkflowSpecDto, expectedRevision: number | null) =>
    request<StudioDraftDto>("PUT", `${studioPath(orgId)}/workflows/${encodeURIComponent(key)}/draft`, {
      spec,
      expected_revision: expectedRevision,
    }),
  validateStudioWorkflow: (orgId: string, spec: WorkflowSpecDto) =>
    request<{ valid: boolean; problems: string[] }>("POST", `${studioPath(orgId)}/validate`, { spec }),
  publishStudioWorkflow: (orgId: string, key: string, expectedRevision: number) =>
    request<StudioVersionDto>("POST", `${studioPath(orgId)}/workflows/${encodeURIComponent(key)}/publish`, {
      expected_revision: expectedRevision,
    }),
  exportStudioWorkflow: (orgId: string, key: string, format: "json" | "yaml") =>
    request<{ filename: string; content: string }>(
      "GET",
      `${studioPath(orgId)}/workflows/${encodeURIComponent(key)}/export?format=${format}`,
    ),
  importStudioWorkflow: (orgId: string, format: "json" | "yaml", content: string) =>
    request<{ draft: StudioDraftDto; problems: string[] }>("POST", `${studioPath(orgId)}/import`, { format, content }),
  createProfile: (orgId: string, key: string, name: string) =>
    request("POST", `${orgPath(orgId)}/profiles`, { key, name }),
  createAgent: (orgId: string, body: AgentVersionBody & { profile: string; key: string; kind: string }) =>
    request("POST", `${orgPath(orgId)}/agents`, body),
  addAgentVersion: (orgId: string, key: string, body: AgentVersionBody) =>
    request("POST", `${orgPath(orgId)}/agents/${encodeURIComponent(key)}/versions`, body),
  studioRules: (orgId: string) => request<{ items: StudioRuleDto[] }>("GET", `${orgPath(orgId)}/rules`),
  saveRule: (orgId: string, body: Record<string, string>) => request("POST", `${orgPath(orgId)}/rules`, body),
  retireRule: (orgId: string, id: string) =>
    request("POST", `${orgPath(orgId)}/rules/${encodeURIComponent(id)}/retire`),
  studioProposals: (orgId: string) => request<{ items: StudioProposalDto[] }>("GET", `${orgPath(orgId)}/proposals`),
  decideProposal: (orgId: string, id: string, approve: boolean) =>
    request("POST", `${orgPath(orgId)}/proposals/${encodeURIComponent(id)}/decision`, { approve }),
  studioHooks: (orgId: string) => request<{ items: StudioHookDto[] }>("GET", `${orgPath(orgId)}/hooks`),
  saveHook: (orgId: string, key: string, body: Record<string, unknown>) =>
    request("PUT", `${orgPath(orgId)}/hooks/${encodeURIComponent(key)}`, body),
  setHookEnabled: (orgId: string, key: string, enabled: boolean) =>
    request("POST", `${orgPath(orgId)}/hooks/${encodeURIComponent(key)}/enabled`, { enabled }),
  createProject: (orgId: string, name: string, description: string, projectType: string) =>
    request<ProjectDto>("POST", `/api/v1/orgs/${encodeURIComponent(orgId)}/projects`, {
      name,
      description,
      project_type: projectType,
    }),
};
