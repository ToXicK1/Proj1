import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api, type ScopeDto } from "../api";
import { PageHeader, Skeleton } from "../components/ui";
import { DepartmentStatus, TeamChat, projectChat } from "../portal/Collaboration";
import { PROFILES } from "../portal/roles";
import { MODULES, PATH_DEPARTMENT } from "../workspace/modules";
import { Records } from "../workspace/Records";
import { Handoffs, Later, Packages, Traceability } from "../workspace/Screens";
import { Steps } from "../workspace/Steps";
import { Intake } from "../workspace/Intake";
import { MeetingAnalysis } from "../workspace/MeetingAnalysis";
import { Kickoff } from "../workspace/Kickoff";
import { PmTasks } from "../workspace/PmTasks";
import { BaHandoff, ProjectBrief } from "../workspace/ProjectBrief";
import { ChangeRequests, ScopeBoard } from "../workspace/Scope";
import { Assistant, SelectedRecord } from "../workspace/Assistant";
import { type KindDto, type TeamCardDto, workApi } from "../workspace/workApi";

/** One department's own working environment: its module navigation, the work area, and a context panel. */
export function DepartmentWorkspacePage() {
  const { projectId = "", dept = "" } = useParams();
  const department = PATH_DEPARTMENT[dept] ?? "";
  const modules = MODULES[department] ?? [];
  const [params, setParams] = useSearchParams();
  const current = modules.find((m) => m.key === params.get("m")) ?? modules[0];
  const [kinds, setKinds] = useState<KindDto[] | null>(null);
  const [card, setCard] = useState<TeamCardDto | null>(null);
  const [scope, setScope] = useState<ScopeDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState(true);
  const [selected, setSelected] = useState<{ id: string | null; key: string | null }>({ id: null, key: null });

  useEffect(() => {
    if (!department) return;
    Promise.all([workApi.kinds(projectId), workApi.team(projectId), api.portalScope(projectId)])
      .then(([k, t, s]) => {
        setKinds(k.items);
        setCard(t.departments.find((d) => d.profile === department) ?? null);
        setScope(s);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not open this workspace."));
  }, [projectId, department]);
  const chat = useMemo(() => (scope ? projectChat(projectId, scope) : null), [projectId, scope]);

  const title = PROFILES.find(([k]) => k === department)?.[1] ?? "Department";
  if (!department) return <section className="page"><h1>No such department</h1></section>;
  if (error) return <section className="page"><h1>{title}</h1><p role="alert" className="error">{error}</p></section>;
  if (!kinds || !card || !scope || !current) return <section className="page"><Skeleton lines={6} /></section>;
  const canEdit = card.can_edit;

  return (
    <div className={`page workspace workspace-${dept}`}>
      <PageHeader eyebrow="Department workspace" title={`${title}`}
        meta={card.people.length ? `Assigned: ${card.people.join(", ")}${canEdit ? "" : " · you can read but not change this work"}`
          : "Nobody is assigned to this department yet"}
        actions={<span className="actions">
          <Link to={`/projects/${encodeURIComponent(projectId)}/team`} className="button secondary">Professional team</Link>
          <button type="button" className="secondary" aria-pressed={panel} onClick={() => setPanel(!panel)}>
            {panel ? "Hide context" : "Show context"}</button>
        </span>} />
      <SelectedRecord.Provider value={{ ...selected, set: (id, key) => setSelected({ id, key }) }}>
      <div className={panel ? "workspace-grid with-panel" : "workspace-grid"}>
        <nav className="workspace-nav" aria-label={`${title} modules`}>
          {modules.map((m) => (
            <button key={m.key} type="button" aria-current={m.key === current.key ? "page" : undefined}
              className={m.key === current.key ? "nav-link active" : m.screen === "later" ? "nav-link later" : "nav-link"}
              onClick={() => setParams({ m: m.key })}>
              {m.label}{m.screen === "later" && <span className="muted small"> · {m.step}</span>}
            </button>
          ))}
        </nav>
        <main className="workspace-main stack" aria-label={current.label}>
          <h2>{current.label}</h2>
          {current.screen === "overview" && <Overview card={card} projectId={projectId} department={department} />}
          {current.screen === "records" && (
            <Records key={current.key} projectId={projectId} department={department} kinds={current.kinds} all={kinds} />
          )}
          {current.screen === "steps" && <Steps projectId={projectId} department={department} />}
          {current.screen === "intake" && <Intake projectId={projectId} all={kinds} />}
          {current.screen === "analysis" && <MeetingAnalysis projectId={projectId} all={kinds} />}
          {current.screen === "kickoff" && <Kickoff projectId={projectId} all={kinds} />}
          {current.screen === "pm_tasks" && <PmTasks projectId={projectId} onOpen={(m) => setParams({ m })} />}
          {current.screen === "brief" && <ProjectBrief projectId={projectId} all={kinds} />}
          {current.screen === "ba_handoff" && <BaHandoff projectId={projectId} />}
          {current.screen === "scope" && <ScopeBoard projectId={projectId} department={department} />}
          {current.screen === "changes" && <ChangeRequests projectId={projectId} department={department} />}
          {current.screen === "packages" && <Packages projectId={projectId} department={department} canEdit={canEdit} />}
          {current.screen === "handoffs" && <Handoffs projectId={projectId} department={department} canEdit={canEdit} />}
          {current.screen === "traceability" && <Traceability projectId={projectId} />}
          {current.screen === "conversations" && chat && (scope.channels.some((c) => c.key === department)
            ? <TeamChat key={department} source={chat} tick={0} initial={department} label={`Message the ${title} team`} />
            : <p className="muted">This department's conversation is for its own team.</p>)}
          {current.screen === "later" && <Later label={current.label} step={current.step} what={current.what} />}
        </main>
        {panel && (
          <aside className="workspace-context stack" aria-label="Context">
            {card.visible
              ? <Assistant projectId={projectId} department={department} canEdit={canEdit} />
              : <p className="muted small">This department's assistant is for its own team.</p>}
            {card.visible && <DepartmentStatus projectId={projectId} profile={department} tick={0} />}
          </aside>
        )}
      </div>
      </SelectedRecord.Provider>
    </div>
  );
}

function Overview({ card, projectId, department }: { card: TeamCardDto; projectId: string; department: string }) {
  const w = card.work;
  return (
    <div className="stack">
      <ul className="stats" aria-label="Work in this department">
        <li><strong>{w.records}</strong> records</li>
        <li className={w.to_confirm ? "stat-pending" : ""}><strong>{w.to_confirm}</strong> AI suggestions or open questions to confirm</li>
        <li><strong>{w.in_review}</strong> in review</li>
        <li className={w.packages_awaiting_decision ? "stat-pending" : ""}><strong>{w.packages_awaiting_decision}</strong> packages awaiting a decision</li>
        <li className={w.incoming_handoffs ? "stat-pending" : ""}><strong>{w.incoming_handoffs}</strong> incoming handoffs</li>
        <li><strong>{w.approved}</strong> approved</li>
      </ul>
      {card.current && (
        <p>Current lifecycle step: <strong>{card.current.name}</strong>{card.current.note ? `. ${card.current.note}` : ""}</p>
      )}
      <p className="muted">Steps of the department lifecycle are worked on in Lifecycle steps. Steps of the standard
        lifecycle are still reviewed in the project's{" "}
        <Link to={`/projects/${encodeURIComponent(projectId)}?tab=Workspace&profile=${department}`}>step reviews</Link>.</p>
    </div>
  );
}
