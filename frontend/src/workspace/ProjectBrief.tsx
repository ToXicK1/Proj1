import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api";
import { EmptyState, Skeleton } from "../components/ui";
import { Records } from "./Records";
import { Handoffs, Packages } from "./Screens";
import { type BriefStatusDto, type KindDto, workApi } from "./workApi";

const PM = "project_manager";
const problem = (e: unknown) => (e instanceof ApiError ? e.message : "That did not work. Please try again.");

function useBrief(projectId: string) {
  const [status, setStatus] = useState<BriefStatusDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    workApi.brief(projectId).then(setStatus).catch((e: unknown) => setError(problem(e)));
  }, [projectId]);
  useEffect(load, [load]);
  return { status, error, setError, load };
}

/** P4: the Project Brief. The platform assembles it from the validated intake and the confirmed meetings (no AI);
 * the PM confirms or edits it, submits it and approves it. A brief with the PM's own edits needs a second PM. */
export function ProjectBrief({ projectId, all }: { projectId: string; all: KindDto[] }) {
  const { status, error, setError, load } = useBrief(projectId);
  const [tick, setTick] = useState(0);
  const [packagesTick, setPackagesTick] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  if (error && !status) return <p role="alert" className="error">{error}</p>;
  if (!status) return <Skeleton />;
  const canAssemble = status.is_project_manager && status.kickoff_held && status.intake_validated && !status.started;
  const withClient = status.approved_packages[0];
  return (
    <div className="stack">
      <p className="muted">The brief is assembled by the platform from your validated intake and the confirmed client
        meetings. Every line names its record and version. Confirm it as written, or edit it, then submit it for
        approval. Only an approved brief can be handed to the Business Analyst.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {note && <p role="status" className="notice small">{note}</p>}
      {!status.kickoff_held && <p className="muted">Hold the project kickoff first (Kickoff).</p>}
      {!status.intake_validated && <p className="muted">Validate the project intake first (Project Intake).</p>}
      {withClient?.client_status === "awaiting" && <p className="notice small">Package {withClient.number} is with the client for approval.</p>}
      {withClient?.client_status === "changes_requested" && (
        <p className="notice small">The client asked for changes: “{withClient.client_note}”. Revise the brief (or update the
          intake and re-assemble it), then submit and approve it again.</p>
      )}
      {withClient?.client_status === "approved" && <p className="small">The client approved package {withClient.number}. Hand it to the
        Business Analyst in BA Handoff.</p>}
      {status.started
        ? <p className="small">Delivery has started from the approved brief. Changes now go through change requests.</p>
        : status.is_project_manager && (
          <div className="actions">
            <button type="button" disabled={!canAssemble} onClick={async () => {
              setError(null); setNote(null);
              try {
                const r = await workApi.assembleBrief(projectId);
                setNote(r.kept_pm_edits
                  ? `${r.item.key} keeps your edits; it was not re-assembled. The intake or meetings may have changed since.`
                  : `${r.item.key} v${r.item.version} is assembled. Confirm or edit it, then submit it.`);
                setTick((t) => t + 1); load();
              } catch (e) { setError(problem(e)); }
            }}>{status.brief ? "Re-assemble the brief" : "Assemble the brief"}</button>
          </div>
        )}
      {status.edited_by_pm && !status.started && (
        <p className="notice small">This brief contains your own edits, so another Project Manager must approve it.</p>
      )}
      <Records key={tick} projectId={projectId} department={PM} kinds={["project_brief"]} all={all}
        onSubmitted={() => { setPackagesTick((t) => t + 1); load(); }} />
      <h3>Approval</h3>
      <Packages key={`p${tick}-${packagesTick}`} projectId={projectId} department={PM} canEdit={status.is_project_manager} />
    </div>
  );
}

const CLIENT_STATUS: Record<string, string> = {
  awaiting: "with the client for approval", approved: "approved by the client",
  changes_requested: "the client asked for changes", withdrawn: "withdrawn (the kind of work changed)",
};

/** The PM (or an administrator, with a reason, when the PM is not available) hands the client-approved brief to the
 * Business Analyst department; that starts delivery with the project's kind of work. The BA asks for clarification
 * on the handoff, and the PM answers through the PM's handoffs. */
export function BaHandoff({ projectId }: { projectId: string }) {
  const { status, error, setError, load } = useBrief(projectId);
  const [packageId, setPackageId] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  if (error && !status) return <p role="alert" className="error">{error}</p>;
  if (!status) return <Skeleton />;
  const ready = status.approved_packages.filter((p) => p.client_status === "approved");
  const chosen = packageId || ready[0]?.id || "";
  const forPm = !status.is_project_manager && status.is_admin;
  const canStart = status.is_project_manager || status.is_admin;
  return (
    <div className="stack">
      <p className="muted">Handing the client-approved brief to the Business Analyst starts delivery, with the project's
        kind of work. The BA's AI steps work from the exact approved version of the brief.</p>
      <p><strong>Kind of work:</strong> {status.kind_of_work ?? "not chosen"}</p>
      {error && <p role="alert" className="error">{error}</p>}
      {status.approved_packages.length > 0 && (
        <ul className="list" aria-label="Approved briefs">
          {status.approved_packages.map((p) => (
            <li key={p.id}>Package {p.number}: {p.brief.key} v{p.brief.number} · {CLIENT_STATUS[p.client_status ?? ""] ?? "approved by you"}
              {p.client_status === "changes_requested" && p.client_note && <span className="muted"> · “{p.client_note}”</span>}</li>
          ))}
        </ul>
      )}
      {status.team_gaps.length > 0 && !status.started && (
        <p className="notice small">Before delivery can start: {status.team_gaps.join("; ")}.</p>
      )}
      {status.started
        ? <p role="status" className="small"><strong>Delivery has started</strong> from the approved brief.</p>
        : ready.length === 0
          ? <EmptyState title="No client-approved brief yet.">Approve the brief in Project Brief; the client then approves it in their portal.</EmptyState>
          : canStart && (
            <form className="stack-sm" aria-label="Hand the brief to the Business Analyst" onSubmit={async (e) => {
              e.preventDefault();
              setError(null); setBusy(true);
              try { await workApi.startFromBrief(projectId, chosen, note, reason); load(); }
              catch (err) { setError(problem(err)); }
              finally { setBusy(false); }
            }}>
              <label>Client-approved brief
                <select value={chosen} onChange={(e) => setPackageId(e.target.value)}>
                  {ready.map((p) => <option key={p.id} value={p.id}>Package {p.number}: {p.brief.key} v{p.brief.number}</option>)}
                </select>
              </label>
              <label>Note for the Business Analyst<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
              {forPm && (
                <label>Why you start it instead of the Project Manager (required)
                  <input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
              )}
              <button type="submit" disabled={busy || !chosen || (forPm && !reason.trim()) || status.team_gaps.length > 0}>
                {forPm ? "Start delivery for the Project Manager" : "Hand to the Business Analyst and start"}</button>
            </form>
          )}
      <h3>Handoffs</h3>
      <Handoffs key={String(status.started)} projectId={projectId} department={PM} canEdit={status.is_project_manager} />
    </div>
  );
}
