import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api";
import { EmptyState, IdentityTag, Skeleton } from "../components/ui";
import { Records } from "./Records";
import { type AssistantExchangeDto, type ItemDto, type KindDto, workApi } from "./workApi";

const problem = (e: unknown) => (e instanceof ApiError ? e.message : "That did not work. Please try again.");

/** AI Meeting Analysis (P3): the PM asks the AI persona to analyse a meeting. Each analysis is a provisional
 * record linked to its meeting; nothing counts until the PM confirms it, and the meeting and intake are never edited. */
export function MeetingAnalysis({ projectId, all }: { projectId: string; all: KindDto[] }) {
  const [meetings, setMeetings] = useState<ItemDto[] | null>(null);
  const [canEdit, setCanEdit] = useState(false);
  const [latest, setLatest] = useState<Record<string, AssistantExchangeDto | undefined>>({});
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const load = useCallback(() => {
    workApi.items(projectId, "project_manager", { kind: "meeting" }).then(async (r) => {
      setMeetings(r.items);
      setCanEdit(r.can_edit);
      const runs = await Promise.all(r.items.map((m) => workApi.analyses(projectId, m.id).catch(() => ({ items: [] }))));
      setLatest(Object.fromEntries(r.items.map((m, i) => [m.id, runs[i].items[0]])));
    }).catch((e: unknown) => setError(problem(e)));
  }, [projectId]);
  useEffect(load, [load, tick]);
  const pending = Object.values(latest).some((x) => x?.status === "pending");
  useEffect(() => {
    if (!pending) return undefined;
    const timer = window.setInterval(() => setTick((t) => t + 1), 3000);
    return () => window.clearInterval(timer);
  }, [pending]);

  if (error && !meetings) return <p role="alert" className="error">{error}</p>;
  if (!meetings) return <Skeleton />;
  return (
    <div className="stack">
      <p className="muted">The PM assistant reads a meeting's notes, earlier meetings, your intake and the client's
        pre-meeting answers, and drafts an analysis: objectives, features, stakeholders, decisions, assumptions,
        risks, missing information, contradictions and follow-up questions. It is a suggestion until you confirm it.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {meetings.length === 0
        ? <EmptyState title="No meetings yet.">Record a meeting in Client Meetings first.</EmptyState>
        : (
          <ul className="list" aria-label="Meetings to analyse">
            {meetings.map((m) => {
              const run = latest[m.id];
              return (
                <li key={m.id} className="row">
                  <span><strong>{m.key}</strong> {m.title}
                    {run?.status === "pending" && <> · <IdentityTag kind="ai">analysing…</IdentityTag></>}
                    {run?.status === "answered" && <span className="muted"> · analysed as {run.proposals[0]?.added}</span>}
                    {run?.status === "failed" && <span className="error"> · the analysis failed: {run.failure}</span>}
                  </span>
                  {canEdit && (
                    <button type="button" className="secondary" disabled={run?.status === "pending"} onClick={async () => {
                      setError(null);
                      try { await workApi.analyse(projectId, m.id); setTick((t) => t + 1); }
                      catch (e) { setError(problem(e)); }
                    }}>Analyze with AI</button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      <h3>Analyses</h3>
      <Records key={tick} projectId={projectId} department="project_manager" kinds={["meeting_analysis"]} all={all} />
    </div>
  );
}
