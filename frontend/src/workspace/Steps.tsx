import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type DeliverableDto } from "../api";
import { EmptyState, IdentityTag, Skeleton, StatusPill } from "../components/ui";
import { STEP_LABELS } from "../portal/Collaboration";
import { ProvenanceTag } from "./Records";
import { type StepDto, workApi } from "./workApi";

const problem = (e: unknown) =>
  e instanceof ApiError ? [e.message, ...(e.problems ?? [])].join(" ") : "That did not work. Please try again.";
const ACTIVE = new Set(["READY", "RUNNING", "AI_COMPLETED", "VALIDATING", "CHANGES_REQUESTED"]);
const OWNER_ASK = "Please review this work and tell us anything you want changed, or say that you have no further "
  + "input. The professional gives the final approval after your answer.";

/** The department's lifecycle steps and what each one waits for. Every decision here goes through the server's gate. */
export function Steps({ projectId, department }: { projectId: string; department: string }) {
  const [steps, setSteps] = useState<StepDto[] | null>(null);
  const [deliverables, setDeliverables] = useState<Record<string, DeliverableDto>>({});
  const [canEdit, setCanEdit] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [targets, setTargets] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    Promise.all([workApi.steps(projectId, department), api.portalDeliverables(projectId).catch(() => ({ items: [] }))])
      .then(([s, d]) => {
        setSteps(s.items);
        setCanEdit(s.can_edit);
        setDeliverables(Object.fromEntries(d.items.map((x) => [x.stage, x])));
      })
      .catch((e: unknown) => setError(problem(e)));
  }, [projectId, department]);
  useEffect(load, [load]);
  // While the AI is working on a step, keep the list current (every 3 seconds) so people see when it is their turn.
  const working = (steps ?? []).some((st) => ACTIVE.has(st.status));
  useEffect(() => {
    if (!working) return undefined;
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [working, load]);

  if (error && !steps) return <p role="alert" className="error">{error}</p>;
  if (!steps) return <Skeleton />;
  if (steps.length === 0) {
    return <EmptyState title="This department has no lifecycle steps in this project yet.">Steps appear once the owner
      confirms the brief.</EmptyState>;
  }
  const act = async (work: () => Promise<unknown>, done: string) => {
    setError(null);
    setNotice(null);
    try { await work(); setNotice(done); load(); } catch (e) { setError(problem(e)); }
  };
  const name = (key: string) => steps.find((s) => s.key === key)?.name ?? key;

  return (
    <div className="stack">
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status" className="notice">{notice}</p>}
      <ol className="list steps" aria-label="Lifecycle steps">
        {steps.map((step) => {
          const [label, tone] = STEP_LABELS[step.status] ?? [step.status, "neutral"];
          const waiting = step.status === "AWAITING_HUMAN_REVIEW";
          const deliverable = deliverables[step.key];
          const suggestions = step.records.filter((r) => r.provenance === "ai_suggestion");
          return (
            <li key={step.key} className="panel stack-sm" aria-label={step.name}>
              <div className="row">
                <h3>{step.name}</h3>
                <span className="actions">{step.status === "RUNNING" && <IdentityTag kind="ai">working</IdentityTag>}
                  <StatusPill label={label} tone={tone} /></span>
              </div>
              {step.failure_reason && <p className="error small">{step.failure_reason}</p>}

              {step.kind === "records" && (
                <>
                  {step.records.length === 0
                    ? <p className="muted small">{step.status === "NOT_STARTED" || step.status === "READY"
                      ? "Not started yet." : "No records from this step."}</p>
                    : <ul className="list">{step.records.map((r) => (
                      <li key={r.id} className="row"><span><strong>{r.key}</strong> {r.title}</span><ProvenanceTag value={r.provenance} /></li>
                    ))}</ul>}
                  {waiting && canEdit && (
                    <div className="actions">
                      {suggestions.length > 0 && (
                        <button type="button" className="secondary" onClick={() => act(async () => {
                          for (const r of suggestions) {
                            await workApi.edit(projectId, r.id, { expected_version: r.version, provenance: "confirmed",
                              reason: "confirmed as written by a professional" });
                          }
                        }, `${suggestions.length} suggestion(s) confirmed as written.`)}>
                          Confirm {suggestions.length} suggestion{suggestions.length === 1 ? "" : "s"} as written</button>
                      )}
                      <button type="button" disabled={suggestions.length > 0}
                        title={suggestions.length > 0 ? "Confirm, edit or archive the AI suggestions first" : undefined}
                        onClick={() => act(() => workApi.submit(projectId, department, step.name, step.records.map((r) => r.id),
                          "", step.key), "Package submitted. Decide on it in Reviews & Approvals.")}>Submit step package</button>
                    </div>
                  )}
                  {waiting && suggestions.length > 0 && <p className="muted small">Review each suggestion in its module
                    (edit, confirm or archive). Confirming as written is a decision you are recorded as making.</p>}
                </>
              )}

              {step.kind === "review" && deliverable && (() => {
                const current = deliverable.versions.find((v) => v.id === deliverable.current_version_id) ?? deliverable.versions[0];
                const docs = ((current?.content ?? {}) as { documents?: { key: string; title: string; version: number;
                  kept_professional_edits: boolean }[] }).documents ?? [];
                return docs.length > 0 && (
                  <div className="stack-sm">
                    <p className="small"><strong>Documents in this review</strong> (assembled by the platform from the approved
                      records; open them in BRD / SRS Documents to read, edit or confirm):</p>
                    <ul className="list small">{docs.map((d) => (
                      <li key={d.key}><strong>{d.key}</strong> v{d.version} {d.title}
                        {d.kept_professional_edits ? " · your edited version, kept" : ""}</li>
                    ))}</ul>
                  </div>
                );
              })()}
              {(step.kind === "review" || step.kind === "owner_input") && deliverable && (
                <details>
                  <summary>What is in this step ({deliverable.versions.length} version{deliverable.versions.length === 1 ? "" : "s"})</summary>
                  <ul className="list small">
                    {((((deliverable.versions.find((v) => v.id === deliverable.current_version_id) ?? deliverable.versions[0])?.content ?? {}) as { package?: { name: string; content: string }[] })
                      .package ?? []).map((p, i) => <li key={i}><strong>{p.name}</strong>: {String(p.content).slice(0, 400)}</li>)}
                  </ul>
                </details>
              )}

              {step.kind === "owner_input" && step.owner && (
                <div className="stack-sm">
                  {!step.owner.asked && <p className="muted small">The owner has not been asked yet.</p>}
                  {step.owner.asked && !step.owner.answer && <p className="small">Waiting for the owner's input.</p>}
                  {step.owner.answer && <p className="notice small"><strong>The owner said:</strong> {step.owner.answer}</p>}
                  {waiting && canEdit && !step.owner.answered && (
                    <button type="button" onClick={() => act(() => api.askOwner(projectId, step.key, OWNER_ASK),
                      "The owner has been asked for their input.")}>Ask the owner for input</button>
                  )}
                </div>
              )}

              {(step.kind === "review" || step.kind === "owner_input") && waiting && canEdit && deliverable && (
                <div className="stack-sm">
                  <div className="actions">
                    <button type="button" disabled={step.kind === "owner_input" && !step.owner?.answered}
                      title={step.kind === "owner_input" && !step.owner?.answered ? "The owner answers first" : undefined}
                      onClick={() => act(() => api.portalDecide(projectId, step.key, deliverable.current_version_id, "APPROVE", "",
                        crypto.randomUUID()), `${step.name} approved.`)}>Approve {step.kind === "owner_input" ? "(final)" : ""}</button>
                  </div>
                  {step.send_back_to.length > 0 && (
                    <div className="actions">
                      <label>Send back<select value={targets[step.key] ?? ""}
                        onChange={(e) => setTargets({ ...targets, [step.key]: e.target.value })}>
                        <option value="">Choose a step</option>
                        {step.send_back_to.map((k) => <option key={k} value={k}>{name(k)}</option>)}
                      </select></label>
                      <label className="grow">What needs to change<input value={notes[step.key] ?? ""}
                        onChange={(e) => setNotes({ ...notes, [step.key]: e.target.value })} /></label>
                      <button type="button" className="secondary" disabled={!targets[step.key] || !(notes[step.key] ?? "").trim()}
                        onClick={() => act(() => workApi.sendBack(projectId, step.key, targets[step.key], notes[step.key]),
                          `${name(targets[step.key])} was sent back for rework.`)}>Send back</button>
                    </div>
                  )}
                </div>
              )}

              {step.change_requests.length > 0 && (
                <details>
                  <summary>Change requests ({step.change_requests.filter((c) => c.status === "open").length} open)</summary>
                  <ul className="list small">{step.change_requests.map((c, i) => (
                    <li key={i}>{c.comment} <span className="muted">· {c.status} · {new Date(c.at).toLocaleString()}</span></li>
                  ))}</ul>
                </details>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
