import { useEffect, useState } from "react";
import { ApiError } from "../api";
import { EmptyState, Skeleton } from "../components/ui";
import { type PmTasksDto, workApi } from "./workApi";

const TABS = ["My to-dos", "Department work", "Assigned tasks"] as const;
const problem = (e: unknown) => (e instanceof ApiError ? e.message : "That did not work. Please try again.");

/** The PM's Tasks page: what waits on the PM, every department's lifecycle work, and (P6) assigned tasks. Read-only;
 * each to-do opens the module where it is done. */
export function PmTasks({ projectId, onOpen }: { projectId: string; onOpen: (module: string) => void }) {
  const [data, setData] = useState<PmTasksDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("My to-dos");
  useEffect(() => { workApi.pmTasks(projectId).then(setData).catch((e: unknown) => setError(problem(e))); }, [projectId]);
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!data) return <Skeleton />;
  const work = data.departments;
  return (
    <div className="stack">
      <div className="tabs" role="tablist" aria-label="Tasks">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? "tab selected" : "tab"}
            onClick={() => setTab(t)}>{t}{t === "My to-dos" && data.todos.length > 0 ? ` (${data.todos.length})` : ""}</button>
        ))}
      </div>
      {tab === "My to-dos" && (data.todos.length === 0
        ? <EmptyState title="Nothing is waiting on you.">New client input, approvals and clarifications show up here.</EmptyState>
        : (
          <ul className="list" aria-label="My to-dos">
            {data.todos.map((t, i) => (
              <li key={`${t.kind}-${i}`} className="row">
                <span>{t.urgent && <strong>Now: </strong>}{t.text}</span>
                <button type="button" className="secondary" onClick={() => onOpen(t.module)}>Open</button>
              </li>
            ))}
          </ul>
        ))}
      {tab === "Department work" && (!work.started
        ? <EmptyState title="Delivery has not started.">Department steps appear once you hand the approved brief to the Business Analyst.</EmptyState>
        : (
          <div className="stack-sm">
            {work.attention.length > 0 && (
              <section className="notice" aria-label="Needs attention">
                <strong>Needs attention</strong>
                <ul>{work.attention.map((a) => <li key={a}>{a}</li>)}</ul>
              </section>
            )}
            <div className="table-wrap">
              <table aria-label="Department work">
                <thead><tr><th>Department</th><th>Step</th><th>Status</th><th>Approver</th><th>Note</th></tr></thead>
                <tbody>
                  {work.steps.map((s) => (
                    <tr key={s.stage}>
                      <td>{s.department_title}</td><td>{s.number} {s.name}</td><td>{s.status}</td>
                      <td>{s.people.join(", ") || <span className="muted">nobody assigned</span>}</td>
                      <td>{s.note ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small">You oversee this work; each department's professionals approve their own steps.</p>
          </div>
        ))}
      {tab === "Assigned tasks" && (
        <EmptyState title="Assigned tasks arrive in step P6.">
          You will create department tasks here with owners, priorities and due dates.
        </EmptyState>
      )}
    </div>
  );
}
