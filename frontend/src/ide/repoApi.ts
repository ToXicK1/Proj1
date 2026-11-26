import { request } from "../api";

// The project repository and executions (Phase 1 APIs), for the Developer IDE. Every git operation runs in the
// executor's isolated containers; these calls only ask for it and read the results.

export interface RepoStatusDto { exists: boolean; status?: string; default_branch?: string; head_sha?: string }
export interface TreeEntryDto { path: string; sha: string; size: number }
export interface TreeDto {
  ref: string; commit: string; tree: TreeEntryDto[];
  files: { path: string; content?: string; missing?: boolean; too_large?: boolean }[];
}
export interface LogDto { ref: string; branches: string[]; commits: { commit: string; author: string; date: string; subject: string }[] }
export interface DiffDto {
  base: string; head: string; merge_base: string; head_commit: string; patch: string; truncated: boolean;
  files: { path: string; added: number | null; removed: number | null }[];
}
export interface CommitDto { branch: string; commit: string; parent: string | null; changed: string[] }
export interface ChangeSetDto {
  id: string; number: number; title: string; description: string; branch: string; base_sha: string; head_sha: string;
  status: string; files: { path: string; added: number | null; removed: number | null }[]; approved_sha: string;
  decision_note: string; author_user_id: string | null; decided_by_user_id: string | null; merged_sha: string;
  created_at: string | null;
}
export interface ExecutionDto {
  id: string; kind: string; status: string; image: string; limits: Record<string, unknown>; exit_code: number | null;
  output: string; failure: string; created_at: string | null; started_at: string | null; finished_at: string | null;
  result: { status?: string; language?: string | null; duration_ms?: number;
    checks?: Record<string, { passed: boolean; summary: string; output?: string }> };
}

const repo = (p: string) => `/api/v1/projects/${encodeURIComponent(p)}/repository`;
const runs = (p: string) => `/api/v1/projects/${encodeURIComponent(p)}/executions`;
const query = (params: Record<string, string | string[]>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) for (const one of Array.isArray(v) ? v : [v]) q.append(k, one);
  return q.toString();
};

export const repoApi = {
  status: (p: string) => request<RepoStatusDto>("GET", repo(p)),
  create: (p: string) => request<RepoStatusDto>("POST", repo(p)),
  tree: (p: string, ref: string, paths: string[] = []) =>
    request<TreeDto>("GET", `${repo(p)}/tree?${query({ ref, ...(paths.length ? { path: paths } : {}) })}`),
  log: (p: string, ref: string) => request<LogDto>("GET", `${repo(p)}/log?${query({ ref })}`),
  diff: (p: string, head: string, base = "main") => request<DiffDto>("GET", `${repo(p)}/diff?${query({ head, base })}`),
  commit: (p: string, branch: string, message: string, files: { path: string; content?: string; delete?: boolean }[]) =>
    request<CommitDto>("POST", `${repo(p)}/commits`, { branch, message, files }),
  changeSets: (p: string) => request<{ items: ChangeSetDto[] }>("GET", `${repo(p)}/change-sets`),
  openChangeSet: (p: string, branch: string, title: string, description = "") =>
    request<ChangeSetDto>("POST", `${repo(p)}/change-sets`, { branch, title, description }),
  decide: (p: string, id: string, decision: "approve" | "request_changes", reviewedSha: string, note = "") =>
    request<ChangeSetDto>("POST", `${repo(p)}/change-sets/${encodeURIComponent(id)}/decision`,
      { decision, reviewed_sha: reviewedSha, note }),
  merge: (p: string, id: string) => request<ChangeSetDto>("POST", `${repo(p)}/change-sets/${encodeURIComponent(id)}/merge`),
  runChecks: (p: string, files: { path: string; content: string }[]) =>
    request<ExecutionDto>("POST", runs(p), { kind: "checks", payload: { files } }),
  execution: (p: string, id: string) => request<ExecutionDto>("GET", `${runs(p)}/${encodeURIComponent(id)}`),
  executions: (p: string) => request<{ items: ExecutionDto[] }>("GET", runs(p)),
};
