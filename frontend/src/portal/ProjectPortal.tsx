import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PROFILES, TABS_FOR, type PortalTab } from "./roles";
import { Avatar, EmptyState, IdentityTag, LiveIndicator, PageHeader, Panel, Skeleton, StatusPill, When } from "../components/ui";
import { ActivityMenu } from "./ActivityMenu";
import { DepartmentStatus, TeamChat, Tickets, projectChat } from "./Collaboration";
import { ApiError, api, type ClientBriefDto, type ClientProgressDto, type ScopeDto, type DeliverableDto, type FeedbackDto, type IntakeDto, type PortalMessageDto, type WorkspaceDto } from "../api";


function problem(err: unknown): string {
  return err instanceof ApiError ? err.message : "That did not work. Please try again.";
}

/** Shows a deliverable as readable text. Everything renders as plain text, never as HTML. */
export function ContentView({ value }: { value: unknown }): ReactNode {
  if (Array.isArray(value)) return <ul>{value.map((v, i) => <li key={i}><ContentView value={v} /></li>)}</ul>;
  if (value && typeof value === "object") {
    return (
      <dl className="content-view">
        {Object.entries(value).map(([k, v]) => (
          <div key={k}><dt>{k.replace(/_/g, " ")}</dt><dd><ContentView value={v} /></dd></div>
        ))}
      </dl>
    );
  }
  return <>{String(value ?? "")}</>;
}

const DONE = ["Approved", "Completed"];

type PhaseState = "done" | "active" | "todo";
function phaseState(stages: { status: string }[]): PhaseState {
  if (stages.every((s) => DONE.includes(s.status))) return "done";
  return stages.some((s) => !DONE.includes(s.status) && s.status !== "Not Started") ? "active" : "todo";
}

function Lifecycle({ data }: { data: WorkspaceDto }) {
  if (data.phases.length === 0) {
    return <EmptyState title="The lifecycle has not started.">It starts when the project brief is confirmed.</EmptyState>;
  }
  return (
    <div className="stack">
      <h2 className="sr-only">Lifecycle</h2>
      {data.phases.map((phase, index) => {
        const done = phase.stages.filter((s) => DONE.includes(s.status)).length;
        const state = phaseState(phase.stages);
        return (
          <section key={phase.name} className={`phase phase-${state}`} aria-label={phase.name}>
            <div className="phase-head">
              <span className="phase-index" aria-hidden="true">{state === "done" ? "✓" : index + 1}</span>
              <h3>{phase.name}</h3>
              <span className="muted">{done} of {phase.stages.length} done</span>
            </div>
            <ul className="steps">
              {phase.stages.map((s) => (
                <li key={s.id} className={`step step-${DONE.includes(s.status) ? "done" : s.status === "Not Started" ? "todo" : "active"}`}>
                  <span className="step-name">{s.number} {s.name} <span className="muted">· {s.profile}</span></span>
                  <StatusPill label={s.status} />
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** The owner answers a professional's question. The answer goes to the AI as feedback; the professional decides. */
function OwnerAnswer({ projectId, questionId, step, from, question, onChange }: {
  projectId: string; questionId: string; step: string; from: string; question: string; onChange: () => void;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function send(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.answerQuestion(projectId, questionId, text);
      setText("");
      onChange();
    } catch (err) {
      setError(problem(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="row-main owner-answer" onSubmit={(e) => void send(e)}>
      <strong>{from} asks about {step}</strong>
      <span>{question}</span>
      <label>Your answer<textarea rows={2} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} /></label>
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" disabled={busy || !text.trim()}>Send answer</button>
    </form>
  );
}

/** The professional team's controls on a step: ask the owner, escalate, or resolve an escalation. */
function Supervise({ projectId, item, onChange }: { projectId: string; item: DeliverableDto; onChange: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function run(work: () => Promise<unknown>) {
    setError(null);
    try {
      await work();
      setText("");
      onChange();
    } catch (err) {
      setError(problem(err));
    }
  }
  const field = (label: string) => (
    <label>{label}<textarea rows={2} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} /></label>
  );
  if (item.escalation) {
    return (
      <div className="callout callout-retry stack-sm" role="note">
        <strong>Paused by an escalation</strong>
        <span>{item.escalation.reason}</span>
        <span className="muted small">Nothing runs and nothing can be approved on this step until it is resolved.</span>
        {item.can_supervise && <>{field("How it was resolved")}
          <button type="button" disabled={text.trim().length < 3}
            onClick={() => void run(() => api.resolveEscalation(projectId, item.escalation!.id, text))}>Resolve escalation</button></>}
        {error && <p role="alert" className="error">{error}</p>}
      </div>
    );
  }
  if (item.question) {
    return (
      <div className="callout stack-sm" role="note">
        <strong>Waiting for the owner's answer</strong>
        <span>{item.question.text}</span>
        <span className="muted small">Their answer goes to the AI as feedback, then the step comes back to you to decide.</span>
        {item.can_supervise && <button type="button" className="secondary"
          onClick={() => void run(() => api.withdrawQuestion(projectId, item.question!.id))}>Withdraw the question</button>}
        {error && <p role="alert" className="error">{error}</p>}
      </div>
    );
  }
  if (!item.can_supervise) return null;
  return (
    <div className="supervise">
      {item.can_decide && item.status === "Awaiting Review" && (
        <details>
          <summary>Ask the owner a question</summary>
          <div className="stack-sm">
            {field("Your question")}
            <button type="button" disabled={text.trim().length < 3}
              onClick={() => void run(() => api.askOwner(projectId, item.stage, text))}>Send to the owner</button>
          </div>
        </details>
      )}
      {!["Approved", "Completed"].includes(item.status) && (
        <details>
          <summary>Escalate this step</summary>
          <div className="stack-sm">
            {field("Why it needs to pause")}
            <button type="button" className="secondary" disabled={text.trim().length < 3}
              onClick={() => void run(() => api.escalate(projectId, item.stage, text))}>Escalate and pause</button>
          </div>
        </details>
      )}
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  );
}

function Overview({ data, projectId, onReview, onBrief, onChange }: {
  data: WorkspaceDto; projectId: string; onReview: (stage: string) => void; onBrief: () => void; onChange: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [allActivity, setAllActivity] = useState(false);
  async function retry(stage: string) {
    setError(null);
    try {
      await api.portalRetry(projectId, stage);
      onChange();
    } catch (err) {
      setError(problem(err));
    }
  }
  const activity = allActivity ? data.activity : data.activity.slice(0, 6);
  return (
    <div className="overview-grid">
      <div className="stack">
        <Panel title="Progress" aside={<strong className="big-number">{data.progress}%</strong>}>
          <div className="progress" role="progressbar" aria-label="Overall progress" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={data.progress}><span style={{ width: `${data.progress}%` }} /></div>
          {data.phases.length > 0 && (
            <ol className="phase-strip" aria-label="Phases">
              {data.phases.map((phase) => (
                <li key={phase.name} className={`phase-chip phase-${phaseState(phase.stages)}`}>{phase.name}</li>
              ))}
            </ol>
          )}
          {data.current_step ? (
            <p className="now">
              <span className="muted">Now</span> <strong>{data.current_step.number} {data.current_step.name}</strong>
              <span className="muted"> · {data.current_step.profile}</span> <StatusPill label={data.current_step.status} />
            </p>
          ) : <p className="muted">Work starts once the project brief is confirmed.</p>}
        </Panel>

        {error && <p role="alert" className="error">{error}</p>}
        <Panel title="Waiting for you"
          aside={data.pending_actions.length > 0 ? <StatusPill label={String(data.pending_actions.length)} tone="pending" /> : undefined}>
          {data.pending_actions.length === 0 && <EmptyState title="Nothing right now.">We will let you know when the team needs you.</EmptyState>}
          <ul className="rows">
            {data.pending_actions.map((a) => (
              <li key={`${a.kind}-${a.stage}-${a.question_id ?? ""}`} className={`row-item callout callout-${a.kind}`}>
                {a.kind === "question" && a.question_id ? (
                  <OwnerAnswer projectId={projectId} questionId={a.question_id} step={a.what} from={a.from ?? "Your team"}
                    question={a.why} onChange={onChange} />
                ) : <span className="row-main"><strong>{a.what}</strong><span className="muted">{a.why}</span></span>}
                {a.action && a.kind !== "question" && (
                  <button type="button" aria-label={`${a.action}: ${a.what}`} onClick={() => {
                    if (a.kind === "retry") void retry(a.stage);
                    else if (a.kind === "review") onReview(a.stage);
                    else onBrief();
                  }}>{a.action}</button>
                )}
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Recent activity">
          {data.activity.length === 0 && <EmptyState title="No activity yet." />}
          <ol className="timeline">
            {activity.map((a, i) => (
              <li key={i}><span className="timeline-dot" aria-hidden="true" /><span>{a.text}</span><When at={a.at} /></li>
            ))}
          </ol>
          {data.activity.length > 6 && (
            <button type="button" className="link-button" onClick={() => setAllActivity(!allActivity)}>
              {allActivity ? "Show less" : `Show all ${data.activity.length}`}
            </button>
          )}
        </Panel>
      </div>

      <Panel title="Your project team" aside={<IdentityTag kind="ai">AI-assisted</IdentityTag>}>
        <p className="hint">Each department has specialist AI agents. The named professional approves its work.</p>
        <div className="team-list">
          {data.team.map((m) => (
            <article key={m.profile} className="team-row" aria-label={m.representative}>
              <div className="team-row-head">
                <strong>{m.representative}</strong>
                {m.stages_total > 0 && <StatusPill label={m.status} />}
              </div>
              <div className="team-row-people">
                {m.assigned.length
                  ? m.assigned.map((name) => <span key={name} className="person"><Avatar name={name} size="sm" />{name}</span>)
                  : <span className="muted">No professional assigned yet</span>}
              </div>
              {m.stages_total > 0 ? (
                <div className="mini-progress">
                  <span className="mini-bar" aria-hidden="true"><span style={{ width: `${(m.stages_done / m.stages_total) * 100}%` }} /></span>
                  <span className="muted">{m.stages_done} of {m.stages_total} steps</span>
                </div>
              ) : <span className="muted small">No steps in this plan</span>}
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}

const TAG_NAMES: Record<string, string> = {
  explicit: "You told us", inferred: "Assumption", uncertain: "Unclear", needs_clarification: "Needs your answer",
};

/** The brief the PM approved, for the client to approve or send back with changes. Delivery starts only after the
 * client approves it. */
function ApprovedBrief({ projectId, onChange }: { projectId: string; onChange: () => void }) {
  const [data, setData] = useState<ClientBriefDto | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.portalProjectBrief(projectId).then(setData).catch((e: unknown) => setError(problem(e))), [projectId]);
  useEffect(() => { void load(); }, [load]);
  const brief = data?.brief;
  if (!brief) return null;
  const decide = async (decision: "approve" | "request_changes") => {
    setError(null);
    try { setData(await api.portalDecideBrief(projectId, brief.package_id, decision, note)); setNote(""); onChange(); }
    catch (err) { setError(problem(err)); }
  };
  const said: Record<string, string> = {
    awaiting: "Waiting for your approval", approved: "You approved this brief", changes_requested: "You asked for changes",
    withdrawn: "Withdrawn: your Project Manager is preparing a new version",
  };
  return (
    <section className="panel stack-sm" aria-label="Your project brief">
      <div className="row"><h3>{brief.key} · {brief.title} (version {brief.version})</h3>
        <StatusPill label={said[brief.client_status] ?? brief.client_status} /></div>
      {brief.kind_of_work && <p><strong>Kind of work:</strong> {brief.kind_of_work}</p>}
      {brief.sections.filter((s) => s.heading !== "Kind of work").map((s) => (
        <div key={s.heading}><h4>{s.heading}</h4><p className="prewrap">{s.content}</p></div>
      ))}
      {brief.client_note && brief.client_status !== "awaiting" && <p className="muted">Your note: {brief.client_note}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {brief.can_decide && (
        <div className="stack-sm">
          <label>Your comments<textarea rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} /></label>
          <div className="actions">
            <button type="button" onClick={() => void decide("approve")}>Approve the brief</button>
            <button type="button" className="secondary" disabled={!note.trim()} onClick={() => void decide("request_changes")}>Ask for changes</button>
          </div>
          <p className="muted small">The work starts only after you approve the brief.</p>
        </div>
      )}
    </section>
  );
}

function Brief({ projectId, isOwner, onChange }: { projectId: string; isOwner: boolean; onChange: () => void }) {
  const [intake, setIntake] = useState<IntakeDto | null>(null);
  const [field, setField] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [accepted, setAccepted] = useState<string[]>([]);
  const [scope, setScope] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.portalIntake(projectId).then(setIntake), [projectId]);
  useEffect(() => { load().catch((e: unknown) => setError(problem(e))); }, [load]);
  if (!intake) return error ? <p role="alert" className="error">{error}</p> : <Skeleton title={false} />;
  const asked = field ? intake.questions.find((q) => q.field === field) ?? null : intake.next_question;
  const open = isOwner && !intake.started;

  async function send(kind: "answer" | "dont_know" | "you_decide") {
    if (!asked) return;
    setError(null);
    try {
      setIntake(await api.portalAnswer(projectId, asked.field, kind, kind === "answer" ? text : ""));
      setText("");
      setField(null);
      onChange();
    } catch (err) {
      setError(problem(err));
    }
  }

  async function confirm() {
    setError(null);
    try {
      await api.portalConfirm(projectId, intake!.revision, accepted, scope || intake!.default_scope);
      await load();
      onChange();
    } catch (err) {
      setError(problem(err));
    }
  }

  return (
    <div className="stack">
      {error && <p role="alert" className="error">{error}</p>}
      {intake.started && <p className="notice">Your team is working from this confirmed brief.</p>}
      {open && asked && (
        <form className="stack-sm" onSubmit={(e: FormEvent) => { e.preventDefault(); void send("answer"); }}>
          <label>{asked.question}<textarea rows={3} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} /></label>
          <div className="actions">
            <button type="submit" disabled={!text.trim()}>Save answer</button>
            <button type="button" className="secondary" onClick={() => void send("dont_know")}>I don't know</button>
            <button type="button" className="secondary" onClick={() => void send("you_decide")}>You decide</button>
          </div>
        </form>
      )}
      <section>
        <h2>What we understand so far</h2>
        {intake.items.length === 0 && <p className="muted">Nothing yet.</p>}
        <ul className="list">
          {intake.items.map((item) => (
            <li key={item.field} className="row">
              <span><strong>{item.label}</strong> <StatusPill label={TAG_NAMES[item.tag]} /><br />{item.value}</span>
              {open && (
                <span className="actions">
                  {item.tag === "inferred" && (
                    <label className="check">
                      <input type="checkbox" checked={accepted.includes(item.field)} onChange={(e) => setAccepted(
                        e.target.checked ? [...accepted, item.field] : accepted.filter((f) => f !== item.field))} />
                      Accept this assumption
                    </label>
                  )}
                  <button type="button" className="secondary" aria-label={`Change ${item.label}`}
                    onClick={() => { setField(item.field); setText(item.tag === "explicit" ? item.value : ""); }}>Change</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>
      {open && intake.pm_led && (
        <div className="stack-sm">
          <p className="muted">These answers help your Project Manager prepare. Your Project Manager meets you, writes
            the project brief and starts the work once it is approved.</p>
          {intake.sent_to_pm
            ? <p role="status" className="small">Sent to your Project Manager. You can still change your answers.</p>
            : (
              <button type="button" disabled={!intake.can_send} onClick={async () => {
                setError(null);
                try { setIntake(await api.portalSendToPm(projectId, intake.revision)); onChange(); }
                catch (err) { setError(problem(err)); }
              }}>Send to your Project Manager</button>
            )}
        </div>
      )}
      {open && !intake.pm_led && (
        <div className="stack-sm">
          {intake.still_needed.length > 0 && <p className="muted">Still needed: {intake.still_needed.join(", ")}.</p>}
          <label>
            What kind of work is this?
            <select value={scope || intake.default_scope} onChange={(e) => setScope(e.target.value)}>
              {intake.scopes.map((s) => <option key={s.key} value={s.key}>{s.label} ({s.stages} steps)</option>)}
            </select>
          </label>
          <button type="button" disabled={!intake.can_confirm} onClick={() => void confirm()}>Confirm and start</button>
        </div>
      )}
    </div>
  );
}

function Deliverables({ projectId, tick, role, wanted, profile, onChange }: {
  projectId: string; tick: number; role: string; wanted: string; profile: string | null; onChange: () => void;
}) {
  const [items, setItems] = useState<DeliverableDto[] | null>(null);
  const [selected, setSelected] = useState(wanted);
  const [versionId, setVersionId] = useState("");
  const [compareId, setCompareId] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const attempt = useRef<string | null>(null);

  useEffect(() => {
    api.portalDeliverables(projectId).then((r) => {
      setItems(r.items);
      setSelected((s) => s || r.items.find((d) => d.can_decide)?.stage || r.items[r.items.length - 1]?.stage || "");
    }).catch((e: unknown) => setError(problem(e)));
  }, [projectId, tick]);

  if (!items) return error ? <p role="alert" className="error">{error}</p> : <Skeleton title={false} lines={4} />;
  const department = PROFILES.find(([key]) => key === profile)?.[1];
  const shown = profile ? items.filter((d) => d.profile === profile) : items;
  if (shown.length === 0) {
    return <p className="muted">{department ? `The ${department} has nothing ready to view yet.` : "Nothing is ready to view yet."}</p>;
  }
  const item = shown.find((d) => d.stage === selected) ?? shown[shown.length - 1];
  const version = item.versions.find((v) => v.id === versionId) ?? item.versions[0];
  const other = item.versions.find((v) => v.id === compareId);
  const isCurrent = version.id === item.current_version_id;

  async function decide(decision: "APPROVE" | "REJECT" | "REQUEST_CHANGES", done: string) {
    setError(null);
    setNotice(null);
    attempt.current ??= crypto.randomUUID();
    try {
      await api.portalDecide(projectId, item.stage, version.id, decision, comment, attempt.current);
      attempt.current = null;
      setComment("");
      setVersionId("");
      setCompareId("");
      setNotice(done);
      onChange();
    } catch (err) {
      if (err instanceof ApiError) attempt.current = null;
      setError(problem(err));
    }
  }

  return (
    <div className="stack">
      <label>
        Deliverable
        <select value={item.stage} onChange={(e) => { setSelected(e.target.value); setVersionId(""); setCompareId(""); setNotice(null); }}>
          {shown.map((d) => <option key={d.stage} value={d.stage}>{d.number} {d.name} ({d.status})</option>)}
        </select>
      </label>
      {department && profile && role === "project_owner" && <DepartmentStatus projectId={projectId} profile={profile} tick={tick} />}
      <div className="row">
        <span>Prepared by <IdentityTag kind="ai">{item.representative} team</IdentityTag></span>
        <StatusPill label={item.status} />
      </div>
      <div className="row start">
        <label className="grow">
          Version
          <select value={version.id} onChange={(e) => setVersionId(e.target.value)}>
            {item.versions.map((v) => <option key={v.id} value={v.id}>Version {v.number}</option>)}
          </select>
        </label>
        {item.versions.length > 1 && (
          <label className="grow">
            Compare with
            <select value={compareId} onChange={(e) => setCompareId(e.target.value)}>
              <option value="">Nothing</option>
              {item.versions.filter((v) => v.id !== version.id).map((v) => <option key={v.id} value={v.id}>Version {v.number}</option>)}
            </select>
          </label>
        )}
      </div>
      {version.checks.length > 0 && (
        <section aria-label="Real build and test results">
          <h3>Build and test results</h3>
          <ul className="list">
            {version.checks.map((c) => (
              <li key={c.name} className="row">
                <span>{c.name}: {c.summary}</span>
                <StatusPill label={c.passed ? "Passed" : "Failed"} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {item.can_view_code && version.has_code && (
        <a href={`/api/v1/portal/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(version.id)}/code.zip`}>
          Download code for version {version.number}
        </a>
      )}
      <div className={other ? "compare" : ""}>
        <article aria-label={`Version ${version.number}`}><ContentView value={version.content} /></article>
        {other && <article aria-label={`Version ${other.number}`}><ContentView value={other.content} /></article>}
      </div>
      {notice && <p role="status" className="notice">{notice}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {item.checks_blocking && <p className="error">A required quality or security check has not passed, so this cannot be approved yet.</p>}
      {item.can_decide && isCurrent && (
        <div className="stack-sm">
          {item.waiting_for_client && role === "project_owner" && (
            <p className="notice small">{item.sign_off}: your {item.representative} has approved this version. It now needs
              your approval.</p>
          )}
          <label>Your comments<textarea rows={3} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
          <div className="actions">
            <button type="button" onClick={() => void decide("APPROVE", `Version ${version.number} approved.`)}>Approve version {version.number}</button>
            <button type="button" className="secondary" disabled={!comment.trim()}
              onClick={() => void decide("REQUEST_CHANGES", "Your changes were sent to the team.")}>Request changes</button>
            {role !== "project_owner" && (
              <button type="button" className="secondary" disabled={!comment.trim()}
                onClick={() => void decide("REJECT", "This deliverable was rejected.")}>Reject</button>
            )}
          </div>
        </div>
      )}
      {!item.can_decide && role === "project_owner" && item.status === "Awaiting Review" && isCurrent && (
        <div className="stack-sm">
          <p className="muted">{item.sign_off
            ? `${item.sign_off}: your ${item.representative} approves this first, then you give your approval.`
            : `Your ${item.representative} approves this step. You can read it and ask for changes.`}</p>
          <label>Your feedback<textarea rows={3} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
          <button type="button" className="secondary" disabled={!comment.trim()}
            onClick={() => void decide("REQUEST_CHANGES", "Your changes were sent to the team.")}>Request changes</button>
        </div>
      )}
      {isCurrent && <Supervise projectId={projectId} item={item} onChange={onChange} />}
      {item.change_requests.length > 0 && (
        <section>
          <h3>Requested changes</h3>
          <ul className="list">{item.change_requests.map((c, i) => <li key={i}>{c.comment} <span className="muted">· {c.status}</span></li>)}</ul>
        </section>
      )}
    </div>
  );
}

/** P5: progress from records, what waits for the client's approval, and a change request to the PM. */
function Progress({ projectId, data, tick, onReview }: {
  projectId: string; data: WorkspaceDto; tick: number; onReview: (stage: string) => void;
}) {
  const [progress, setProgress] = useState<ClientProgressDto | null>(null);
  const [summary, setSummary] = useState("");
  const [details, setDetails] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.portalProgress(projectId).then(setProgress).catch((e: unknown) => setError(problem(e))); }, [projectId, tick]);
  if (!progress) return error ? <p role="alert" className="error">{error}</p> : <Skeleton title={false} />;
  return (
    <div className="stack">
      <section className="panel stack-sm" aria-label="Where the project stands">
        <h3>{progress.phase}</h3>
        {progress.phase === "Discovery"
          ? <p className="muted">Your Project Manager is preparing the project brief with you. Delivery starts once it is approved.</p>
          : <p>{progress.steps_done} of {progress.steps_total} steps done.</p>}
      </section>
      {progress.awaiting_you.length > 0 && (
        <section className="notice stack-sm" aria-label="Waiting for your approval">
          <strong>Waiting for your approval</strong>
          <ul className="list">{progress.awaiting_you.map((a) => (
            <li key={a.stage} className="row"><span>{a.sign_off ?? a.name}</span>
              <button type="button" className="secondary" onClick={() => onReview(a.stage)}>Review</button></li>
          ))}</ul>
        </section>
      )}
      <section className="stack-sm" aria-label="Approved deliverables">
        <h3>Approved deliverables</h3>
        {progress.approved.length === 0 ? <p className="muted">Nothing approved yet.</p> : (
          <ul className="list">{progress.approved.map((a) => (
            <li key={a.stage}>{a.sign_off ? `${a.sign_off} (${a.name})` : a.name}, version {a.version}
              {a.approved_at && <span className="muted small"> · {new Date(a.approved_at).toLocaleDateString()}</span>}</li>
          ))}</ul>
        )}
        <p className="muted small">Sprints and milestones appear here from step {progress.arrive_in}.</p>
      </section>
      {data.pm_led && data.role === "project_owner" && (
        <form className="panel stack-sm" aria-label="Request a change" onSubmit={async (e) => {
          e.preventDefault(); setError(null); setSent(null);
          try { await api.portalRequestChange(projectId, summary.trim(), details); setSent(summary.trim()); setSummary(""); setDetails(""); }
          catch (err) { setError(problem(err)); }
        }}>
          <h3>Request a change</h3>
          <p className="muted small">Your Project Manager gets it and tells you what it would change before anything is decided.</p>
          <label>What should change?<input required minLength={3} maxLength={300} value={summary} onChange={(e) => setSummary(e.target.value)} /></label>
          <label>Details<textarea rows={3} maxLength={4000} value={details} onChange={(e) => setDetails(e.target.value)} /></label>
          {error && <p role="alert" className="error">{error}</p>}
          {sent && <p role="status" className="small">Sent to your Project Manager: {sent}</p>}
          <button type="submit" disabled={summary.trim().length < 3}>Send change request</button>
        </form>
      )}
    </div>
  );
}

function Conversations({ projectId, data, tick }: { projectId: string; data: WorkspaceDto; tick: number }) {
  const [items, setItems] = useState<PortalMessageDto[]>([]);
  const people = data.conversation_with ?? data.team.map((m) => ({ profile: m.profile, representative: m.representative }));
  const [profile, setProfile] = useState(people[0]?.profile ?? "");
  const professional = data.scope === "professional" || data.scope === "admin";
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.portalMessages(projectId).then((r) => setItems(r.items)), [projectId]);
  useEffect(() => { load().catch((e: unknown) => setError(problem(e))); }, [load, tick]);

  async function send(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (data.role === "project_owner") await api.portalSendMessage(projectId, body, profile);
      else await api.replyToOwner(projectId, profile, body);
      setBody("");
      await load();
    } catch (err) {
      setError(problem(err));
    }
  }

  return (
    <div className="stack">
      {items.length === 0 && <EmptyState title="No messages yet.">Questions you send to a department show up here with their replies.</EmptyState>}
      <ul className="messages" aria-label="Messages">
        {items.map((m) => (
          <li key={m.id} className={m.mine ? "message mine" : "message"}>
            <div className="message-head">
              {m.mine ? <IdentityTag kind="human">You</IdentityTag>
                : <IdentityTag kind={m.author_type === "professional" || m.author_type === "owner" ? "human" : "ai"}>
                  {m.author_type === "owner" ? "Project owner" : m.from}</IdentityTag>}
            </div>
            <div>{m.body}</div>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="error">{error}</p>}
      {(data.role === "project_owner" || professional) && (
        <form className="stack-sm" onSubmit={(e) => void send(e)}>
          <label>
            {data.role === "project_owner" ? "Send to" : "Reply as"}
            <select value={profile} onChange={(e) => setProfile(e.target.value)}>
              {people.map((m) => <option key={m.profile} value={m.profile}>{m.representative}</option>)}
            </select>
          </label>
          <label>Your message<textarea required rows={3} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)} /></label>
          <button type="submit" disabled={!body.trim()}>{data.role === "project_owner" ? "Send message" : "Reply to owner"}</button>
        </form>
      )}
    </div>
  );
}

const KINDS = ["defect", "new_requirement", "enhancement", "usability", "security_concern", "scope_change"];
const STATUSES = ["open", "triaged", "in_progress", "resolved", "rejected"];

function Testing({ projectId, data, tick }: { projectId: string; data: WorkspaceDto; tick: number }) {
  const [items, setItems] = useState<FeedbackDto[]>([]);
  const [form, setForm] = useState({ steps: "", expected: "", actual: "", severity: "medium" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => api.portalFeedback(projectId).then((r) => setItems(r.items)), [projectId]);
  useEffect(() => { load().catch((e: unknown) => setError(problem(e))); }, [load, tick]);
  const status = data.phases.flatMap((p) => p.stages).find((s) => s.id === "build_and_test")?.status;
  const open = status !== undefined && status !== "Not Started" && status !== "In Progress";

  async function run(work: () => Promise<unknown>, done: string) {
    setError(null);
    setNotice(null);
    try {
      await work();
      await load();
      setNotice(done);
      return true;
    } catch (err) {
      setError(problem(err));
      return false;
    }
  }

  return (
    <div className="stack">
      {notice && <p role="status" className="notice">{notice}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {!open && <p className="muted">Testing has not opened yet.</p>}
      {open && data.role === "project_owner" && (
        <form className="stack-sm" onSubmit={(e) => {
          e.preventDefault();
          void run(() => api.portalTestReport(projectId, form), "Your report was sent to the QA team.").then((ok) => {
            if (ok) setForm({ steps: "", expected: "", actual: "", severity: "medium" });
          });
        }}>
          <h2>Report what you found</h2>
          <label>What did you do?<textarea required rows={2} value={form.steps} onChange={(e) => setForm({ ...form, steps: e.target.value })} /></label>
          <label>What did you expect?<input required value={form.expected} onChange={(e) => setForm({ ...form, expected: e.target.value })} /></label>
          <label>What happened?<input required value={form.actual} onChange={(e) => setForm({ ...form, actual: e.target.value })} /></label>
          <label>
            How serious is it?
            <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
              <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
            </select>
          </label>
          <button type="submit">Send report</button>
        </form>
      )}
      <section>
        <h2>Feedback and reports</h2>
        {items.length === 0 && <EmptyState title="Nothing has been reported." />}
        <ul className="list">
          {items.map((f) => (
            <li key={f.id} className="stack-sm">
              <div>{f.summary}</div>
              <div className="muted">{f.kind.replace(/_/g, " ")} · {f.status.replace(/_/g, " ")} · with {f.handled_by}</div>
              {data.can_triage && (
                <div className="actions">
                  <select aria-label="Type" defaultValue={f.kind} id={`kind-${f.id}`}>{KINDS.map((k) => <option key={k} value={k}>{k}</option>)}</select>
                  <select aria-label="Status" defaultValue={f.status} id={`status-${f.id}`}>{STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}</select>
                  <button type="button" className="secondary" onClick={() => void run(() => api.portalTriage(projectId, f.id,
                    (document.getElementById(`kind-${f.id}`) as HTMLSelectElement).value,
                    (document.getElementById(`status-${f.id}`) as HTMLSelectElement).value, "Reviewed by QA"), "Feedback updated.")}>Update</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export function ProjectPortal({ projectId }: { projectId: string }) {
  const [data, setData] = useState<WorkspaceDto | null>(null);
  const [params, setParams] = useSearchParams();
  const [wanted, setWanted] = useState(params.get("review") ?? "");
  const [scope, setScope] = useState<ScopeDto | null>(null);
  useEffect(() => { api.portalScope(projectId).then(setScope).catch(() => setScope(null)); }, [projectId]);
  const chat = useMemo(() => (scope ? projectChat(projectId, scope) : null), [projectId, scope]);
  const allowed = TABS_FOR[scope?.kind ?? "member"];
  const asked = params.get("tab");
  const fallback: PortalTab = wanted ? (scope?.kind === "professional" ? "Workspace" : "Deliverables") : allowed[0];
  const tab: PortalTab = allowed.includes(asked as PortalTab) ? (asked as PortalTab) : fallback;
  const profile = tab === "Deliverables" || tab === "Workspace" ? params.get("profile") : null;
  const department = tab === "Workspace" ? (profile && scope?.profiles.includes(profile) ? profile : scope?.profiles[0] ?? "") : "";
  const setTab = (next: PortalTab) => setParams((prev) => {
    const out = new URLSearchParams(prev);
    out.set("tab", next);
    out.delete("profile");
    return out;
  });
  const [tick, setTick] = useState(0);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    api.portalWorkspace(projectId).then((d) => { setData(d); setError(null); setTick((n) => n + 1); setUpdated(new Date()); })
      .catch((e: unknown) => setError(e instanceof ApiError && e.status === 404 ? "Project not found." : "Could not load the project."));
  }, [projectId]);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => { if (!document.hidden) refresh(); }, 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (!data || !scope) return error ? <p role="alert" className="error">{error}</p> : <div className="page"><Skeleton lines={5} /></div>;
  const departmentName = PROFILES.find(([key]) => key === department)?.[1] ?? "";
  const views: Record<string, string> = { owner: "You own this project", admin: "Administrator view", manager: "Project manager view" };
  const yourRole = scope.kind === "professional"
    ? `Your role: ${scope.profiles.map((p) => PROFILES.find(([k]) => k === p)?.[1]).join(", ")}`
    : views[scope.kind];
  return (
    <div className="page project-page">
      <div className="page-topbar">
        <nav aria-label="Breadcrumb" className="crumbs"><Link to="/">My projects</Link><span aria-hidden="true">/</span><span>{data.project.name}</span></nav>
        {(scope.kind === "admin" || scope.kind === "manager" || scope.kind === "professional") &&
          <ActivityMenu projectId={projectId} />}
      </div>
      <PageHeader
        title={data.project.name}
        meta={`${data.project.type} · ${data.project.status}`}
        actions={<><LiveIndicator updated={updated} />{yourRole && <span className="role-tag">{yourRole}</span>}</>}>
        {data.project.description && <p className="lede">{data.project.description}</p>}
      </PageHeader>
      <div className="tabs sticky-tabs" role="tablist" aria-label="Project sections">
        {allowed.map((t) => <button key={t} type="button" role="tab" aria-selected={tab === t}
          className={tab === t ? "tab selected" : "tab"} onClick={() => setTab(t)}>{t}</button>)}
      </div>
      <div role="tabpanel" aria-label={tab} className="tabpanel-enter" key={tab}>
        {tab === "Lifecycle" && <Lifecycle data={data} />}
        {tab === "Progress" && <Progress projectId={projectId} data={data} tick={tick}
          onReview={(stage) => { setWanted(stage); setTab("Deliverables"); }} />}
        {tab === "Workspace" && department && (
          <div className="stack">
            <h2 className="section-title">{departmentName} workspace</h2>
            <div className="split">
              <DepartmentStatus projectId={projectId} profile={department} tick={tick} />
              {scope?.channels.some((c) => c.key === department) && (
                <section className="stack-sm">
                  <h2>{departmentName} discussion on this project</h2>
                  <TeamChat key={department} source={chat!} tick={tick} initial={department}
                    label="Message your department about this project" />
                </section>
              )}
            </div>
            <section className="stack-sm">
              <h2>Work to review</h2>
              <Deliverables key={`ws-${department}-${wanted}`} projectId={projectId} tick={tick} role={data.role} wanted={wanted}
                profile={department} onChange={refresh} />
            </section>
          </div>
        )}
        {tab === "Tickets" && <Tickets projectId={projectId} scope={scope} tick={tick} />}
        {tab === "Overview" && <Overview data={data} projectId={projectId} onChange={refresh} onBrief={() => setTab("Project brief")}
          onReview={(stage) => { setWanted(stage); setTab("Deliverables"); }} />}
        {tab === "Project brief" && (
          <div className="stack">
            {data.pm_led && <ApprovedBrief projectId={projectId} onChange={refresh} />}
            <Brief projectId={projectId} isOwner={data.role === "project_owner"} onChange={refresh} />
          </div>
        )}
        {tab === "Deliverables" && <Deliverables key={`${wanted}-${profile ?? ""}`} projectId={projectId} tick={tick} role={data.role} wanted={wanted}
          profile={profile} onChange={refresh} />}
        {tab === "Conversations" && <Conversations projectId={projectId} data={data} tick={tick} />}
        {tab === "Testing" && <Testing projectId={projectId} data={data} tick={tick} />}
      </div>
    </div>
  );
}
