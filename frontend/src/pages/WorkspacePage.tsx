import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, PageHeader, Panel, Skeleton, StatusPill } from "../components/ui";
import { ApiError, api, type MyDayDto } from "../api";
import { PROFILES } from "../portal/roles";
import { DEPARTMENT_PATH } from "../workspace/modules";

// The Workspace: where the work is done. Home keeps the day's information (approvals, tickets, messages); here each
// profile opens its own professional tool for a project, with what the AI made and the department's documents.
// Profiles get their full tool one at a time (Developer first: the IDE); until then the department workspace opens.

interface Tool { name: string; what: string; full: boolean; to: (projectId: string) => string }

const department = (key: string) => (p: string) => `/projects/${encodeURIComponent(p)}/work/${DEPARTMENT_PATH[key]}`;

export const WORKSPACE_TOOLS: Record<string, Tool> = {
  software_developer: { name: "IDE", what: "Code, source control, change sets, build and test, terminal, Developer AI",
    full: true, to: (p) => `/projects/${encodeURIComponent(p)}/ide` },
  business_analyst: { name: "Requirements workspace", what: "AI drafts, requirements, user stories, BRD and SRS",
    full: false, to: department("business_analyst") },
  solution_architect: { name: "Architecture workspace", what: "AI drafts, architecture records, decisions, APIs and data models",
    full: false, to: department("solution_architect") },
  ui_ux_designer: { name: "Design workspace", what: "AI drafts, screens, flows and design records",
    full: false, to: department("ui_ux_designer") },
  qa_security: { name: "QA workspace", what: "AI drafts, test cases, defects and security checks",
    full: false, to: department("qa_security") },
  devops_release: { name: "DevOps workspace", what: "AI drafts, pipelines, environments and releases",
    full: false, to: department("devops_release") },
  project_manager: { name: "Project workspace", what: "Meetings, the brief, kickoff, plans and every department's work",
    full: false, to: department("project_manager") },
};

export function WorkspacePage() {
  const [day, setDay] = useState<MyDayDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.myDay().then(setDay).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load your workspaces."));
  }, []);

  const label = (key: string) => PROFILES.find(([k]) => k === key)?.[1] ?? key;
  return (
    <div className="page">
      <PageHeader eyebrow="Workspace" title="Your workspaces"
        meta="Where the work happens: your professional tools, what the AI made, and the documents. Your to-dos stay on Home." />
      {error && <p role="alert" className="error">{error}</p>}
      {day === null && !error && <Skeleton />}
      {day !== null && day.workspaces.length === 0 && (
        <EmptyState title="No workspaces yet.">Workspaces appear when you are on a project's professional team.</EmptyState>
      )}
      <div className="stack">
        {day?.workspaces.map((w) => (
          <Panel key={w.project_id} title={w.project} label={`Workspaces in ${w.project}`}>
            <ul className="workspace-grid">
              {w.profiles.map((key) => {
                const tool = WORKSPACE_TOOLS[key];
                if (!tool) return null;
                return (
                  <li key={key} className="workspace-card">
                    <Link to={tool.to(w.project_id)} className="workspace-link" aria-label={`Open ${tool.name} for ${label(key)} in ${w.project}`}>
                      <span className="workspace-role">{label(key)}</span>
                      <span className="workspace-name">{tool.name}</span>
                      <span className="muted">{tool.what}</span>
                      <StatusPill label={tool.full ? "Professional tool" : "Department workspace"} tone={tool.full ? "success" : undefined} />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </Panel>
        ))}
      </div>
    </div>
  );
}
