// Typed client for the backend API. The CSRF token lives in memory only; the session cookie is
// HttpOnly and never readable from script.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
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

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

interface Problem {
  code?: string;
  title?: string;
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
    throw new ApiError(res.status, data.code ?? "http_error", data.title ?? "Something went wrong");
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
  createProject: (orgId: string, name: string, description: string, projectType: string) =>
    request<ProjectDto>("POST", `/api/v1/orgs/${encodeURIComponent(orgId)}/projects`, {
      name,
      description,
      project_type: projectType,
    }),
};
