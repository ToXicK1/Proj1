import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { IdentityTag, PageHeader, Skeleton, StatusPill, type Tone } from "../components/ui";
import { STEP_LABELS } from "../portal/Collaboration";
import { DEPARTMENT_PATH } from "../workspace/modules";
import { type TeamCardDto, workApi } from "../workspace/workApi";

/** An administrator names the project's Project Manager from the people holding the PM profile (RD-20). */
function AssignManager({ projectId, current, onDone }: { projectId: string; current: string | null; onDone: () => void }) {
  const [people, setPeople] = useState<{ user_id: string; display_name: string }[]>([]);
  const [chosen, setChosen] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.listOrgs().then(async (o) => {
      const org = o.items.find((x) => x.role === "org_admin");
      if (!org) return;
      const m = await api.listMembers(org.id);
      setPeople(m.members.filter((x) => x.profiles.includes("project_manager") && x.status === "active"));
    }).catch(() => setPeople([]));
  }, []);
  return (
    <div className="actions">
      <label>{current ? "Change Project Manager" : "Assign a Project Manager"}
        <select value={chosen} onChange={(e) => setChosen(e.target.value)}>
          <option value="">Choose a person</option>
          {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.display_name}</option>)}
        </select>
      </label>
      <button type="button" disabled={!chosen} onClick={async () => {
        setError(null);
        try { await api.assignManager(projectId, chosen); setChosen(""); onDone(); }
        catch (e) { setError(e instanceof ApiError ? e.message : "Could not assign the Project Manager."); }
      }}>Assign</button>
      {people.length === 0 && <span className="hint">Add a Project Manager in Team first.</span>}
      {error && <span role="alert" className="error">{error}</span>}
    </div>
  );
}

/** The seven professional profiles of this project, each opening its own workspace. Every figure comes from
 * recorded work. */
export function ProfessionalTeamPage() {
  const { projectId = "" } = useParams();
  const [cards, setCards] = useState<TeamCardDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [admin, setAdmin] = useState(false);
  const load = useCallback(() => {
    workApi.team(projectId).then((r) => setCards(r.departments))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load the team."));
  }, [projectId]);
  useEffect(load, [load]);
  useEffect(() => { api.access().then((a) => setAdmin(a.is_admin)).catch(() => setAdmin(false)); }, []);
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
              {c.profile === "project_manager" && admin && (
                <AssignManager projectId={projectId} current={c.people[0] ?? null} onDone={load} />
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
