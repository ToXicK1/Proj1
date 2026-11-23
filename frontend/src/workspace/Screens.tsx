import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api";
import { EmptyState, Skeleton } from "../components/ui";
import { PROFILES } from "../portal/roles";
import { ItemStatus } from "./Records";
import { type HandoffDto, type PackageDto, workApi } from "./workApi";

const problem = (e: unknown) =>
  e instanceof ApiError ? [e.message, ...(e.problems ?? [])].join(" ") : "That did not work. Please try again.";
const titleOf = (profile: string) => PROFILES.find(([k]) => k === profile)?.[1] ?? profile;

/** A module the brief asks for that is not built yet. It says so, and when it comes. */
export function Later({ label, step, what }: { label: string; step: string; what: string }) {
  return (
    <EmptyState title={`${label} is not available yet`}>
      This module arrives in step {step}: {what}. Nothing here is simulated in the meantime.
    </EmptyState>
  );
}

/** Packages submitted for review, and the department's decision on each exact set of versions. */
export function Packages({ projectId, department, canEdit }: { projectId: string; department: string; canEdit: boolean }) {
  const [items, setItems] = useState<PackageDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [handTo, setHandTo] = useState<Record<string, string>>({});
  const load = useCallback(() => {
    workApi.packages(projectId, department).then((r) => setItems(r.items)).catch((e: unknown) => setError(problem(e)));
  }, [projectId, department]);
  useEffect(load, [load]);
  if (error && !items) return <p role="alert" className="error">{error}</p>;
  if (!items) return <Skeleton />;
  const act = async (work: () => Promise<unknown>) => {
    setError(null);
    try { await work(); load(); } catch (e) { setError(problem(e)); }
  };
  return (
    <div className="stack">
      <p className="muted">A package freezes the exact versions of the records in it. Only this department's assigned
        professionals decide on it; the AI never does. Editing a record afterwards does not change what was decided.
        The lifecycle's own approval steps stay in the project's Deliverables until step 7.1 joins them here.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {items.length === 0 && <EmptyState title="No packages yet.">Select records in a module and submit them for review.</EmptyState>}
      {items.map((p) => (
        <section key={p.id} className="panel stack-sm" aria-label={`Package ${p.number}`}>
          <div className="row">
            <h3>Package {p.number}: {p.title}</h3>
            <ItemStatus value={p.status} />
          </div>
          <p className="muted small">Submitted by {p.submitted_by} on {new Date(p.submitted_at).toLocaleString()}
            {p.decided_by ? ` · decided by ${p.decided_by} on ${new Date(p.decided_at ?? "").toLocaleString()}` : ""}
            {" · fingerprint "}<code>{p.sha256.slice(0, 12)}</code></p>
          <ul className="list">{p.items.map((i) => <li key={i.version_id}><strong>{i.key}</strong> v{i.number} {i.title}</li>)}</ul>
          {p.decision_note && <p>Note: {p.decision_note}</p>}
          {canEdit && p.status === "submitted" && (
            <div className="actions">
              <label className="grow">Decision note<input value={notes[p.id] ?? ""}
                onChange={(e) => setNotes({ ...notes, [p.id]: e.target.value })} /></label>
              <button type="button" onClick={() => act(() => workApi.decide(projectId, p.id, "approve", notes[p.id] ?? ""))}>Approve</button>
              <button type="button" className="secondary" disabled={!(notes[p.id] ?? "").trim()}
                onClick={() => act(() => workApi.decide(projectId, p.id, "request_changes", notes[p.id] ?? ""))}>Request changes</button>
            </div>
          )}
          {canEdit && p.status === "approved" && (
            <div className="actions">
              <label>Hand off to<select value={handTo[p.id] ?? ""} onChange={(e) => setHandTo({ ...handTo, [p.id]: e.target.value })}>
                <option value="">Choose a department</option>
                {PROFILES.filter(([k]) => k !== department).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
              <button type="button" disabled={!handTo[p.id]}
                onClick={() => act(() => workApi.handOff(projectId, p.id, handTo[p.id], notes[p.id] ?? ""))}>Send handoff</button>
            </div>
          )}
        </section>
      ))}
    </div>
  );
}

/** Handoffs sent and received. Acknowledging or asking for clarification never changes workflow state. */
export function Handoffs({ projectId, department, canEdit }: { projectId: string; department: string; canEdit: boolean }) {
  const [items, setItems] = useState<HandoffDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState<Record<string, string>>({});
  const load = useCallback(() => {
    workApi.handoffs(projectId, department).then((r) => setItems(r.items)).catch((e: unknown) => setError(problem(e)));
  }, [projectId, department]);
  useEffect(load, [load]);
  if (error && !items) return <p role="alert" className="error">{error}</p>;
  if (!items) return <Skeleton />;
  const act = async (work: () => Promise<unknown>) => {
    setError(null);
    try { await work(); load(); } catch (e) { setError(problem(e)); }
  };
  return (
    <div className="stack">
      {error && <p role="alert" className="error">{error}</p>}
      {items.length === 0 && <EmptyState title="No handoffs yet.">Approved packages are handed between departments here.</EmptyState>}
      {items.map((h) => {
        const incoming = h.to === department;
        return (
          <section key={h.id} className="panel stack-sm" aria-label={`Handoff ${h.package.title}`}>
            <div className="row">
              <h3>{incoming ? `From ${titleOf(h.from)}` : `To ${titleOf(h.to)}`}: {h.package.title}</h3>
              <ItemStatus value={h.status} />
            </div>
            <p className="muted small">Sent by {h.sender} on {new Date(h.sent_at).toLocaleString()} · package {h.package.number},
              fingerprint <code>{h.package.sha256.slice(0, 12)}</code></p>
            {h.note && <p>{h.note}</p>}
            <ul className="list">{h.package.items.map((i) => <li key={i.version_id}><strong>{i.key}</strong> v{i.number} {i.title}</li>)}</ul>
            {h.reply && <p><strong>{h.replied_by}:</strong> {h.reply}</p>}
            {incoming && canEdit && h.status === "sent" && (
              <div className="actions">
                <label className="grow">Reply<input value={reply[h.id] ?? ""} onChange={(e) => setReply({ ...reply, [h.id]: e.target.value })} /></label>
                <button type="button" onClick={() => act(() => workApi.reply(projectId, h.id, "acknowledge", reply[h.id] ?? ""))}>Acknowledge</button>
                <button type="button" className="secondary" disabled={!(reply[h.id] ?? "").trim()}
                  onClick={() => act(() => workApi.reply(projectId, h.id, "request_clarification", reply[h.id] ?? ""))}>Ask for clarification</button>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

const CHAIN = ["requirement", "user_story"];

/** Which records link to which, and which are not covered by anything downstream yet. */
export function Traceability({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof workApi.traceability>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { workApi.traceability(projectId).then(setData).catch((e: unknown) => setError(problem(e))); }, [projectId]);
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!data) return <Skeleton />;
  const byId = Object.fromEntries(data.items.map((i) => [i.id, i]));
  const into = (id: string) => data.links.filter((l) => l.to === id).map((l) => byId[l.from]).filter(Boolean);
  const requirements = data.items.filter((i) => i.kind === CHAIN[0]);
  return (
    <div className="stack">
      <p className="muted">Each requirement and what traces back to it. Architecture, design, development tasks and test
        cases join this matrix as their departments are built (steps 7.2 to 7.4).</p>
      {requirements.length === 0 ? <EmptyState title="No requirements to trace yet." /> : (
        <div className="table-wrap">
          <table aria-label="Traceability matrix">
            <thead><tr><th>Requirement</th><th>Linked records</th><th>Coverage</th></tr></thead>
            <tbody>
              {requirements.map((r) => {
                const linked = into(r.id);
                return (
                  <tr key={r.id}>
                    <td><strong>{r.key}</strong> {r.title}</td>
                    <td>{linked.length ? linked.map((l) => `${l.key} ${l.title}`).join("; ") : "—"}</td>
                    <td>{linked.some((l) => l.kind === CHAIN[1]) ? "Has user stories" : <strong className="error">No user story yet</strong>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
