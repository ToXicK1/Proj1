import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api";
import { IdentityTag, PageHeader, Skeleton, StatusPill, type Tone } from "../components/ui";
import { STEP_LABELS } from "../portal/Collaboration";
import { DEPARTMENT_PATH } from "../workspace/modules";
import { type TeamCardDto, workApi } from "../workspace/workApi";

/** The six departments of this project, each opening its own workspace. Every figure comes from recorded work. */
export function ProfessionalTeamPage() {
  const { projectId = "" } = useParams();
  const [cards, setCards] = useState<TeamCardDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    workApi.team(projectId).then((r) => setCards(r.departments))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load the team."));
  }, [projectId]);
  if (error) return <section className="page"><h1>Professional team</h1><p role="alert" className="error">{error}</p></section>;
  if (!cards) return <section className="page"><Skeleton lines={6} /></section>;
  return (
    <div className="page">
      <PageHeader eyebrow="Project" title="Professional team"
        meta="Each department, who is assigned, what it is working on and what waits on it."
        actions={<Link to={`/projects/${encodeURIComponent(projectId)}`} className="button secondary">Project overview</Link>} />
      <ul className="team-grid" aria-label="Departments">
        {cards.map((c) => {
          const [label, tone]: [string, Tone] = c.current ? STEP_LABELS[c.current.status] ?? [c.current.status, "neutral"] : ["", "neutral"];
          return (
            <li key={c.profile} className="panel stack-sm">
              <div className="row">
                <h2>{c.title}</h2>
                {c.issues && c.issues.length > 0 && <StatusPill label={`${c.issues.length} blocker${c.issues.length === 1 ? "" : "s"}`} tone="blocked" />}
              </div>
              <p className="small">
                {c.people.length ? c.people.map((n) => <IdentityTag key={n} kind="human">{n}</IdentityTag>)
                  : <span className="muted">Nobody assigned</span>}
                {c.ai_lead && <IdentityTag kind="ai">{c.ai_lead}</IdentityTag>}
              </p>
              {c.visible ? (
                <>
                  <p className="small">{c.current
                    ? <>Now: <strong>{c.current.name}</strong> <StatusPill label={label} tone={tone} /></>
                    : c.started ? "All of its steps are done." : "Not started: work begins when the owner confirms the brief."}</p>
                  <p className="muted small">{c.steps_done ?? 0} of {c.steps ?? 0} lifecycle steps approved ·{" "}
                    {c.awaiting_approval ?? 0} awaiting approval · {c.work.records} records, {c.work.to_confirm} to confirm ·{" "}
                    {c.work.packages_awaiting_decision} package{c.work.packages_awaiting_decision === 1 ? "" : "s"} awaiting a decision ·{" "}
                    {c.work.incoming_handoffs} incoming handoff{c.work.incoming_handoffs === 1 ? "" : "s"}</p>
                </>
              ) : (
                <p className="muted small">{c.work.approved} approved records. Details stay inside the department; you can read what it
                  approves.</p>
              )}
              <Link to={`/projects/${encodeURIComponent(projectId)}/work/${DEPARTMENT_PATH[c.profile]}`} className="button">
                Open {c.title} workspace</Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
