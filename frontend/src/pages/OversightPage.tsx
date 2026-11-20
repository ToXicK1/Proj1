import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type OversightDto } from "../api";
import { Avatar, EmptyState, LiveIndicator, PageHeader, Skeleton, StatusPill, type Tone } from "../components/ui";
import { STEP_LABELS } from "../portal/Collaboration";

/** For administrators and project managers: what is happening on every project and who it waits on. */
export function OversightPage() {
  const [data, setData] = useState<OversightDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [updated, setUpdated] = useState<Date | null>(null);
  useEffect(() => {
    api.oversight().then((d) => { setData(d); setError(null); setUpdated(new Date()); })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not load the oversight view."));
  }, [tick]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (!document.hidden) setTick((n) => n + 1); }, 10000);
    return () => window.clearInterval(timer);
  }, []);

  if (error) return <section className="page"><h1>Oversight</h1><p role="alert" className="error">{error}</p></section>;
  if (!data) return <section className="page"><h1>Oversight</h1><Skeleton /></section>;
  const t = data.totals;
  return (
    <div className="page">
      <PageHeader eyebrow={data.role} title="Oversight" actions={<LiveIndicator updated={updated} />}
        meta="Every project, who is working on what, and what is waiting on whom. Only the assigned professional can approve their department's work; follow up with them in Team chat or Messages." />
      <ul className="stats" aria-label="Totals">
        <li><strong>{t.projects}</strong> projects</li>
        <li className={t.approvals ? "stat-pending" : ""}><strong>{t.approvals}</strong> waiting for approval</li>
        <li className={t.working ? "stat-progress" : ""}><strong>{t.working}</strong> AI tasks in progress</li>
        <li className={t.issues ? "stat-blocked" : ""}><strong>{t.issues}</strong> need attention</li>
        <li><strong>{t.open_tickets}</strong> open tickets</li>
      </ul>
      {data.projects.length === 0 && <EmptyState title="There are no projects yet." />}
      {data.projects.map((p) => (
        <section key={p.id} className="panel stack" aria-label={`Project ${p.name}`}>
          <div className="panel-head">
            <div className="project-title">
              <span className="project-mark lg" aria-hidden="true">{p.name.trim()[0]?.toUpperCase() ?? "P"}</span>
              <div>
                <h2><Link to={`/projects/${p.id}`}>{p.name}</Link></h2>
                <p className="muted small">Owner: {p.owners.join(", ") || "none"} · {p.open_tickets} open ticket{p.open_tickets === 1 ? "" : "s"}</p>
              </div>
            </div>
            {!p.started && <StatusPill label="Not started" tone="neutral" />}
          </div>
          {p.issues.length > 0 && (
            <div className="stack-sm">
              <h3>Needs attention</h3>
              <ul className="issues">{p.issues.map((i, n) => <li key={n} className={`issue issue-${i.kind}`}><strong>{i.department}:</strong> {i.text}</li>)}</ul>
            </div>
          )}
          {p.approvals.length > 0 && (
            <div className="stack-sm">
              <h3>Waiting for approval</h3>
              <ul className="rows">{p.approvals.map((a, n) => (
                <li key={n} className="row-item"><span className="row-main"><strong>{a.step}</strong><span className="muted">{a.department}</span></span>
                  <span className="person"><Avatar name={a.who} size="sm" />Waiting on {a.who}</span></li>
              ))}</ul>
            </div>
          )}
          {p.working.length > 0 && (
            <div className="stack-sm">
              <h3>AI working now</h3>
              <ul className="rows">{p.working.map((w, n) => (
                <li key={n} className="row-item"><span className="row-main"><strong>{w.step}</strong><span className="muted">{w.department}</span></span>
                  <span>{w.slow && <StatusPill label="Slow" tone="warning" />} {w.note}</span></li>
              ))}</ul>
            </div>
          )}
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Who is doing what on {p.name}</caption>
              <thead><tr><th scope="col">Department</th><th scope="col">People</th><th scope="col">Now</th><th scope="col">Progress</th></tr></thead>
              <tbody>
                {p.departments.map((d) => {
                  const [label, tone]: [string, Tone] = d.current ? STEP_LABELS[d.current.status] ?? [d.current.status, "neutral"] : ["All done", "success"];
                  return (
                    <tr key={d.profile}>
                      <th scope="row">{d.title}</th>
                      <td>{d.people.join(", ") || <span className="muted">Nobody assigned</span>}</td>
                      <td>{d.steps === 0 ? <span className="muted">No steps in this lifecycle</span>
                        : <>{d.current?.name ?? ""} <StatusPill label={label} tone={tone} /></>}</td>
                      <td>{d.done} of {d.steps}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
