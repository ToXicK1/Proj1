import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState, IdentityTag, PageHeader, Panel, Skeleton, StatusPill, type Tone } from "../components/ui";
import { type AccessDto, ApiError, api, type MyDayDto } from "../api";
import { STEP_LABELS } from "../portal/Collaboration";
import { PROFILES } from "../portal/roles";
import { type TeamCardDto, workApi } from "../workspace/workApi";
import { ROLE_SPACES } from "../workspace/tools";

// The Workspace: where the work is done. Home keeps the day's information (approvals, tickets, messages). Here each
// project shows, for every profile the person works in, what is happening in that role (its current step, what waits
// for approval, records, packages, handoffs, blockers; for the Developer the code: change sets, the Developer AI and
// the last build), and opens that profile's own tool. Every figure comes from recorded work.

const label = (key: string) => PROFILES.find(([k]) => k === key)?.[1] ?? key;
const AI_LABEL: Record<string, string> = {
  queued: "queued", working: "working", in_review: "change set in review", checks_failed: "checks failed",
  failed: "failed", cancelled: "cancelled",
};
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** What is happening in one role on one project, built from that department's real records. */
export function roleLines(card: TeamCardDto): [string, Tone][] {
  const lines: [string, Tone][] = [];
  const w = card.work;
  if (card.awaiting_approval) lines.push([`${plural(card.awaiting_approval, "step")} awaiting approval`, "pending"]);
  if (w.packages_awaiting_decision) lines.push([`${plural(w.packages_awaiting_decision, "package")} awaiting a decision`, "pending"]);
  if (w.incoming_handoffs) lines.push([plural(w.incoming_handoffs, "incoming handoff"), "pending"]);
  if (w.to_confirm) lines.push([`${plural(w.to_confirm, "AI suggestion")} to confirm`, "info"]);
  const code = card.code;
  if (code) {
    if (!code.repository) lines.push(["No repository yet", "neutral"]);
    if (code.change_sets_in_review) lines.push([`${plural(code.change_sets_in_review, "change set")} in review`, "pending"]);
    if (code.change_sets_approved) lines.push([`${plural(code.change_sets_approved, "change set")} approved, ready to merge`, "success"]);
    if (code.ai_run) lines.push([`Developer AI run ${code.ai_run.number}: ${AI_LABEL[code.ai_run.status] ?? code.ai_run.status}`,
      ["checks_failed", "failed"].includes(code.ai_run.status) ? "blocked" : "info"]);
    if (code.last_build) {
      const result = code.last_build.passed ? "passed" : code.last_build.status === "succeeded" ? "failed" : code.last_build.status;
      lines.push([`Last build ${result}${code.last_build.summary ? `: ${code.last_build.summary}` : ""}`, code.last_build.passed ? "success" : "blocked"]);
    }
  }
  return lines;
}

function RoleOverview({ card }: { card: TeamCardDto }) {
  if (!card.visible) return <p className="muted small">Details stay inside the department.</p>;
  const lines = roleLines(card);
  const [stepLabel, stepTone] = card.current ? STEP_LABELS[card.current.status] ?? [card.current.status, "neutral" as Tone]
    : ["", "neutral" as Tone];
  const w = card.work;
  return (
    <div className="stack-sm">
      <p className="small">
        {card.current ? <>Now: <strong>{card.current.name}</strong> <StatusPill label={stepLabel} tone={stepTone} /></>
          : !card.started ? "Not started yet." : !card.steps ? "No lifecycle steps in this kind of work."
            : "All of its lifecycle steps are done."}
      </p>
      <p className="muted small">
        {card.steps ? `${card.steps_done ?? 0} of ${card.steps} steps approved · ` : ""}{plural(w.records, "record")} ({w.approved} approved)
      </p>
      {card.issues && card.issues.length > 0 && (
        <ul className="workspace-lines">{card.issues.slice(0, 3).map((i, n) => (
          <li key={n}><StatusPill label="Blocked" tone="blocked" /> {i.text}</li>))}</ul>
      )}
      {lines.length > 0
        ? <ul className="workspace-lines">{lines.map(([text, tone]) => <li key={text}><StatusPill label={text} tone={tone} /></li>)}</ul>
        : !card.issues?.length && <p className="muted small">{card.code?.repository
          ? "Repository ready. No change sets, Developer AI runs or builds yet." : "Nothing waiting."}</p>}
      <p className="small">{card.people.length ? card.people.map((n) => <IdentityTag key={n} kind="human">{n}</IdentityTag>)
        : <span className="muted">Nobody assigned</span>}{card.ai_lead && <IdentityTag kind="ai">AI team</IdentityTag>}</p>
    </div>
  );
}

/** One project. Its overview loads when it comes into view: an administrator may have many projects. */
function ProjectWorkspaces({ projectId, project, profiles, own }: { projectId: string; project: string; profiles: string[];
  own: string[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [cards, setCards] = useState<Record<string, TeamCardDto> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    let started = false;
    const load = () => {
      if (started) return;
      started = true;
      workApi.team(projectId).then((r) => setCards(Object.fromEntries(r.departments.map((c) => [c.profile, c]))))
        .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load this project's overview."));
    };
    if (typeof IntersectionObserver === "undefined") { load(); return undefined; }
    const seen = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { load(); seen.disconnect(); }
    }, { rootMargin: "300px" });
    seen.observe(el);
    return () => seen.disconnect();
  }, [projectId]);

  return (
    <div ref={ref}>
      <Panel title={project} label={`Workspaces in ${project}`}>
        {error && <p role="alert" className="error">{error}</p>}
        <ul className="workspace-grid">
          {profiles.map((key) => {
            const space = ROLE_SPACES[key];
            if (!space) return null;
            const tools = own.includes(key) ? space.tools : [];  // a role's tools are for the people who hold it
            const card = cards?.[key];
            return (
              <li key={key} className="workspace-card" aria-label={`${label(key)} in ${project}`}>
                <div className="workspace-head">
                  <span className="workspace-role">{label(key)}</span>
                  {space.tools.length > 0 && <StatusPill label="Professional tools" tone="success" />}
                </div>
                {card ? <RoleOverview card={card} /> : !error && <Skeleton title={false} lines={3} />}
                <span className="actions">
                  <Link to={space.overview.to(projectId)} className="button workspace-open"
                    aria-label={`Open ${space.overview.name} for ${label(key)} in ${project}`}>{space.overview.name}</Link>
                  {tools.map((t) => (
                    <Link key={t.name} to={t.to(projectId)} className="button secondary"
                      aria-label={`Open ${t.name} for ${label(key)} in ${project}`}>{t.name}</Link>))}
                </span>
                <span className="muted small">{space.overview.what}</span>
              </li>
            );
          })}
        </ul>
      </Panel>
    </div>
  );
}

export function WorkspacePage() {
  const [day, setDay] = useState<MyDayDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [access, setAccess] = useState<AccessDto | null>(null);
  useEffect(() => { api.access().then(setAccess).catch(() => setAccess(null)); }, []);
  const own = access && !access.is_admin && !access.is_manager ? access.profiles : [];

  useEffect(() => {
    api.myDay().then(setDay).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load your workspaces."));
  }, []);

  return (
    <div className="page">
      <PageHeader eyebrow="Workspace" title="Your workspaces"
        meta="What is happening in each of your roles, project by project, and the way into your tools. Your to-dos stay on Home." />
      {error && <p role="alert" className="error">{error}</p>}
      {day === null && !error && <Skeleton />}
      {day !== null && day.workspaces.length === 0 && (
        <EmptyState title="No workspaces yet.">Workspaces appear when you are on a project's professional team.</EmptyState>
      )}
      <div className="stack">
        {day?.workspaces.map((w) => (
          <ProjectWorkspaces key={w.project_id} projectId={w.project_id} project={w.project} profiles={w.profiles} own={own} />))}
      </div>
    </div>
  );
}
