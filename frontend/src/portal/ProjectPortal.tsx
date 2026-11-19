import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { PROFILES } from "../components/Sidebar";
import { IdentityTag, StatusPill } from "../components/ui";
import { ApiError, api, type DeliverableDto, type FeedbackDto, type IntakeDto, type PortalMessageDto, type WorkspaceDto } from "../api";

const TABS = ["Overview", "Lifecycle", "Project brief", "Deliverables", "Conversations", "Testing"] as const;
export type PortalTab = (typeof TABS)[number];

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

function Lifecycle({ data }: { data: WorkspaceDto }) {
  if (data.phases.length === 0) return <p className="muted">The lifecycle starts when the project brief is confirmed.</p>;
  return (
    <div className="stack">
      <section>
        <h2>Lifecycle</h2>
        {data.phases.map((phase) => (
          <details key={phase.name} open={phase.stages.some((s) => !["Approved", "Completed", "Not Started"].includes(s.status))}>
            <summary>{phase.name}</summary>
            <ul className="list">
              {phase.stages.map((s) => (
                <li key={s.id} className="row">
                  <span>{s.number} {s.name} <span className="muted">· {s.profile}</span></span>
                  <StatusPill label={s.status} />
                </li>
              ))}
            </ul>
          </details>
        ))}
      </section>
    </div>
  );
}

function Overview({ data, projectId, onReview, onBrief, onChange }: {
  data: WorkspaceDto; projectId: string; onReview: (stage: string) => void; onBrief: () => void; onChange: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  async function retry(stage: string) {
    setError(null);
    try {
      await api.portalRetry(projectId, stage);
      onChange();
    } catch (err) {
      setError(problem(err));
    }
  }
  return (
    <div className="stack">
      <div>
        <div className="row"><strong>Overall progress</strong><span>{data.progress}%</span></div>
        <div className="progress" role="progressbar" aria-label="Overall progress" aria-valuemin={0} aria-valuemax={100}
          aria-valuenow={data.progress}><span style={{ width: `${data.progress}%` }} /></div>
        {data.current_step && (
          <p className="muted">Now: {data.current_step.phase} · {data.current_step.number} {data.current_step.name} · {data.current_step.profile} · {data.current_step.status}</p>
        )}
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      <section>
        <h2>Waiting for you</h2>
        {data.pending_actions.length === 0 && <p className="muted">Nothing right now.</p>}
        <ul className="list">
          {data.pending_actions.map((a) => (
            <li key={`${a.kind}-${a.stage}`} className="row">
              <span><strong>{a.what}</strong><br /><span className="muted">{a.why}</span></span>
              {a.action && (
                <button type="button" aria-label={`${a.action}: ${a.what}`} onClick={() => {
                  if (a.kind === "retry") void retry(a.stage);
                  else if (a.kind === "review") onReview(a.stage);
                  else onBrief();
                }}>{a.action}</button>
              )}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2>Your project team</h2>
        <div className="team-grid">
          {data.team.map((m) => (
            <article key={m.profile} className="team-card" aria-label={m.representative}>
              <strong>{m.representative}</strong>
              <IdentityTag kind="ai">Specialist agents</IdentityTag>
              {m.assigned.length
                ? m.assigned.map((name) => <IdentityTag key={name} kind="human">{name}</IdentityTag>)
                : <span className="muted">No professional assigned yet</span>}
              <span className="muted">{m.stages_done} of {m.stages_total} steps</span>
              <StatusPill label={m.status} />
            </article>
          ))}
        </div>
      </section>
      <section>
        <h2>Recent activity</h2>
        {data.activity.length === 0 && <p className="muted">No activity yet.</p>}
        <ul className="list">
          {data.activity.map((a, i) => (
            <li key={i} className="row">
              <span><IdentityTag kind="system" /> {a.text}</span>
              <span className="muted">{new Date(a.at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

const TAG_NAMES: Record<string, string> = {
  explicit: "You told us", inferred: "Assumption", uncertain: "Unclear", needs_clarification: "Needs your answer",
};

function Brief({ projectId, isOwner, onChange }: { projectId: string; isOwner: boolean; onChange: () => void }) {
  const [intake, setIntake] = useState<IntakeDto | null>(null);
  const [field, setField] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [accepted, setAccepted] = useState<string[]>([]);
  const [scope, setScope] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.portalIntake(projectId).then(setIntake), [projectId]);
  useEffect(() => { load().catch((e: unknown) => setError(problem(e))); }, [load]);
  if (!intake) return error ? <p role="alert" className="error">{error}</p> : <p className="muted">Loading…</p>;
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
      {open && (
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

  if (!items) return error ? <p role="alert" className="error">{error}</p> : <p className="muted">Loading…</p>;
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
      {department && <p className="eyebrow">{department} workspace</p>}
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
          <label>Your comments<textarea rows={3} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
          <div className="actions">
            <button type="button" onClick={() => void decide("APPROVE", `Version ${version.number} approved.`)}>Approve version {version.number}</button>
            <button type="button" className="secondary" disabled={!comment.trim()}
              onClick={() => void decide("REQUEST_CHANGES", "Your changes were sent to the team.")}>Request changes</button>
            <button type="button" className="secondary" disabled={!comment.trim()}
              onClick={() => void decide("REJECT", "This deliverable was rejected.")}>Reject</button>
          </div>
        </div>
      )}
      {!item.can_decide && role === "project_owner" && item.status === "Awaiting Review" && isCurrent && (
        <div className="stack-sm">
          <p className="muted">Your {item.representative} approves this step. You can read it and ask for changes.</p>
          <label>Your feedback<textarea rows={3} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
          <button type="button" className="secondary" disabled={!comment.trim()}
            onClick={() => void decide("REQUEST_CHANGES", "Your changes were sent to the team.")}>Request changes</button>
        </div>
      )}
      {item.change_requests.length > 0 && (
        <section>
          <h3>Requested changes</h3>
          <ul className="list">{item.change_requests.map((c, i) => <li key={i}>{c.comment} <span className="muted">· {c.status}</span></li>)}</ul>
        </section>
      )}
    </div>
  );
}

function Conversations({ projectId, data, tick }: { projectId: string; data: WorkspaceDto; tick: number }) {
  const [items, setItems] = useState<PortalMessageDto[]>([]);
  const [profile, setProfile] = useState(data.team[0]?.profile ?? "");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.portalMessages(projectId).then((r) => setItems(r.items)), [projectId]);
  useEffect(() => { load().catch((e: unknown) => setError(problem(e))); }, [load, tick]);

  async function send(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.portalSendMessage(projectId, body, profile);
      setBody("");
      await load();
    } catch (err) {
      setError(problem(err));
    }
  }

  return (
    <div className="stack">
      {items.length === 0 && <p className="muted">No messages yet.</p>}
      <ul className="messages" aria-label="Messages">
        {items.map((m) => (
          <li key={m.id} className={m.mine ? "message mine" : "message"}>
            <div className="message-head">
              {m.mine ? <IdentityTag kind="human">You</IdentityTag> : <IdentityTag kind="ai">{m.from}</IdentityTag>}
            </div>
            <div>{m.body}</div>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="error">{error}</p>}
      {data.role === "project_owner" && (
        <form className="stack-sm" onSubmit={(e) => void send(e)}>
          <label>
            Send to
            <select value={profile} onChange={(e) => setProfile(e.target.value)}>
              {data.team.map((m) => <option key={m.profile} value={m.profile}>{m.representative}</option>)}
            </select>
          </label>
          <label>Your message<textarea required rows={3} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)} /></label>
          <button type="submit" disabled={!body.trim()}>Send message</button>
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
        {items.length === 0 && <p className="muted">Nothing has been reported.</p>}
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
  const asked = params.get("tab");
  const tab: PortalTab = (TABS as readonly string[]).includes(asked ?? "") ? (asked as PortalTab)
    : wanted ? "Deliverables" : "Overview";
  const profile = tab === "Deliverables" ? params.get("profile") : null;
  const setTab = (next: PortalTab) => setParams((prev) => {
    const out = new URLSearchParams(prev);
    out.set("tab", next);
    out.delete("profile");
    return out;
  });
  const [tick, setTick] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    api.portalWorkspace(projectId).then((d) => { setData(d); setError(null); setTick((n) => n + 1); })
      .catch((e: unknown) => setError(e instanceof ApiError && e.status === 404 ? "Project not found." : "Could not load the project."));
  }, [projectId]);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(() => { if (!document.hidden) refresh(); }, 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (!data) return error ? <p role="alert" className="error">{error}</p> : <p className="muted">Loading…</p>;
  return (
    <section className="card stack">
      <div>
        <p className="eyebrow">Project</p>
        <h1>{data.project.name}</h1>
        <p className="muted">{data.project.type} · {data.project.status}</p>
        {data.project.description && <p>{data.project.description}</p>}
      </div>
      <div className="tabs" role="tablist" aria-label="Project sections">
        {TABS.map((t) => <button key={t} type="button" role="tab" aria-selected={tab === t}
          className={tab === t ? "tab selected" : "tab"} onClick={() => setTab(t)}>{t}</button>)}
      </div>
      <div role="tabpanel" aria-label={tab}>
        {tab === "Lifecycle" && <Lifecycle data={data} />}
        {tab === "Overview" && <Overview data={data} projectId={projectId} onChange={refresh} onBrief={() => setTab("Project brief")}
          onReview={(stage) => { setWanted(stage); setTab("Deliverables"); }} />}
        {tab === "Project brief" && <Brief projectId={projectId} isOwner={data.role === "project_owner"} onChange={refresh} />}
        {tab === "Deliverables" && <Deliverables key={`${wanted}-${profile ?? ""}`} projectId={projectId} tick={tick} role={data.role} wanted={wanted}
          profile={profile} onChange={refresh} />}
        {tab === "Conversations" && <Conversations projectId={projectId} data={data} tick={tick} />}
        {tab === "Testing" && <Testing projectId={projectId} data={data} tick={tick} />}
      </div>
    </section>
  );
}
