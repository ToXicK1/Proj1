import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api";
import { EmptyState, Skeleton } from "../components/ui";
import { ProvenanceTag } from "./Records";
import { type ItemDto, type StepDto, workApi } from "./workApi";

const problem = (e: unknown) => (e instanceof ApiError ? e.message : "That did not work. Please try again.");
const COLUMNS: [string, string][] = [["must", "Must have"], ["should", "Should have"], ["could", "Could have"],
  ["wont", "Won't have (this time)"], ["", "Not prioritized"]];

/** Requirements and user stories by priority (MoSCoW). Moving one saves a new version with the reason. */
export function ScopeBoard({ projectId, department }: { projectId: string; department: string }) {
  const [items, setItems] = useState<ItemDto[] | null>(null);
  const [canEdit, setCanEdit] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    Promise.all([workApi.items(projectId, department, { kind: "requirement" }),
      workApi.items(projectId, department, { kind: "user_story" })])
      .then(([r, s]) => { setItems([...r.items, ...s.items]); setCanEdit(r.can_edit); })
      .catch((e: unknown) => setError(problem(e)));
  }, [projectId, department]);
  useEffect(load, [load]);
  if (error && !items) return <p role="alert" className="error">{error}</p>;
  if (!items) return <Skeleton />;
  if (items.length === 0) return <EmptyState title="No requirements or user stories yet." />;
  return (
    <div className="stack">
      {error && <p role="alert" className="error">{error}</p>}
      <p className="muted">Changing a priority here saves a new version of that record, with the reason, and it then
        needs a new package before it counts as approved again.</p>
      <div className="scope-board">
        {COLUMNS.map(([key, label]) => {
          const here = items.filter((i) => ((i.body.priority as string | undefined) ?? "") === key);
          return (
            <section key={key || "none"} className="panel stack-sm" aria-label={label}>
              <h3>{label} <span className="muted small">({here.length})</span></h3>
              <ul className="list">
                {here.map((i) => (
                  <li key={i.id} className="stack-sm">
                    <span><strong>{i.key}</strong> {i.title}</span>
                    <span className="actions"><ProvenanceTag value={i.provenance} />
                      {canEdit && i.status !== "archived" && (
                        <label className="sr-only-label">Priority of {i.key}
                          <select value={(i.body.priority as string | undefined) ?? ""} onChange={async (e) => {
                            setError(null);
                            const body = { ...i.body };
                            if (e.target.value) body.priority = e.target.value; else delete body.priority;
                            try {
                              await workApi.edit(projectId, i.id, { expected_version: i.latest_version, body,
                                reason: `priority set to ${e.target.value || "none"} on the scope board` });
                              load();
                            } catch (err) { setError(problem(err)); }
                          }}>
                            {COLUMNS.map(([k, l]) => <option key={k || "none"} value={k}>{l}</option>)}
                          </select>
                        </label>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}

/** Every change request on the department's steps: from the professional, the owner's answers and send-backs. */
export function ChangeRequests({ projectId, department }: { projectId: string; department: string }) {
  const [steps, setSteps] = useState<StepDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    workApi.steps(projectId, department).then((r) => setSteps(r.items)).catch((e: unknown) => setError(problem(e)));
  }, [projectId, department]);
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!steps) return <Skeleton />;
  const rows = steps.flatMap((s) => s.change_requests.map((c) => ({ ...c, step: s.name })))
    .sort((a, b) => b.at.localeCompare(a.at));
  if (rows.length === 0) return <EmptyState title="No change requests yet.">Requests to change a step's work appear
    here, with whether the AI's next version resolved them.</EmptyState>;
  return (
    <div className="table-wrap">
      <table aria-label="Change requests">
        <thead><tr><th>Step</th><th>Request</th><th>Status</th><th>When</th></tr></thead>
        <tbody>{rows.map((r, i) => (
          <tr key={i}><td>{r.step}</td><td className="prewrap">{r.comment}</td><td>{r.status}</td>
            <td>{new Date(r.at).toLocaleString()}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}
