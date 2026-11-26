import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, request } from "../api";
import type { WorkspaceEventDto } from "../workspace/liveEvents";

// The Developer AI (Phase 2e). A developer gives it a task or a user story; it plans, commits to its own branch
// (ai/dev-n), builds and tests in the executor, repairs real failures at most twice, and opens a change set. It never
// approves or merges, and the person who asked cannot approve its change set either: another engineer reviews it.

export interface DevAiRunDto {
  id: string; number: number; status: string; task: string; story: { id: string; key: string; title: string } | null;
  base_branch: string; branch: string; plan: string; notes: string; attempts: number; head_sha: string;
  checks_passed: boolean | null; change_set: { id: string; number: number; status: string } | null; failure: string;
  requested_by: string | null; created_at: string | null; finished_at: string | null;
  steps: { at: string; step: string; text: string; data?: Record<string, unknown> }[];
}
interface StoryDto { id: string; key: string; title: string; status: string }

const base = (p: string) => `/api/v1/projects/${encodeURIComponent(p)}/developer-ai`;
export const devAiApi = {
  runs: (p: string) => request<{ items: DevAiRunDto[] }>("GET", base(p)),
  stories: (p: string) => request<{ items: StoryDto[] }>("GET", `${base(p)}/stories`),
  start: (p: string, body: { task: string; story_item_id: string | null; base_branch: string }) =>
    request<DevAiRunDto>("POST", base(p), body),
  cancel: (p: string, id: string) => request<DevAiRunDto>("POST", `${base(p)}/${encodeURIComponent(id)}/cancel`),
};

const ACTIVE = ["queued", "working"];
const LABEL: Record<string, string> = {
  queued: "queued", working: "working", in_review: "change set in review", checks_failed: "checks failed",
  failed: "failed", cancelled: "cancelled",
};
const ICON: Record<string, string> = {
  started: "•", read: "▤", plan: "✦", repair: "↻", commit: "⑂", checks: "▷", change_set: "✓", failed: "✗",
  checks_failed: "✗", cancelled: "■",
};

export function aiStatus(runs: DevAiRunDto[]): string {
  const latest = runs[0];
  if (!latest) return "AI: idle";
  return `AI: run ${latest.number} ${LABEL[latest.status] ?? latest.status}`;
}

export function DeveloperAiPanel({ projectId, branch, events, onRuns, onOpenChangeSet }: {
  projectId: string; branch: string; events: WorkspaceEventDto[]; onRuns: (runs: DevAiRunDto[]) => void;
  onOpenChangeSet: (changeSetId: string) => void;
}) {
  const [runs, setRuns] = useState<DevAiRunDto[]>([]);
  const [stories, setStories] = useState<StoryDto[]>([]);
  const [task, setTask] = useState("");
  const [story, setStory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const seen = useRef(0);

  const load = useCallback(async () => {
    const r = await devAiApi.runs(projectId);
    setRuns(r.items); onRuns(r.items);
  }, [projectId, onRuns]);

  useEffect(() => {
    void load().catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the Developer AI"));
    void devAiApi.stories(projectId).then((r) => setStories(r.items)).catch(() => undefined);
  }, [load, projectId]);

  // Each step the AI takes arrives as a live event; poll too while a run is active, in case the socket is down.
  useEffect(() => {
    const fresh = events.filter((e) => e.id > seen.current);
    if (!fresh.length) return;
    seen.current = fresh[fresh.length - 1].id;
    if (fresh.some((e) => e.kind.startsWith("developer_ai.") || e.kind.startsWith("change_set."))) void load().catch(() => undefined);
  }, [events, load]);
  const active = runs.some((r) => ACTIVE.includes(r.status));
  useEffect(() => {
    if (!active) return undefined;
    const t = window.setInterval(() => void load().catch(() => undefined), 4000);
    return () => window.clearInterval(t);
  }, [active, load]);

  const start = async () => {
    setBusy(true); setError(null);
    try {
      const made = await devAiApi.start(projectId, { task, story_item_id: story || null, base_branch: branch });
      setTask(""); setStory(""); setOpen(made.id);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the Developer AI");
    } finally { setBusy(false); }
  };

  return (
    <div className="stack-sm ide-devai">
      <h3>Developer AI</h3>
      <p className="ide-hint">It plans, commits to its own branch, builds and tests in an isolated container, and opens a
        change set. It never approves or merges; another engineer reviews its work.</p>
      <label className="ide-field">User story (optional)
        <select aria-label="User story" value={story} onChange={(e) => setStory(e.target.value)}>
          <option value="">No story</option>
          {stories.map((s) => <option key={s.id} value={s.id}>{s.key} {s.title}</option>)}
        </select>
      </label>
      <label className="ide-field">Task
        <textarea aria-label="Task for the Developer AI" rows={4} maxLength={4000} value={task}
          placeholder="What should it build or change?" onChange={(e) => setTask(e.target.value)} />
      </label>
      <button type="button" disabled={busy || active || (!task.trim() && !story)} onClick={() => void start()}>
        {active ? "Working…" : `Start from ${branch}`}</button>
      {error && <p role="alert" className="ide-error">{error}</p>}

      <h3>Runs</h3>
      {runs.length === 0 && <p className="ide-hint">No runs yet.</p>}
      <ul className="ide-list" aria-label="Developer AI runs">
        {runs.map((r) => (
          <li key={r.id}>
            <button type="button" aria-expanded={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>
              Run {r.number} · {r.story ? `${r.story.key} ` : ""}{(r.task || r.story?.title || "").slice(0, 40)}
              <span className={`ide-badge ide-${r.status}`}>{LABEL[r.status] ?? r.status}</span>
            </button>
            {open === r.id && (
              <div className="ide-devai-run" aria-label={`Developer AI run ${r.number}`}>
                <p className="ide-hint">Branch {r.branch} from {r.base_branch} · asked by {r.requested_by ?? "someone"} · {r.attempts} round(s)</p>
                {r.plan && <><h4>Plan</h4><p className="ide-pre">{r.plan}</p></>}
                <ol className="ide-steps">
                  {r.steps.map((s, i) => <li key={i}><span aria-hidden="true">{ICON[s.step] ?? "•"}</span> {s.text}</li>)}
                </ol>
                {r.notes && <><h4>Notes</h4><p className="ide-pre">{r.notes}</p></>}
                {r.failure && r.status !== "in_review" && <p className="ide-error">{r.failure}</p>}
                <div className="ide-row">
                  {r.change_set && <button type="button" onClick={() => onOpenChangeSet(r.change_set!.id)}>
                    Review change set #{r.change_set.number}</button>}
                  {ACTIVE.includes(r.status) && <button type="button" onClick={() => void devAiApi.cancel(projectId, r.id).then(load)
                    .catch((e) => setError(e instanceof ApiError ? e.message : "Could not cancel"))}>Cancel run</button>}
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
