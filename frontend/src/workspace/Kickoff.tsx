import { type FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError } from "../api";
import { Skeleton } from "../components/ui";
import { RecordDetail } from "./Records";
import { type KickoffDto, type KindDto, workApi } from "./workApi";

const problem = (e: unknown) => (e instanceof ApiError ? [e.message, ...e.problems].join(" · ")
  : "That did not work. Please try again.");
const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

/** The project kickoff: the platform's checklist (PM, client, kind of work, and the team that kind of work needs),
 * the kickoff record, and the kind of work, which the PM may change with the client until the client approves
 * the brief. The brief can only be assembled after the kickoff. */
export function Kickoff({ projectId, all }: { projectId: string; all: KindDto[] }) {
  const [data, setData] = useState<KickoffDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ held_at: "", attendees: "", agenda: "", notes: "", communication: "" });
  const [scope, setScope] = useState("");
  const [reason, setReason] = useState("");
  const load = useCallback(() => {
    workApi.kickoff(projectId).then((d) => { setData(d); setScope(d.scope ?? ""); }).catch((e: unknown) => setError(problem(e)));
  }, [projectId]);
  useEffect(load, [load]);
  if (error && !data) return <p role="alert" className="error">{error}</p>;
  if (!data) return <Skeleton />;

  async function hold(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await workApi.holdKickoff(projectId, { held_at: form.held_at, attendees: lines(form.attendees),
        agenda: lines(form.agenda), notes: form.notes, communication: form.communication });
      load();
    } catch (err) { setError(problem(err)); }
  }

  return (
    <div className="stack">
      <p className="muted">The kickoff starts the project with the client. The platform checks the team is in place for
        the kind of work; the project brief can only be assembled after the kickoff.</p>
      {error && <p role="alert" className="error">{error}</p>}
      <section className="panel stack-sm" aria-label="Kickoff checklist">
        <h3>Checklist</h3>
        <ul className="list">
          {data.checklist.map((c) => (
            <li key={c.key}><span aria-hidden="true">{c.ok ? "✓" : "✗"}</span> {c.label}
              {!c.ok && <span className="muted small"> · ask an administrator to assign one in Team</span>}</li>
          ))}
        </ul>
      </section>
      <section className="stack-sm" aria-label="Kind of work">
        <h3>Kind of work</h3>
        {data.scope_locked
          ? <p>{data.scopes.find((s) => s.key === data.scope)?.label} <span className="muted small">· locked: the client approved the brief</span></p>
          : (
            <div className="stack-sm">
              <label>Kind of work
                <select value={scope} disabled={!data.can_edit} onChange={(e) => setScope(e.target.value)}>
                  {data.scopes.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
              </label>
              {data.can_edit && scope !== data.scope && (
                <div className="actions">
                  <label className="grow">Why it changes (agreed with the client)<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
                  <button type="button" disabled={!reason.trim()} onClick={async () => {
                    setError(null);
                    try { setData(await workApi.changeScope(projectId, scope, reason)); setReason(""); }
                    catch (err) { setError(problem(err)); }
                  }}>Change the kind of work</button>
                </div>
              )}
            </div>
          )}
      </section>
      {data.kickoff
        ? <RecordDetail projectId={projectId} itemId={data.kickoff.id} kinds={all} onChange={load} />
        : data.can_edit && (
          <form className="panel stack-sm" aria-label="Hold the kickoff" onSubmit={(e) => void hold(e)}>
            <h3>Hold the kickoff</h3>
            <label>When (required)<input required value={form.held_at} placeholder="2026-11-25 10:00"
              onChange={(e) => setForm({ ...form, held_at: e.target.value })} /></label>
            <label>Attendees (one per line)<textarea rows={3} value={form.attendees} onChange={(e) => setForm({ ...form, attendees: e.target.value })} /></label>
            <label>Agenda (one per line)<textarea rows={3} value={form.agenda} onChange={(e) => setForm({ ...form, agenda: e.target.value })} /></label>
            <label>How everyone keeps in touch<input value={form.communication} onChange={(e) => setForm({ ...form, communication: e.target.value })} /></label>
            <label>Notes<textarea rows={4} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
            <button type="submit" disabled={!data.ready || !form.held_at.trim()}>Record the kickoff</button>
            {!data.ready && <p className="muted small">The checklist must pass first.</p>}
          </form>
        )}
    </div>
  );
}
