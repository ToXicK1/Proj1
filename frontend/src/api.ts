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
  role: "org_admin" | "project_owner" | "member";
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
  role: "org_admin" | "project_owner" | "member";
  status: "active" | "pending";
  requested_role: string | null;
  profiles: string[];
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

export interface WorkspaceDto {
  project: { id: string; name: string; description: string; type: string; status: string };
  role: string;
  scope: "owner" | "admin" | "professional" | "member";
  my_profiles: string[];
  can_triage: boolean;
  started: boolean;
  completed: boolean;
  progress: number;
  current_step: { name: string; phase: string; number: string; status: string; profile: string } | null;
  team: { profile: string; representative: string; status: string; stages_done: number; stages_total: number; assigned: string[] }[];
  phases: { name: string; stages: { id: string; number: string; name: string; profile: string; status: string }[] }[];
  pending_actions: { kind: string; what: string; why: string; action: string; stage: string }[];
  activity: { at: string; text: string }[];
}

export interface IntakeQuestionDto {
  field: string;
  question: string;
  required: boolean;
}

export interface IntakeDto {
  revision: number;
  status: string;
  started: boolean;
  items: { field: string; label: string; value: string; tag: string; confirmed: boolean }[];
  next_question: IntakeQuestionDto | null;
  questions: IntakeQuestionDto[];
  still_needed: string[];
  can_confirm: boolean;
  scopes: { key: string; label: string; stages: number }[];
  default_scope: string;
}

export interface DeliverableDto {
  stage: string;
  profile: string;
  number: string;
  phase: string;
  name: string;
  representative: string;
  status: string;
  current_version_id: string;
  can_decide: boolean;
  checks_blocking: boolean;
  can_view_code: boolean;
  versions: {
    id: string;
    number: number;
    created_at: string;
    content: Record<string, unknown>;
    has_code: boolean;
    checks: { name: string; passed: boolean; summary: string }[];
  }[];
  change_requests: { comment: string; status: string }[];
}

export interface ActivityFieldDto {
  key: string;
  text?: string;
  count?: number;
  items?: string[];
  files?: { path: string; lines: number; bytes: number }[];
}

export interface ActivityItemDto {
  id: string;
  kind: "job" | "stage" | "context" | "model_call" | "output" | "retry" | "model_error" | "review" | "checks" | "result" | string;
  title: string;
  stage: string | null;
  stage_name: string | null;
  department: string | null;
  profile: string | null;
  at: string;
  detail: {
    agent?: string;
    seconds?: number;
    tokens?: { in: number; out: number };
    fields?: ActivityFieldDto[];
    brief?: string[];
    earlier_work?: { stage: string; name: string; reason: string; chars: number; full_chars: number; included: boolean }[];
    feedback?: string[];
    addressing?: string[];
    must_return?: string[];
    rules?: unknown[];
    revision?: number;
    verdict?: string;
    findings?: string[];
    checks?: { name: string; passed: boolean; summary: string; output: string[] }[];
    files?: { path: string; lines: number; bytes: number }[];
    status?: string;
    reason?: string | null;
    error?: string | null;
    note?: string;
    // a live model call
    role?: string;
    attempt?: number;
    state?: "waiting" | "streaming" | "done" | "failed";
    text?: string;
    thinking?: string;
    elapsed?: number;
    prompt?: { system: string; user: string; cut: boolean };
    prompt_tokens_est?: number;
    context_tokens?: number;
    reply_room_est?: number;
    max_reply_tokens?: number;
    warning?: string | null;
    hidden?: string;
  };
}

export interface ActivityDto {
  items: ActivityItemDto[];
  jobs: { kind: string; status: string; attempts: number; since: string }[];
}

export interface ScopeDto {
  kind: "owner" | "admin" | "manager" | "professional" | "member";
  role: string;
  profiles: string[];
  channels: { key: string; name: string }[];
}

export interface PersonDto {
  user_id: string;
  name: string;
  profiles: string[];
  is_owner: boolean;
  is_you: boolean;
  kind?: string;
  role?: string;
}

export interface TeamMessageDto {
  id: string;
  channel: string;
  author_type: "human" | "ai" | "system";
  author: string;
  mine: boolean;
  body: string;
  mentions: string[];
  mentions_me: boolean;
  author_id?: string | null;
  direct?: boolean;
  to?: string | null;
  to_id?: string | null;
  created_at: string;
}

export interface OversightStepDto {
  stage: string;
  name: string;
  status: string;
  note: string | null;
}

export interface OversightDto {
  role: string;
  totals: { projects: number; approvals: number; working: number; issues: number; open_tickets: number };
  projects: {
    id: string;
    name: string;
    owners: string[];
    started: boolean;
    open_tickets: number;
    departments: { profile: string; title: string; people: string[]; current: OversightStepDto | null; steps: number; done: number; issues: number }[];
    approvals: { step: string; department: string; who: string }[];
    working: { step: string; department: string; note: string | null; slow: boolean }[];
    issues: { text: string; kind: string; department: string }[];
  }[];
}

export interface DepartmentStatusDto {
  profile: string;
  title: string;
  people: string[];
  started: boolean;
  summary: string;
  steps: { stage: string; number: string; name: string; status: string; note: string | null; slow: boolean; since: string | null }[];
  issues: { stage: string; kind: string; text: string }[];
}

export interface TicketDto {
  id: string;
  number: number;
  title: string;
  body: string;
  kind: string;
  profile: string;
  department: string;
  status: string;
  raised_by: string;
  assignee: string | null;
  ai_proposal: string | null;
  can_act: boolean;
  is_mine: boolean;
  created_at: string;
  updated_at: string;
  comments?: { author_type: "human" | "ai" | "system"; author: string; body: string; created_at: string }[];
}

export interface PortalMessageDto {
  id: string;
  profile: string;
  author_type?: string;
  from: string;
  mine: boolean;
  body: string;
  created_at: string;
}

export interface FeedbackDto {
  id: string;
  kind: string;
  status: string;
  summary: string;
  handled_by: string;
}

export interface NotificationDto {
  id: string;
  project_id: string | null;
  kind: string;
  message: string;
  read: boolean;
}

export interface AccessDto {
  status: "active" | "pending" | "none";
  is_admin: boolean;
  is_manager: boolean;
  oversees: boolean;
  can_create_projects: boolean;
  profiles: string[];
  requested_role: string | null;
  organization: string | null;
}

export interface MyReviewDto {
  project_id: string;
  project: string;
  stage: string;
  profile_key: string;
  name: string;
  phase: string;
  profile: string;
}

export const JOIN_ROLES = [
  ["project_owner", "Project Owner"],
  ["project_manager", "Project Manager"],
  ["org_admin", "Administrator"],
  ["business_analyst", "Business Analyst"],
  ["solution_architect", "Solution Architect"],
  ["ui_ux_designer", "UI/UX Designer"],
  ["software_developer", "Software Developer"],
  ["qa_security", "QA & Security Engineer"],
  ["devops_release", "DevOps & Release Engineer"],
] as const;

export interface ProviderDto {
  id: string;
  name: string;
  adapter_type: string;
}

const portalPath = (projectId: string) => `/api/v1/portal/projects/${encodeURIComponent(projectId)}`;
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
  access: () => request<AccessDto>("GET", "/api/v1/orgs/access"),
  myReviews: () => request<{ items: MyReviewDto[] }>("GET", "/api/v1/portal/my-reviews"),
  setMemberAccess: (orgId: string, userId: string, role: string, profiles: string[]) =>
    request("PUT", `${orgPath(orgId)}/members/${encodeURIComponent(userId)}/access`, { role, profiles }),
  signup: (email: string, password: string, displayName: string, requestedRole = "project_owner") =>
    request<{ status: string }>("POST", "/api/v1/auth/signup", {
      email,
      password,
      display_name: displayName,
      requested_role: requestedRole,
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
  portalWorkspace: (id: string) => request<WorkspaceDto>("GET", portalPath(id)),
  portalIntake: (id: string) => request<IntakeDto>("GET", `${portalPath(id)}/intake`),
  portalAnswer: (id: string, field: string, kind: string, answer: string) =>
    request<IntakeDto>("POST", `${portalPath(id)}/intake/answers`, { field, kind, answer }),
  portalConfirm: (id: string, revision: number, acceptAssumptions: string[], scope: string) =>
    request("POST", `${portalPath(id)}/intake/confirm`, { revision, accept_assumptions: acceptAssumptions, scope }),
  portalDeliverables: (id: string) => request<{ items: DeliverableDto[] }>("GET", `${portalPath(id)}/deliverables`),
  portalDecide: (id: string, stage: string, versionId: string, decision: string, comment: string, key: string) =>
    request("POST", `${portalPath(id)}/deliverables/${encodeURIComponent(stage)}/decision`, {
      version_id: versionId,
      decision,
      comment,
      idempotency_key: key,
    }),
  portalRetry: (id: string, stage: string) =>
    request("POST", `${portalPath(id)}/stages/${encodeURIComponent(stage)}/retry`),
  portalMessages: (id: string) => request<{ items: PortalMessageDto[] }>("GET", `${portalPath(id)}/messages`),
  globalChannels: () => request<{ items: { key: string; name: string }[]; kind: string }>("GET", "/api/v1/team-chat/channels"),
  oversight: () => request<OversightDto>("GET", "/api/v1/oversight"),
  globalPeople: () => request<{ items: PersonDto[] }>("GET", "/api/v1/team-chat/people"),
  globalMessages: (channel: string) =>
    request<{ items: TeamMessageDto[] }>("GET", `/api/v1/team-chat/messages/${encodeURIComponent(channel)}`),
  postGlobalMessage: (channel: string, body: string, to: string | null) =>
    request<TeamMessageDto>("POST", "/api/v1/team-chat/messages", { channel, body, to }),
  portalScope: (id: string) => request<ScopeDto>("GET", `${portalPath(id)}/scope`),
  projectActivity: (id: string) => request<ActivityDto>("GET", `${portalPath(id)}/activity`),
  projectPeople: (id: string) => request<{ items: PersonDto[] }>("GET", `${portalPath(id)}/people`),
  teamChat: (id: string, channel: string) =>
    request<{ items: TeamMessageDto[] }>("GET", `${portalPath(id)}/team-chat/${encodeURIComponent(channel)}`),
  postTeamMessage: (id: string, channel: string, body: string, mentions: string[]) =>
    request<TeamMessageDto>("POST", `${portalPath(id)}/team-chat`, { channel, body, mentions }),
  departmentStatus: (id: string, profile: string) =>
    request<DepartmentStatusDto>("GET", `${portalPath(id)}/departments/${encodeURIComponent(profile)}/status`),
  tickets: (id: string) => request<{ items: TicketDto[] }>("GET", `${portalPath(id)}/tickets`),
  ticket: (id: string, ticketId: string) => request<TicketDto>("GET", `${portalPath(id)}/tickets/${encodeURIComponent(ticketId)}`),
  createTicket: (id: string, body: { title: string; body: string; kind: string; profile: string; assignee: string | null }) =>
    request<TicketDto>("POST", `${portalPath(id)}/tickets`, body),
  ticketComment: (id: string, ticketId: string, body: string) =>
    request<TicketDto>("POST", `${portalPath(id)}/tickets/${encodeURIComponent(ticketId)}/comments`, { body }),
  ticketAction: (id: string, ticketId: string, action: string, note: string) =>
    request<TicketDto>("POST", `${portalPath(id)}/tickets/${encodeURIComponent(ticketId)}/actions`, { action, note }),
  replyToOwner: (id: string, profile: string, body: string) =>
    request("POST", `${portalPath(id)}/messages/replies`, { profile, body }),
  portalSendMessage: (id: string, body: string, profile: string) =>
    request("POST", `${portalPath(id)}/messages`, { body, profile }),
  portalFeedback: (id: string) => request<{ items: FeedbackDto[] }>("GET", `${portalPath(id)}/feedback`),
  portalTestReport: (id: string, report: { steps: string; expected: string; actual: string; severity: string }) =>
    request("POST", `${portalPath(id)}/test-reports`, report),
  portalTriage: (id: string, feedbackId: string, kind: string, status: string, reason: string) =>
    request("POST", `${portalPath(id)}/feedback/${encodeURIComponent(feedbackId)}/triage`, { kind, status, reason }),
  notifications: () => request<{ items: NotificationDto[] }>("GET", "/api/v1/notifications"),
  readNotification: (id: string) => request("POST", `/api/v1/notifications/${encodeURIComponent(id)}/read`),
  studioProviders: (orgId: string) => request<{ items: ProviderDto[] }>("GET", `${orgPath(orgId)}/providers`),
  createProvider: (orgId: string, body: { name: string; adapter_type: string; base_url: string | null; api_key: string | null }) =>
    request("POST", `${orgPath(orgId)}/providers`, body),
  createRoute: (orgId: string, key: string, providerId: string, model: string) =>
    request("POST", `${orgPath(orgId)}/model-routes`, { key, primary_provider_id: providerId, primary_model: model }),
  testProvider: (orgId: string, providerId: string, model: string) =>
    request<{ ok: boolean }>("POST", `${orgPath(orgId)}/providers/${encodeURIComponent(providerId)}/health`, { model }),
  setupDeliveryTeam: (orgId: string, modelRoute: string) =>
    request("POST", `${studioPath(orgId)}/default-lifecycle`, { model_route: modelRoute }),
  createProject: (orgId: string, name: string, description: string, projectType: string) =>
    request<ProjectDto>("POST", `/api/v1/orgs/${encodeURIComponent(orgId)}/projects`, {
      name,
      description,
      project_type: projectType,
    }),
};
